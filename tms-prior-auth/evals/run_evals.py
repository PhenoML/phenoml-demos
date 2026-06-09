#!/usr/bin/env python3
"""Determinism + evals scorecard for the TMS prior-auth demo (adjudicate-only).

Each case under ./cases pins its clinical inputs (a frozen submission) and exercises just the
*judgment* layer — the BCBS-MA policy #297 agent's APPROVED/DENIED adjudication — K times. We then
report the two things a payer always asks about an automated prior-auth:

  ACCURACY    — does the decision match the labeled gold outcome? (+ covered codes, cited criteria)
  DETERMINISM — is the decision STABLE across repeated runs? The PhenoML SDK exposes no
                temperature/seed knob, so we *measure* the judgment layer's stability rather than
                forcing it. The coding layer (construe CPT extraction) is schema-constrained and
                deterministic by construction — we show that too.

Run from the tms-prior-auth dir, using its v15 venv (the global Python may have a stale SDK):
  .venv/bin/python evals/run_evals.py                       # K = EVAL_REPEATS (default 5)
  .venv/bin/python evals/run_evals.py --validate            # load + check cases, NO API calls
  .venv/bin/python evals/run_evals.py --case deny-mild-mdd --repeats 3
  EVAL_CHECK_EXTRACTION=1 .venv/bin/python evals/run_evals.py   # also re-extract FHIR K× (slow)
"""
import argparse, json, os, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Reuse the demo's shared helpers (common.py defines only functions, so importing it is side-effect free).
DEMO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_ROOT))
from common import load_env, make_client, as_dict, parse_json, retry, banner, resolve_provider  # noqa: E402
from phenoml.construe import ExtractRequestSystem  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent
CASES_DIR = EVALS_DIR / "cases"
REPORT_MD = EVALS_DIR / "report.md"
REPORT_JSON = EVALS_DIR / "report.json"

# The service text + system used by the demo's construe step (step3_adjudicate.py, Step 3.1).
CPT_TEXT = ("Therapeutic repetitive transcranial magnetic stimulation (TMS) treatment; initial, "
            "including cortical mapping, motor threshold determination, delivery and management; "
            "plus subsequent delivery and management sessions.")

# The adjudication ask/schema — identical to the demo (step3_adjudicate.py, Step 3.2) so the eval grades
# exactly what the demo shows.
ADJUDICATE_SCHEMA = ('{"decision":"APPROVED"|"DENIED","covered_codes":[...],"rationale":"...",'
                     '"policy_citations":[...],"conditions_or_limits":"..."}')


# ---------- scoring helpers ----------------------------------------------
def normalize_decision(s: str) -> str:
    """Collapse the agent's decision word onto {APPROVED, DENIED} (+ EMPTY/ERROR sentinels).
    Policy #297 calls a non-meeting request 'Investigational', so anything that isn't an explicit
    approval counts as a denial."""
    t = (s or "").strip().upper()
    if not t or t == "EMPTY":
        return "EMPTY"
    if t == "ERROR":
        return "ERROR"
    # Explicit denial wording wins over the APPROV substring below, so "NOT APPROVED"
    # and "DENIED - NO APPROVAL" aren't miscounted as approvals.
    if "DENI" in t or "DENY" in t or "INVESTIGATIONAL" in t or "NOT APPROV" in t:
        return "DENIED"
    if "APPROV" in t:
        return "APPROVED"
    if "MEDICALLY NECESSARY" in t and "NOT" not in t:
        return "APPROVED"
    return "DENIED"  # DENIED / DENY / INVESTIGATIONAL / NOT MEDICALLY NECESSARY / ...


def cite_hits(must_cite_any, runs):
    """How many expected citation keywords appear anywhere in citations+rationale across the runs.
    'criterion' is normalized to 'condition' so the two synonyms match interchangeably."""
    hay = " ".join(
        json.dumps(r.get("policy_citations", [])) + " " + str(r.get("rationale", "")) for r in runs
    ).lower().replace("criterion", "condition")
    hits = [kw for kw in must_cite_any if kw.lower() in hay]
    return len(hits), len(must_cite_any)


def score_case(case, runs):
    exp = case["expected"]
    want = normalize_decision(exp["decision"])
    decisions = [normalize_decision(r.get("decision", "")) for r in runs]
    modal, agree = Counter(decisions).most_common(1)[0]
    code_sets = [tuple(sorted(set(r.get("covered_codes") or []))) for r in runs]
    rep_codes = next((cs for d, cs in zip(decisions, code_sets) if d == modal), code_sets[0])
    cited, cite_total = cite_hits(exp.get("must_cite_any", []), runs)
    return {
        "id": case["id"],
        "expected_decision": want,
        "modal_decision": modal,
        "agree": agree,
        "k": len(runs),
        "decision_correct": modal == want,
        "decision_stable": agree == len(runs),
        "rep_codes": list(rep_codes),
        "codes_correct": set(rep_codes) == set(exp.get("covered_codes", [])),
        "codes_stable": len(set(code_sets)) == 1,
        "cited": cited,
        "cite_total": cite_total,
        "decisions": decisions,
        "errors": [r["_error"] for r in runs if r.get("_error")],
    }


# ---------- live calls ----------------------------------------------------
def load_cases(case_filter=None) -> list:
    if not CASES_DIR.exists():
        sys.exit(f"no cases dir at {CASES_DIR}")
    cases = []
    for p in sorted(CASES_DIR.glob("*.json")):
        c = json.loads(p.read_text())
        for key in ("id", "description", "submission", "expected"):
            if key not in c:
                sys.exit(f"{p.name}: missing top-level key '{key}'")
        sub, exp = c["submission"], c["expected"]
        if "clinical_summary" not in sub or "requested_service" not in sub:
            sys.exit(f"{p.name}: submission needs 'requested_service' and 'clinical_summary'")
        if normalize_decision(exp.get("decision", "")) not in ("APPROVED", "DENIED"):
            sys.exit(f"{p.name}: expected.decision must be APPROVED or DENIED")
        exp.setdefault("covered_codes", [])
        exp.setdefault("must_cite_any", [])
        cases.append(c)
    if case_filter:
        cases = [c for c in cases if c["id"] == case_filter]
        if not cases:
            sys.exit(f"no case with id '{case_filter}'")
    return cases


def create_bcbs_agent(client, provider):
    """Recreate the demo's BCBS-MA policy #297 agent (step2_evaluate.py / step3_adjudicate.py). Returns (agent_id, prompt_id).
    agent.create is retried — this instance throws intermittent 500s (see the demo log)."""
    policy_text = (DEMO_ROOT / "policy_297_tms.md").read_text()
    prompt = client.agent.prompts.create(
        name="bcbs-ma-policy-297-eval",
        content=("You are a BCBS-MA utilization-management reviewer. Apply the following policy "
                 "EXACTLY as written, cite the criteria you rely on, and never invent criteria.\n\n"
                 + policy_text),
        description="BCBS-MA Medical Policy #297 (TMS) as an agent — evals harness.")
    last = None
    for i in range(1, 4):
        try:
            agent = client.agent.create(name="BCBS-MA Policy #297 Agent (evals)", prompts=[prompt.data.id],
                                        provider=provider, tags=["bcbs-ma", "policy-297", "evals"])
            return agent.data.id, prompt.data.id
        except Exception as e:
            last = e
            print(f"  [agent.create retry {i}/3] {type(e).__name__}: {str(e)[:120]}")
            time.sleep(4 * i)
    try:
        client.agent.prompts.delete(prompt.data.id)  # don't leave an orphan prompt behind
    except Exception:
        pass
    raise last


def adjudicate(client, agent_id, submission: dict) -> dict:
    """One adjudication call; returns parsed JSON (or an ERROR sentinel so one flaky call can't
    abort the whole scorecard)."""
    try:
        resp = retry(client.agent.chat.send, label="adjudicate",
            agent_id=agent_id,
            message=("Adjudicate this prior-authorization submission under policy #297. Respond ONLY "
                     "as JSON: " + ADJUDICATE_SCHEMA + "\n\nSUBMISSION:\n" + json.dumps(submission, indent=2)),
            enhanced_reasoning=True)
        return parse_json(resp.response) or {"decision": "EMPTY"}
    except Exception as e:
        return {"decision": "ERROR", "_error": f"{type(e).__name__}: {str(e)[:200]}"}


def cpt_determinism(client, k):
    """Run the demo's CPT extraction K× and report code-set stability (expected: 90867 every time)."""
    runs = []
    for _ in range(k):
        try:
            cpt = retry(client.construe.codes.extract, label="construe",
                        text=CPT_TEXT, system=ExtractRequestSystem(name="CPT", version="2025"))
            codes = tuple(sorted({as_dict(c).get("code") for c in (cpt.codes or [])}))
        except Exception as e:
            codes = (f"ERROR:{type(e).__name__}",)
        runs.append(codes)
        print(".", end="", flush=True)
    print()
    return {"runs": [list(r) for r in runs], "stable": len(set(runs)) == 1,
            "modal": list(Counter(runs).most_common(1)[0][0])}


def extraction_determinism(client, k):
    """Opt-in: re-run lang2fhir.create_multi K× and compare the extracted resource-type shape."""
    note = (DEMO_ROOT / "sample_referral_note.txt").read_text()
    runs = []
    for _ in range(k):
        try:
            multi = retry(client.lang2fhir.create_multi, label="create_multi", text=note, version="R4")
            bundle = as_dict(multi.bundle)
            types = tuple(sorted(e.get("resource", {}).get("resourceType")
                                 for e in bundle.get("entry", [])))
        except Exception as e:
            types = (f"ERROR:{type(e).__name__}",)
        runs.append(types)
        print(".", end="", flush=True)
    print()
    first = runs[0] if runs else ()
    return {"stable": len(set(runs)) == 1, "distinct_shapes": len(set(runs)),
            "n_resources": (len(first) if first and not str(first[0]).startswith("ERROR") else None),
            "type_histogram": dict(Counter(first))}


# ---------- output --------------------------------------------------------
def _m(b):
    return "✓" if b else "✗"


def print_scorecard(results, cpt, ext, k):
    if not results:
        return
    banner("SCORECARD  accuracy (vs gold)  +  determinism (stability across repeats)")
    w = max([len(r["id"]) for r in results] + [len("CASE")])
    header = f"{'CASE':<{w}}  {'EXPECT':<8}  {'DECISION (k runs)':<19}  {'CODES':<13}  {'CITED':<5}  STABLE"
    print(header)
    print("-" * len(header))
    for r in results:
        dec = f"{r['modal_decision']} {r['agree']}/{r['k']}" + ("" if r["decision_stable"] else " ⚠")
        codes = (",".join(r["rep_codes"]) or "—") + " " + _m(r["codes_correct"])
        stable = _m(r["decision_stable"] and r["codes_stable"])
        flag = "" if r["decision_correct"] else "   ✗ WRONG vs gold"
        print(f"{r['id']:<{w}}  {r['expected_decision']:<8}  {dec:<19}  {codes:<13}  "
              f"{str(r['cited'])+'/'+str(r['cite_total']):<5}  {stable}{flag}")
    print("-" * len(header))
    n = len(results)
    acc = sum(r["decision_correct"] for r in results)
    tot = sum(r["k"] for r in results)
    agree = sum(r["agree"] for r in results)
    print(f"Decision accuracy:   {acc}/{n}  ({round(100*acc/n)}%)")
    print(f"Decision stability:  {agree}/{tot} runs agree  ({round(100*agree/tot)}%)")
    if cpt:
        print(f"Structured layer (construe CPT):    {','.join(cpt['modal']) or '—'} — "
              f"stable {k if cpt['stable'] else '<'+str(k)}/{k}  ({_m(cpt['stable'])})")
    if ext:
        print(f"Structured layer (FHIR extraction): {ext['n_resources']} resources — "
              f"{'stable' if ext['stable'] else 'UNSTABLE'} across {k}  ({_m(ext['stable'])})")
    errs = [(r["id"], r["errors"]) for r in results if r["errors"]]
    if errs:
        print("\nNOTE — call errors during the run (each counted against stability):")
        for cid, elist in errs:
            print(f"  {cid}: {len(elist)} error(s); first = {elist[0]}")


def write_report(results, cpt, ext, k):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = len(results) or 1
    acc = sum(r["decision_correct"] for r in results)
    agree = sum(r["agree"] for r in results)
    tot = sum(r["k"] for r in results) or 1
    REPORT_JSON.write_text(json.dumps({
        "generated": ts, "repeats": k, "mode": "adjudicate-only", "cases": results,
        "structured_determinism": {"construe_cpt": cpt, "fhir_extraction": ext},
        "aggregate": {"num_cases": len(results), "decision_accuracy": acc,
                      "runs_total": tot, "runs_agree": agree},
    }, indent=2))

    lines = ["# TMS prior-auth — determinism & evals report", "",
             f"_Generated {ts} · {k} repeats per case · adjudicate-only_", "",
             "| Case | Expected | Decision (k runs) | Codes | Cited | Stable | Correct |",
             "|------|----------|-------------------|-------|-------|--------|---------|"]
    for r in results:
        lines.append(
            f"| `{r['id']}` | {r['expected_decision']} | {r['modal_decision']} {r['agree']}/{r['k']} | "
            f"{','.join(r['rep_codes']) or '—'} | {r['cited']}/{r['cite_total']} | "
            f"{_m(r['decision_stable'] and r['codes_stable'])} | {_m(r['decision_correct'])} |")
    lines += ["",
              f"- **Decision accuracy:** {acc}/{len(results)} ({round(100*acc/n)}%)",
              f"- **Decision stability:** {agree}/{tot} runs agree ({round(100*agree/tot)}%)"]
    if cpt:
        lines.append(f"- **Structured (construe CPT):** {','.join(cpt['modal']) or '—'} — "
                     f"{'stable' if cpt['stable'] else 'UNSTABLE'} across {k} runs")
    if ext:
        lines.append(f"- **Structured (FHIR extraction):** {ext['n_resources']} resources — "
                     f"{'stable' if ext['stable'] else 'UNSTABLE'} across {k} runs")
    lines += ["", "> Determinism is **measured, not forced**: the PhenoML SDK exposes no "
              "temperature/seed knob, so the judgment layer's stability is observed empirically across "
              "repeats. The coding/extraction layers are schema-constrained and deterministic by "
              "construction. Demonstration only — not medical, billing, or legal advice."]
    REPORT_MD.write_text("\n".join(lines) + "\n")


# ---------- main ----------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Determinism + evals scorecard for the TMS prior-auth demo.")
    ap.add_argument("--validate", action="store_true", help="load + check cases, no API calls")
    ap.add_argument("--case", help="run only the case with this id")
    ap.add_argument("--repeats", type=int, default=None, help="repeats per case (overrides EVAL_REPEATS)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any case decision != gold")
    args = ap.parse_args()

    cases = load_cases(args.case)
    k = args.repeats if args.repeats is not None else int(os.environ.get("EVAL_REPEATS", "5"))
    if k < 1:
        sys.exit(f"--repeats must be a positive integer (got {k})")

    if args.validate:
        banner(f"VALIDATE  {len(cases)} case(s) — no API calls")
        for c in cases:
            exp = c["expected"]
            print(f"  • {c['id']:<28} expect={normalize_decision(exp['decision']):<8} "
                  f"codes={exp.get('covered_codes') or '—'}  cite={exp.get('must_cite_any')}")
            print(f"      {c['description']}")
        print("\nAll cases valid. Re-run without --validate to score against the live policy agent.")
        return

    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)

    banner(f"EVALS  {len(cases)} case(s) × {k} repeats  (adjudicate-only)")
    agent_id, prompt_id = create_bcbs_agent(client, provider)
    print(f"BCBS-MA policy #297 agent: {agent_id}")

    results, cpt, ext = [], None, None
    try:
        for c in cases:
            submission = {"patient": f"Patient/eval-{c['id']}", **c["submission"]}
            print(f"\n[{c['id']}] adjudicating {k}×: ", end="", flush=True)
            runs = []
            for _ in range(k):
                r = adjudicate(client, agent_id, submission)
                runs.append(r)
                print(normalize_decision(r.get("decision", ""))[0], end="", flush=True)  # A / D / E
            print()
            results.append(score_case(c, runs))

        banner(f"DETERMINISM  structured coding layer (construe CPT × {k})")
        print("  extracting: ", end="", flush=True)
        cpt = cpt_determinism(client, k)
        print(f"  CPT codes: {','.join(cpt['modal']) or '—'}  — "
              f"{'stable' if cpt['stable'] else 'UNSTABLE'} across {k} ({_m(cpt['stable'])})")

        if os.environ.get("EVAL_CHECK_EXTRACTION"):
            banner(f"DETERMINISM  structured extraction layer (lang2fhir.create_multi × {k})")
            print("  re-extracting (slow): ", end="", flush=True)
            ext = extraction_determinism(client, k)
            print(f"  resources: n={ext['n_resources']}  types={ext['type_histogram']}  "
                  f"({_m(ext['stable'])})")
    finally:
        banner("CLEANUP  delete eval agent + prompt")
        for fn, arg, lbl in ((client.agent.delete, agent_id, "agent"),
                             (client.agent.prompts.delete, prompt_id, "prompt")):
            try:
                fn(arg)
                print(f"deleted {lbl} {arg}")
            except Exception as e:
                print(f"skip {lbl} {arg}: {type(e).__name__}")

    print_scorecard(results, cpt, ext, k)
    write_report(results, cpt, ext, k)
    print(f"\nwrote {REPORT_MD.relative_to(DEMO_ROOT)} and {REPORT_JSON.relative_to(DEMO_ROOT)}")

    if args.strict and any(not r["decision_correct"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Determinism + evals scorecard for the MOPA breast-cancer prior-auth demo.

Each case under ./cases pins a frozen patient chart + ordered regimen and exercises the oncology-crd
service's judgment (cds_hooks_server/evaluate.py) K times. The service has THREE outcomes, so we
grade three gold labels:

  APPROVED    - all data present, NCCN Category 1 -> medically accepted (Response A + Coverage)
  DENIED      - all data present, not a medically accepted use (HER2-negative TH)
  NEEDS_INFO  - a required element (HER2) is missing -> DTR card (Response B)

We report the two things a payer always asks about an automated prior-auth:

  ACCURACY    - does the outcome match the labeled gold outcome? (+ cited UM-9 criteria)
  DETERMINISM - is the outcome STABLE across repeats? The PhenoML SDK exposes no temperature/seed
                knob, so we MEASURE the medical-acceptance judgment's stability. The readiness gate
                (the HER2 gap-check) is deterministic by construction: NEEDS_INFO never calls the
                agent. The coding layer (construe RxNorm extraction) is schema-constrained and
                deterministic too, we show that as well.

Run from the mopa-breast-pa dir, using its v15 venv (the global Python may have a stale SDK):
  .venv/bin/python evals/run_evals.py                       # K = EVAL_REPEATS (default 5)
  .venv/bin/python evals/run_evals.py --validate            # load + check cases, NO API calls
  .venv/bin/python evals/run_evals.py --case dtr-her2-missing --repeats 3
"""
import argparse, json, os, re, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Reuse the demo's shared helpers + the actual judgment code (so the eval grades exactly what the
# demo runs). common.py / evaluate.py / step2_cdshooks define only functions, so importing is safe.
DEMO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_ROOT))
from common import load_env, make_client, as_dict, retry, banner, resolve_provider  # noqa: E402
from cds_hooks_server import evaluate as cds  # noqa: E402
from step2_cdshooks import classify  # noqa: E402
from phenoml.construe import ExtractRequestSystem  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent
CASES_DIR = EVALS_DIR / "cases"
REPORT_MD = EVALS_DIR / "report.md"
REPORT_JSON = EVALS_DIR / "report.json"

# The drug text + system used by the demo's construe step (step1_intake.py, Step 1.3).
RXNORM_TEXT = "Paclitaxel intravenous; trastuzumab intravenous."

# classify() returns the demo's card outcome; map it onto the eval's gold labels.
OUTCOME_TO_LABEL = {"pre-approved": "APPROVED", "needs-more-info": "NEEDS_INFO", "deny": "DENIED"}


# ---------- scoring helpers ----------------------------------------------
def normalize_decision(s: str) -> str:
    """Collapse a decision word onto {APPROVED, DENIED, NEEDS_INFO} (+ EMPTY/ERROR sentinels).
    UM-9 calls a non-meeting request 'not medically accepted'; a missing data element pends the
    request for more info (DTR)."""
    t = (s or "").strip().upper()
    if not t or t == "EMPTY":
        return "EMPTY"
    if t == "ERROR":
        return "ERROR"
    # Needs-more-info wins first so a DTR outcome is never miscounted as an approval/denial.
    if "NEEDS" in t or "MORE INFO" in t or "ADDITIONAL INFO" in t or "DTR" in t or "PENDED" in t:
        return "NEEDS_INFO"
    if "DENI" in t or "DENY" in t or "NOT MEDICALLY ACCEPTED" in t or "NOT APPROV" in t:
        return "DENIED"
    if "APPROV" in t or "MEDICALLY ACCEPTED" in t:
        return "APPROVED"
    return "DENIED"


def cite_hits(must_cite_any, runs):
    """How many expected keywords appear in the returned card detail(s) across the runs."""
    hay = " ".join(r.get("detail", "") for r in runs).lower().replace("criterion", "condition")
    def cited(kw: str) -> bool:
        kw = kw.lower()
        tail = r"(?!\d)" if kw[-1:].isdigit() else ""
        return re.search(re.escape(kw) + tail, hay) is not None
    hits = [kw for kw in must_cite_any if cited(kw)]
    return len(hits), len(must_cite_any)


def score_case(case, runs):
    exp = case["expected"]
    want = normalize_decision(exp["decision"])
    decisions = [normalize_decision(r.get("decision", "")) for r in runs]
    modal, agree = Counter(decisions).most_common(1)[0]
    cited, cite_total = cite_hits(exp.get("must_cite_any", []), runs)
    return {
        "id": case["id"],
        "expected_decision": want,
        "modal_decision": modal,
        "agree": agree,
        "k": len(runs),
        "decision_correct": modal == want,
        "decision_stable": agree == len(runs),
        "cited": cited,
        "cite_total": cite_total,
        "decisions": decisions,
        "errors": [r["_error"] for r in runs if r.get("_error")],
    }


# ---------- building requests from cases ----------------------------------
def _obs(code, display, value):
    return {"resourceType": "Observation", "status": "final",
            "code": {"text": display, "coding": [{"system": "http://loinc.org", "code": code,
                                                  "display": display}]},
            "valueCodeableConcept": {"text": value}}


def build_request(case, library) -> dict:
    """Expand a compact case submission into a CDS Hooks request the service can judge. `her2` is the
    load-bearing variable (positive / negative / missing); everything else is the standard chart."""
    sub = case["submission"]
    include = set(sub.get("include", ["condition", "stage", "er", "pr", "ecog", "regimen"]))
    pid = "eval-" + case["id"]
    res = [{"resourceType": "Patient", "id": pid}]
    if "condition" in include:
        res.append({"resourceType": "Condition",
                    "code": {"text": "Invasive ductal carcinoma of breast",
                             "coding": [{"system": "http://snomed.info/sct", "code": "254837009",
                                         "display": "Malignant neoplasm of breast"}]}})
    if "stage" in include:
        res.append(_obs("21908-9", "Stage group.clinical Cancer", "Stage IIB"))
    if "er" in include:
        res.append(_obs("85337-4", "Estrogen receptor [Presence] by Immune stain", "Negative 0%"))
    if "pr" in include:
        res.append(_obs("85339-0", "Progesterone receptor [Presence] by Immune stain", "Negative 0%"))
    if "ecog" in include:
        res.append(_obs("89247-1", "ECOG performance status", "0"))
    her2 = sub.get("her2", "missing")
    if her2 == "positive":
        res.append(_obs("85319-2", "HER2 [Presence] by Immune stain", "Positive (HER2 amplified)"))
    elif her2 == "negative":
        res.append(_obs("85319-2", "HER2 [Presence] by Immune stain", "Negative (HER2 not amplified)"))
    draft = []
    if "regimen" in include:
        draft.append({"resource": {"resourceType": "RequestGroup", "status": "active",
                                   "intent": "order", "code": {"text": "TH (paclitaxel + trastuzumab)"},
                                   "action": [{"resource": {"reference": "urn:pac"}},
                                              {"resource": {"reference": "urn:tra"}}]}})
    return {"hook": "order-sign", "hookInstance": "eval",
            "context": {"patientId": pid,
                        "draftOrders": {"resourceType": "Bundle", "type": "collection", "entry": draft}},
            "prefetch": {"library": library,
                         "patientData": {"resourceType": "Bundle", "type": "collection",
                                         "entry": [{"resource": r} for r in res]}}}


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
        if "requested_service" not in c["submission"]:
            sys.exit(f"{p.name}: submission needs 'requested_service'")
        if normalize_decision(c["expected"].get("decision", "")) not in ("APPROVED", "DENIED", "NEEDS_INFO"):
            sys.exit(f"{p.name}: expected.decision must be APPROVED, DENIED, or NEEDS_INFO")
        c["expected"].setdefault("must_cite_any", [])
        cases.append(c)
    if case_filter:
        cases = [c for c in cases if c["id"] == case_filter]
        if not cases:
            sys.exit(f"no case with id '{case_filter}'")
    return cases


def create_um9_agent(client, provider):
    """Create the demo's OncoHealth UM-9 agent (cds_hooks_server/evaluate.build_agent_once) with a
    few retries, returning (agent_id, prompt_id) for cleanup. agent.create can throw transient 500s."""
    last = None
    for i in range(1, 4):
        try:
            created = {"agents": [], "prompts": []}
            agent_id = cds.build_agent_once(client, provider, created)
            return agent_id, created["prompts"][0]
        except Exception as e:
            last = e
            print(f"  [agent.create retry {i}/3] {type(e).__name__}: {str(e)[:120]}")
            time.sleep(4 * i)
    raise last


def evaluate_case(client, agent_id, request, library) -> dict:
    """One judgment of a case; returns {decision, detail} (or an ERROR sentinel so one flaky call
    can't abort the whole scorecard). NEEDS_INFO short-circuits before the agent (deterministic)."""
    try:
        resp = cds.evaluate(client, agent_id, request, library)
        label = OUTCOME_TO_LABEL.get(classify(resp), "EMPTY")
        # Search both summary and detail so citations in either are graded (the DTR summary carries
        # "additional information", the approve/deny detail carries the cited UM-9 criteria).
        detail = " ".join(((c or {}).get("summary", "") + " " + (c or {}).get("detail", ""))
                          for c in (resp.get("cards") or []))
        return {"decision": label, "detail": detail}
    except Exception as e:
        return {"decision": "ERROR", "detail": "", "_error": f"{type(e).__name__}: {str(e)[:200]}"}


def rxnorm_determinism(client, k):
    """Run the demo's RxNorm extraction K× and report code-set stability (paclitaxel + trastuzumab)."""
    runs = []
    for _ in range(k):
        try:
            res = retry(client.construe.codes.extract, label="construe",
                        text=RXNORM_TEXT, system=ExtractRequestSystem(name="RXNORM"))
            codes = tuple(sorted({as_dict(c).get("code") for c in (res.codes or [])}))
        except Exception as e:
            codes = (f"ERROR:{type(e).__name__}",)
        runs.append(codes)
        print(".", end="", flush=True)
    print()
    return {"runs": [list(r) for r in runs], "stable": len(set(runs)) == 1,
            "modal": list(Counter(runs).most_common(1)[0][0])}


# ---------- output --------------------------------------------------------
def _m(b):
    return "✓" if b else "✗"


def print_scorecard(results, rx, k):
    if not results:
        return
    banner("SCORECARD  accuracy (vs gold)  +  determinism (stability across repeats)")
    w = max([len(r["id"]) for r in results] + [len("CASE")])
    header = f"{'CASE':<{w}}  {'EXPECT':<10}  {'DECISION (k runs)':<22}  {'CITED':<5}  STABLE"
    print(header)
    print("-" * len(header))
    for r in results:
        dec = f"{r['modal_decision']} {r['agree']}/{r['k']}" + ("" if r["decision_stable"] else " ⚠")
        flag = "" if r["decision_correct"] else "   ✗ WRONG vs gold"
        print(f"{r['id']:<{w}}  {r['expected_decision']:<10}  {dec:<22}  "
              f"{str(r['cited'])+'/'+str(r['cite_total']):<5}  {_m(r['decision_stable'])}{flag}")
    print("-" * len(header))
    n = len(results)
    acc = sum(r["decision_correct"] for r in results)
    tot = sum(r["k"] for r in results)
    agree = sum(r["agree"] for r in results)
    print(f"Decision accuracy:   {acc}/{n}  ({round(100*acc/n)}%)")
    print(f"Decision stability:  {agree}/{tot} runs agree  ({round(100*agree/tot)}%)")
    if rx:
        print(f"Structured layer (construe RxNorm): {','.join(rx['modal']) or '-'} - "
              f"stable {k if rx['stable'] else '<'+str(k)}/{k}  ({_m(rx['stable'])})")
    errs = [(r["id"], r["errors"]) for r in results if r["errors"]]
    if errs:
        print("\nNOTE - call errors during the run (each counted against stability):")
        for cid, elist in errs:
            print(f"  {cid}: {len(elist)} error(s); first = {elist[0]}")


def write_report(results, rx, k):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = len(results) or 1
    acc = sum(r["decision_correct"] for r in results)
    agree = sum(r["agree"] for r in results)
    tot = sum(r["k"] for r in results) or 1
    REPORT_JSON.write_text(json.dumps({
        "generated": ts, "repeats": k, "service": "oncology-crd", "cases": results,
        "structured_determinism": {"construe_rxnorm": rx},
        "aggregate": {"num_cases": len(results), "decision_accuracy": acc,
                      "runs_total": tot, "runs_agree": agree},
    }, indent=2))

    lines = ["# MOPA breast-cancer prior-auth - determinism & evals report", "",
             f"_Generated {ts} - {k} repeats per case - oncology-crd_", "",
             "| Case | Expected | Decision (k runs) | Cited | Stable | Correct |",
             "|------|----------|-------------------|-------|--------|---------|"]
    for r in results:
        lines.append(
            f"| `{r['id']}` | {r['expected_decision']} | {r['modal_decision']} {r['agree']}/{r['k']} | "
            f"{r['cited']}/{r['cite_total']} | {_m(r['decision_stable'])} | {_m(r['decision_correct'])} |")
    lines += ["",
              f"- **Decision accuracy:** {acc}/{len(results)} ({round(100*acc/n)}%)",
              f"- **Decision stability:** {agree}/{tot} runs agree ({round(100*agree/tot)}%)"]
    if rx:
        lines.append(f"- **Structured (construe RxNorm):** {','.join(rx['modal']) or '-'} - "
                     f"{'stable' if rx['stable'] else 'UNSTABLE'} across {k} runs")
    lines += ["", "> Determinism is **measured, not forced**: the PhenoML SDK exposes no "
              "temperature/seed knob, so the judgment layer's stability is observed across repeats. "
              "The readiness gate (HER2 gap-check) and the coding layer are deterministic by "
              "construction. Demonstration only - not medical, billing, or legal advice."]
    REPORT_MD.write_text("\n".join(lines) + "\n")


# ---------- main ----------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Determinism + evals scorecard for the MOPA oncology demo.")
    ap.add_argument("--validate", action="store_true", help="load + check cases, no API calls")
    ap.add_argument("--case", help="run only the case with this id")
    ap.add_argument("--repeats", type=int, default=None, help="repeats per case (overrides EVAL_REPEATS)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any case outcome != gold")
    args = ap.parse_args()

    cases = load_cases(args.case)
    k = args.repeats if args.repeats is not None else int(os.environ.get("EVAL_REPEATS", "5"))
    if k < 1:
        sys.exit(f"--repeats must be a positive integer (got {k})")

    if args.validate:
        banner(f"VALIDATE  {len(cases)} case(s) - no API calls")
        for c in cases:
            exp = c["expected"]
            print(f"  - {c['id']:<22} expect={normalize_decision(exp['decision']):<10} "
                  f"her2={c['submission'].get('her2', 'missing'):<8} cite={exp.get('must_cite_any')}")
            print(f"      {c['description']}")
        print("\nAll cases valid. Re-run without --validate to score against the live UM-9 agent.")
        return

    library = cds.load_library()
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)

    banner(f"EVALS  {len(cases)} case(s) x {k} repeats  (oncology-crd)")
    agent_id, prompt_id = create_um9_agent(client, provider)
    print(f"OncoHealth UM-9 agent: {agent_id}")

    results, rx = [], None
    try:
        for c in cases:
            request = build_request(c, library)
            print(f"\n[{c['id']}] judging {k}x: ", end="", flush=True)
            runs = []
            for _ in range(k):
                r = evaluate_case(client, agent_id, request, library)
                runs.append(r)
                print(normalize_decision(r.get("decision", ""))[0], end="", flush=True)  # A / D / N / E
            print()
            results.append(score_case(c, runs))

        banner(f"DETERMINISM  structured coding layer (construe RxNorm x {k})")
        print("  extracting: ", end="", flush=True)
        rx = rxnorm_determinism(client, k)
        print(f"  RxNorm codes: {','.join(rx['modal']) or '-'}  - "
              f"{'stable' if rx['stable'] else 'UNSTABLE'} across {k} ({_m(rx['stable'])})")
    finally:
        banner("CLEANUP  delete eval agent + prompt")
        for fn, arg, lbl in ((client.agent.delete, agent_id, "agent"),
                             (client.agent.prompts.delete, prompt_id, "prompt")):
            try:
                fn(arg)
                print(f"deleted {lbl} {arg}")
            except Exception as e:
                print(f"skip {lbl} {arg}: {type(e).__name__}")

    print_scorecard(results, rx, k)
    write_report(results, rx, k)
    print(f"\nwrote {REPORT_MD.relative_to(DEMO_ROOT)} and {REPORT_JSON.relative_to(DEMO_ROOT)}")

    if args.strict and any(not r["decision_correct"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()

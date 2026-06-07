#!/usr/bin/env python3
"""End-to-end runner for the TMS prior-auth demo (PhenoML SDK v15).

Reads credentials from tms-prior-auth/.env (preferred) or the repo-root ../.env.
Auth: PHENOML_CLIENT_ID + PHENOML_CLIENT_SECRET (OAuth client credentials, v15-native).

Run:  .venv/bin/python run_demo.py
"""
import json, os, re, sys, time
from pathlib import Path

import httpx
from dotenv import dotenv_values
from phenoml import PhenomlClient


# ---------- config / auth -------------------------------------------------
def load_env() -> dict:
    env = dict(os.environ)                       # real env vars are the base layer
    for p in (Path("../.env"), Path(".env")):   # .env files override env vars
        if p.exists():
            env.update({k: (v or "").strip().strip('"').strip("'")
                        for k, v in dotenv_values(p).items()})
    return env


def make_client(env: dict) -> PhenomlClient:
    base_url = env.get("PHENOML_BASE_URL") or None
    cid, csec = env.get("PHENOML_CLIENT_ID"), env.get("PHENOML_CLIENT_SECRET")
    # max_retries=0 turns OFF the SDK's *silent* auto-retry; the explicit retry() wrapper below is
    # the single, visible retry layer (so a flaky call never silently double-fires document/multi).
    kw = {"timeout": float(env.get("PHENOML_TIMEOUT", "300")), "max_retries": 0}
    if base_url:
        kw["base_url"] = base_url
    if cid and csec:
        print(f"[auth] OAuth client credentials (base_url={base_url})")
        return PhenomlClient(client_id=cid, client_secret=csec, **kw)
    sys.exit("No credentials found. Set PHENOML_CLIENT_ID and PHENOML_CLIENT_SECRET in .env (see .env.example)")


# ---------- helpers -------------------------------------------------------
def as_dict(obj):
    # by_alias=True is REQUIRED: SDK models use snake_case attrs (resource_type, full_url)
    # but FHIR/the API expect camelCase (resourceType, fullUrl). Without it, summary.create
    # (IPS) rejects the bundle with "resourceType field is missing".
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, list):
        return [as_dict(x) for x in obj]
    return obj


def parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}|\[.*\]", text or "", re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def clip(s: str, n: int = 6000) -> str:
    return s if len(s) <= n else s[:n] + "\n...[truncated]"


def banner(title: str):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78, flush=True)


def retry(fn, *args, attempts=3, base=4, label="", **kwargs):
    """Retry transient transport errors (server disconnects, read timeouts) with backoff."""
    for i in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except httpx.TransportError as e:
            if i == attempts:
                raise
            wait = base * i
            print(f"  [retry {i}/{attempts}] {label}: {type(e).__name__}; waiting {wait}s", flush=True)
            time.sleep(wait)


# ---------- pipeline ------------------------------------------------------
def main():
    env = load_env()
    client = make_client(env)
    provider = env.get("PHENOML_FHIR_PROVIDER_ID") or env.get("FHIR_PROVIDER_ID") or ""
    print(f"[fhir provider] {provider or '(none — agent/FHIR steps may use sandbox default)'}")

    created = {"agents": [], "prompts": []}

    # --- Step 1.1: document/multi (text fallback; no PDF asset here) -----
    banner("STEP 1.1  Referral note -> FHIR bundle (lang2fhir.create_multi)")
    note = Path("sample_referral_note.txt").read_text()
    cache = Path(".cache_bundle.json")
    if cache.exists():
        print("(using cached bundle from .cache_bundle.json — delete it to re-extract)")
        cached = json.loads(cache.read_text())
        bundle, extracted = cached["bundle"], cached["resources"]
    else:
        multi = retry(client.lang2fhir.create_multi, label="create_multi", text=note, version="R4")
        bundle, extracted = as_dict(multi.bundle), as_dict(multi.resources)
        cache.write_text(json.dumps({"bundle": bundle, "resources": extracted}))
    print(f"extracted {len(bundle.get('entry', []))} resources:")
    for r in extracted or []:
        print(f"  - {r.get('resourceType')}: {r.get('description')}")

    # The failed/discontinued medication trials are 'stopped'/'completed', so they do NOT appear in
    # the IPS current-medication section. They ARE the key evidence for policy criterion #2, so we
    # pull the trial history out of the extracted resources to feed the prior-auth/adjudication agent.
    med_history_text = "\n".join(
        f"- {r.get('description')}" for r in (extracted or []) if r.get("resourceType") == "MedicationRequest"
    ) or "(no medication trials documented)"

    # --- Step 1.2: IPS ---------------------------------------------------
    banner("STEP 1.2  International Patient Summary (summary.create mode=ips)")
    patients = [e["resource"] for e in bundle.get("entry", [])
                if e.get("resource", {}).get("resourceType") == "Patient"]
    print(f"patients in bundle: {len(patients)}")
    ips = retry(client.summary.create, label="summary.create", fhir_resources=bundle, mode="ips")
    ips_text = ips.summary or ""
    print(ips_text[:1500])

    # --- Step 1.3: referral agent review --------------------------------
    banner("STEP 1.3  Referral agent reviews IPS, asks follow-ups")
    REFERRAL_PROMPT = (
        "You are a referral intake specialist preparing a prior-authorization packet for rTMS "
        "for depression under BCBS-MA Medical Policy #297. Given the patient summary, decide "
        "whether the record documents EACH item and list what is MISSING or AMBIGUOUS: "
        "1) severe MDD documented by a standardized rating scale; "
        "2) at least one of: 2 failed med trials / intolerance across 2 trials / prior rTMS "
        "response >=3 months ago / ECT candidacy where ECT is not superior; "
        "3) failed adequate psychotherapy trial documented by a rating scale; "
        "4) contraindication screen (seizure history, psychosis, neuro conditions, implanted "
        "magnetic device within 30cm). "
        'Return ONLY JSON: {"present":[...],"missing":[...],"follow_up_questions":[...]}'
    )
    rp = client.agent.prompts.create(name="tms-referral-intake", content=REFERRAL_PROMPT,
                                     description="TMS PA completeness reviewer (policy #297).")
    created["prompts"].append(rp.data.id)
    referral_agent = client.agent.create(name="TMS Referral Intake Agent", prompts=[rp.data.id],
                                          provider=provider, tags=["tms", "prior-auth"])
    created["agents"].append(referral_agent.data.id)
    # The referral agent reviews the IPS (the clean patient summary) — data goes in the MESSAGE,
    # because the agent does not surface the `context=` field to the model.
    review = retry(client.agent.chat.send, label="referral.chat",
        agent_id=referral_agent.data.id,
        message=("Review the following International Patient Summary against the policy #297 rTMS "
                 "criteria and return the JSON.\n\n" + ips_text),
    )
    print(review.response)
    follow_up_questions = parse_json(review.response).get("follow_up_questions", [])
    print("\nfollow_up_questions parsed:", follow_up_questions)

    # --- Step 1.4: write follow-up answers back to the EHR --------------
    banner("STEP 1.4  Persist Patient + follow-up Observations to the EHR")
    patient_id = None
    try:
        created_patient = as_dict(client.fhir.create(
            fhir_provider_id=provider, fhir_path="Patient", request=patients[0]))
        patient_id = created_patient.get("id")
        print("Patient on EHR:", patient_id)
    except Exception as e:
        print("Patient POST failed (instance may be read-only):", type(e).__name__, str(e)[:200])

    follow_up_answers = [
        "Completed 16 sessions of cognitive behavioral therapy over 12 weeks with no significant "
        "improvement; PHQ-9 remained 20 or higher throughout.",
        "No personal or family history of seizures and no implanted magnetic-sensitive devices; "
        "no psychotic features in the current episode.",
    ]
    for answer in follow_up_answers:
        try:
            resource = as_dict(client.lang2fhir.create(version="R4", resource="auto", text=answer))
            if patient_id:
                resource.setdefault("subject", {"reference": f"Patient/{patient_id}"})
            saved = as_dict(client.fhir.create(
                fhir_provider_id=provider, fhir_path=resource["resourceType"], request=resource))
            print(f"  wrote {saved.get('resourceType')}/{saved.get('id')}")
        except Exception as e:
            print("  write failed:", type(e).__name__, str(e)[:200])

    # --- Step 1.5: BCBS-MA policy agent ---------------------------------
    banner("STEP 1.5  Create BCBS-MA policy #297 agent")
    policy_text = Path("policy_297_tms.md").read_text()
    bcbs_prompt = client.agent.prompts.create(
        name="bcbs-ma-policy-297",
        content=("You are a BCBS-MA utilization-management reviewer. Apply the following policy "
                 "EXACTLY as written, cite the criteria you rely on, and never invent criteria.\n\n"
                 + policy_text),
        description="BCBS-MA Medical Policy #297 (TMS) as an agent.")
    created["prompts"].append(bcbs_prompt.data.id)
    bcbs_agent = client.agent.create(name="BCBS-MA Policy #297 Agent", prompts=[bcbs_prompt.data.id],
                                     provider=provider, tags=["bcbs-ma", "policy-297"])
    created["agents"].append(bcbs_agent.data.id)
    print("BCBS agent:", bcbs_agent.data.id)

    # --- Step 2.1: prior-auth evaluation --------------------------------
    banner("STEP 2.1  Prior-auth evaluation by the BCBS agent")
    # The prior-auth agent needs the IPS *plus* the medication trial history (criterion #2 evidence)
    # plus the follow-up answers — all in the MESSAGE.
    pa_evidence = (
        "=== INTERNATIONAL PATIENT SUMMARY ===\n" + ips_text
        + "\n\n=== MEDICATION TRIAL HISTORY (from chart) ===\n" + med_history_text
        + "\n\n=== ADDITIONAL FOLLOW-UP INFORMATION ON FILE ===\n"
        + "\n".join(f"- {a}" for a in follow_up_answers)
    )
    pa = retry(client.agent.chat.send, label="pa.eval",
        agent_id=bcbs_agent.data.id,
        message=('A provider requests prior auth for rTMS (CPT 90867/90868/90869). Evaluate the '
                 'patient below against policy #297 and return ONLY JSON: {"meets_criteria":true|false,'
                 '"satisfied":[...],"unmet":[...],"additional_info_needed":[...],"rationale":"..."}\n\n'
                 + pa_evidence),
        enhanced_reasoning=True,
    )
    print(json.dumps(parse_json(pa.response), indent=2)[:2000])

    # --- Step 2.2: workflow alternative ---------------------------------
    banner("STEP 2.2  Workflow alternative (create + execute)")
    try:
        if env.get("SKIP_WORKFLOW"):
            raise RuntimeError("skipped via SKIP_WORKFLOW env")
        wf = client.workflows.create(
            name="TMS PA - gather supporting evidence",
            workflow_instructions=(
                "Given a patient reference, gather the evidence needed to evaluate an rTMS prior "
                "authorization under BCBS-MA policy #297: severe MDD Condition, depression rating-"
                "scale Observations (PHQ-9/MADRS), antidepressant MedicationRequest history, and any "
                "psychotherapy Observations. Flag which policy criteria are not supported."),
            sample_data={"patient_id": patient_id or "example-patient-id"},
            fhir_provider_id=provider,
        )
        print("workflow:", wf.workflow_id)
        if patient_id:
            run = client.workflows.execute(wf.workflow_id, input_data={"patient_id": patient_id})
            print(as_dict(run))
    except Exception as e:
        print("workflow step skipped/failed:", type(e).__name__, str(e)[:300])

    # --- Step 3: assemble + adjudicate ----------------------------------
    banner("STEP 3.1  Extract CPT codes (construe.codes.extract)")
    from phenoml.construe import ExtractRequestSystem
    cpt = client.construe.codes.extract(
        text=("Therapeutic repetitive transcranial magnetic stimulation (TMS) treatment; initial, "
              "including cortical mapping, motor threshold determination, delivery and management; "
              "plus subsequent delivery and management sessions."),
        system=ExtractRequestSystem(name="CPT", version="2025"))
    cpt_codes = [as_dict(c) for c in (cpt.codes or [])]
    for c in cpt_codes:
        print(" ", c.get("code"), "-", c.get("description"))

    submission = {
        "patient": f"Patient/{patient_id}" if patient_id else "Patient/example",
        "requested_service": "rTMS for treatment-resistant major depressive disorder",
        "cpt_codes": [c.get("code") for c in cpt_codes][:3],
        "clinical_summary": clip(ips_text),
        "medication_trial_history": clip(med_history_text),
        "supporting_evidence": follow_up_answers,
    }

    banner("STEP 3.2  Adjudicate (approve path, then a denied case)")
    decision = retry(client.agent.chat.send, label="adjudicate.approve",
        agent_id=bcbs_agent.data.id,
        message=('Adjudicate this prior-authorization submission under policy #297. Respond ONLY as '
                 'JSON: {"decision":"APPROVED"|"DENIED","covered_codes":[...],"rationale":"...",'
                 '"policy_citations":[...],"conditions_or_limits":"..."}\n\nSUBMISSION:\n'
                 + json.dumps(submission, indent=2)),
        enhanced_reasoning=True)
    print("APPROVE-PATH:\n", decision.response)

    denied_case = {"patient": "Patient/example-2", "requested_service": "rTMS for depression",
                   "clinical_summary": ("Mild major depressive disorder. One antidepressant trial "
                       "(sertraline) for 4 weeks. No psychotherapy trial. No standardized rating scale.")}
    denied = retry(client.agent.chat.send, label="adjudicate.deny",
        agent_id=bcbs_agent.data.id,
        message=('Adjudicate the following prior-authorization submission under policy #297. Respond '
                 'ONLY as JSON: {"decision":"APPROVED"|"DENIED","covered_codes":[...],"rationale":"...",'
                 '"policy_citations":[...],"conditions_or_limits":"..."}\n\nSUBMISSION:\n'
                 + json.dumps(denied_case, indent=2)),
        enhanced_reasoning=True)
    print("\nDENY-PATH:\n", denied.response)

    # --- cleanup ---------------------------------------------------------
    banner("CLEANUP  delete created agents/prompts")
    for aid in created["agents"]:
        try: client.agent.delete(aid); print("deleted agent", aid)
        except Exception as e: print("skip agent", aid, type(e).__name__)
    for pid in created["prompts"]:
        try: client.agent.prompts.delete(pid); print("deleted prompt", pid)
        except Exception as e: print("skip prompt", pid, type(e).__name__)

    print("\nDONE.")


if __name__ == "__main__":
    main()

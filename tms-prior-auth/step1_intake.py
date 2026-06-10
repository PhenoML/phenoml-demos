#!/usr/bin/env python3
"""Step 1 · Intake & evidence  (TMS prior-auth demo, PhenoML SDK v15).

Referral note -> FHIR transaction bundle -> International Patient Summary -> a referral agent
reviews the summary and asks follow-ups -> write the whole chart + follow-up answers back to the
EHR in one transaction. Hands the bundle, IPS, evidence, and patient id to step 2 via .state/.

Run:  .venv/bin/python step1_intake.py        (then step2_evaluate.py, then step3_adjudicate.py)
"""
import copy, json, sys, uuid

from common import (HERE, load_env, make_client, resolve_provider, as_dict, parse_json,
                    banner, retry, cleanup, load_state, save_state)


def run(client, env, provider, state, created):
    # --- Step 1.1: document/multi (text fallback; no PDF asset here) -----
    banner("STEP 1.1  Referral note -> FHIR bundle (lang2fhir.create_multi)")
    note = (HERE / "sample_referral_note.txt").read_text()
    if state.get("bundle") and state.get("resources") is not None:
        print("(reusing cached bundle from .state/ — delete .state/ to re-extract)")
        bundle, extracted = state["bundle"], state["resources"]
    else:
        multi = retry(client.lang2fhir.create_multi, label="create_multi", text=note, version="R4")
        bundle, extracted = as_dict(multi.bundle), as_dict(multi.resources)
        state["bundle"], state["resources"] = bundle, extracted
    print(f"extracted {len(bundle.get('entry', []))} resources:")
    for r in extracted or []:
        print(f"  - {r.get('resourceType')}: {r.get('description')}")

    # The failed/discontinued medication trials are 'stopped'/'completed', so they do NOT appear in
    # the IPS current-medication section. They ARE the key evidence for policy criterion #2, so we
    # pull the trial history out of the extracted resources to feed the prior-auth/adjudication agent.
    med_history_text = "\n".join(
        f"- {r.get('description')}" for r in (extracted or []) if r.get("resourceType") == "MedicationRequest"
    ) or "(no medication trials documented)"
    state["med_history_text"] = med_history_text

    # --- Step 1.2: IPS ---------------------------------------------------
    banner("STEP 1.2  International Patient Summary (summary.create mode=ips)")
    patients = [e["resource"] for e in bundle.get("entry", [])
                if e.get("resource", {}).get("resourceType") == "Patient"]
    print(f"patients in bundle: {len(patients)}")
    if len(patients) != 1:
        sys.exit(f"expected exactly 1 Patient in the bundle, found {len(patients)}; the IPS + "
                 "EHR steps assume a single patient. Delete .state/ to re-extract.")
    ips = retry(client.summary.create, label="summary.create", fhir_resources=bundle, mode="ips")
    ips_text = ips.summary or ""
    state["ips_text"] = ips_text
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
    state["follow_up_questions"] = follow_up_questions
    print("\nfollow_up_questions parsed:", follow_up_questions)

    # --- Step 1.4: persist the full chart to the EHR in ONE transaction --
    banner("STEP 1.4  Persist the full FHIR bundle + follow-up answers (fhir.execute_bundle)")
    # The extracted bundle is already a FHIR `transaction` Bundle: every entry has a unique
    # urn:uuid fullUrl and internal refs use those fullUrls, so a single execute_bundle persists
    # Patient + Condition + Observations + MedicationRequests + ... interlinked — the server
    # assigns real ids and rewrites the references. (create_multi only EXTRACTS the bundle;
    # execute_bundle is what writes it.)
    patient_full_url = next(e["fullUrl"] for e in bundle["entry"]
                            if e["resource"]["resourceType"] == "Patient")

    # Follow-up answers are new evidence gathered after the referral review. Extract each and fold
    # it into the SAME transaction, linked to the patient's bundle-local fullUrl, so the whole
    # chart lands in one atomic write. We persist a COPY so the cached state["bundle"] stays the
    # clean extracted chart (re-running step 1 must not append the follow-ups twice).
    follow_up_answers = [
        "Completed 16 sessions of cognitive behavioral therapy over 12 weeks with no significant "
        "improvement; PHQ-9 remained 20 or higher throughout.",
        "No personal or family history of seizures and no implanted magnetic-sensitive devices; "
        "no psychotic features in the current episode.",
    ]
    state["follow_up_answers"] = follow_up_answers
    tx_bundle = copy.deepcopy(bundle)
    for answer in follow_up_answers:
        resource = as_dict(client.lang2fhir.create(version="R4", resource="auto", text=answer))
        # lang2fhir stamps a placeholder subject; repoint it at the patient's fullUrl (a plain
        # setdefault would no-op — the placeholder key already exists, leaving it orphaned).
        resource["subject"] = {"reference": patient_full_url}
        tx_bundle["entry"].append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource,
                                   "request": {"method": "POST", "url": resource["resourceType"]}})

    patient_id = None
    try:
        resp = as_dict(client.fhir.execute_bundle(fhir_provider_id=provider, request=tx_bundle))
        for e in resp.get("entry", []) or []:
            loc = (e.get("response") or {}).get("location") or ""
            print(f"  created {loc}")
            if "Patient/" in loc and patient_id is None:
                patient_id = loc.split("Patient/")[1].split("/")[0]
        print(f"persisted {len(resp.get('entry', []) or [])} resources; Patient/{patient_id}")
    except Exception as e:
        print("execute_bundle failed (instance may be read-only):", type(e).__name__, str(e)[:300])
    state["patient_id"] = patient_id


if __name__ == "__main__":
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)
    state, created = load_state(), {"agents": [], "prompts": []}
    try:
        run(client, env, provider, state, created)
        save_state(state)
        print("\nDONE.  Next: .venv/bin/python step2_evaluate.py")
    finally:
        cleanup(client, created)

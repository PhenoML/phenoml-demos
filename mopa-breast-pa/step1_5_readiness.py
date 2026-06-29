#!/usr/bin/env python3
"""Step 1.5 - PA readiness  (MOPA breast-cancer prior-auth demo, PhenoML SDK v15).

Run the SAME DataRequirement gap-check the payer will run, but on the provider side, BEFORE
submitting. The intake chart documents diagnosis, stage, and ER/PR, but HER2 is unresolved, so the
readiness check flags it, a readiness agent phrases the follow-up, and we collect the resolved HER2
and write it back to the EHR. This is PhenoML's Layer 1 role: structure the data, find the gaps,
fill them, then hand a clean payload to the Layer 2 CDS Hooks exchange (Step 2).

Run:  .venv/bin/python step1_5_readiness.py        (run step1_intake.py first)
"""
import uuid

from common import (HERE, load_env, make_client, resolve_provider, as_dict, parse_json,
                    banner, retry, cleanup, load_state, save_state, require, reset_state,
                    fresh_requested)
from cds_hooks_server import evaluate


def _chart_resources(state, extra=None):
    """The structured chart as plain resource dicts: the mCODE evidence + the RequestGroup, plus
    any extra resources (e.g. a freshly collected HER2 Observation)."""
    res = [e["resource"] for e in state["chart_resources"]] + [state["regimen_requestgroup"]]
    if extra:
        res = res + extra
    return res


def run(client, env, provider, state, created):
    require(state, "chart_resources", "regimen_requestgroup", "patient_full_url")
    library = evaluate.load_library()
    state["requirements"] = library

    # --- Step 1.5.1: gap-check the intake chart -------------------------------
    banner("STEP 1.5.1  Readiness gap-check vs the breast-cancer DataRequirements")
    gap = evaluate.check_data_requirements(_chart_resources(state), library)
    missing = gap["missing"]
    print("on file:", ", ".join(s["label"] for s in gap["satisfied"]) or "(none)")
    print("MISSING:", ", ".join(m["label"] for m in missing) or "(none)")
    ready_before = not missing

    # --- Step 1.5.2: readiness agent phrases the follow-up --------------------
    banner("STEP 1.5.2  Readiness agent phrases the follow-up question(s)")
    # A readiness agent (NOT the policy agent) turns the missing-element list into concrete
    # follow-up questions for the care team. Its prompt is a short role, not the UM-9 policy.
    READINESS_PROMPT = (
        "You are a prior-authorization readiness reviewer for medical oncology. You are given the "
        "ordered regimen and the list of required data elements that are missing or unresolved. "
        "Write one concise, specific follow-up question per missing element to collect it from the "
        'care team. Return ONLY JSON: {"follow_up_questions":[...]}')
    rp = client.agent.prompts.create(name="mopa-readiness", content=READINESS_PROMPT,
                                     description="MOPA oncology PA readiness reviewer.")
    created["prompts"].append(rp.data.id)
    readiness_agent = client.agent.create(name="MOPA Readiness Agent", prompts=[rp.data.id],
                                          provider=provider, tags=["mopa", "readiness"])
    created["agents"].append(readiness_agent.data.id)
    review = retry(client.agent.chat.send, label="readiness.chat",
        agent_id=readiness_agent.data.id,
        message=("Ordered regimen: TH (paclitaxel + trastuzumab), adjuvant, breast cancer.\n"
                 "Missing or unresolved required elements: "
                 + (", ".join(m["label"] for m in missing) or "none") + "\n"
                 "Return the JSON."))
    print(review.response)
    follow_up_questions = parse_json(review.response).get("follow_up_questions", [])

    # --- Step 1.5.3: collect HER2 and write it back ---------------------------
    banner("STEP 1.5.3  Collect the resolved HER2 result and write it back (fhir.execute_bundle)")
    # The reflex ISH has resulted: HER2 is POSITIVE (amplified). We structure that as an
    # observation-lab via lang2fhir and persist it, exactly like Step 1 structured the other markers.
    collected_her2 = ("HER2 status by reflex in-situ hybridization (ISH): POSITIVE (HER2 gene "
                      "amplified). Resolves the earlier equivocal IHC 2+ result.")
    state["collected_her2"] = collected_her2
    her2_obs = as_dict(retry(client.lang2fhir.create, label="lang2fhir.her2",
                             version="R4", resource="observation-lab", text=collected_her2))
    her2_obs["subject"] = {"reference": state["patient_full_url"]}
    # Stamp the canonical HER2 LOINC + a definitive positive value so the resolved observation
    # satisfies the HER2 DataRequirement (matched by code) and reads as positive downstream.
    her2_obs.setdefault("code", {}).setdefault("coding", []).append(
        {"system": "http://loinc.org", "code": "85319-2",
         "display": "HER2 [Presence] in Breast cancer specimen by Immune stain"})
    her2_obs["code"].setdefault("text", "HER2 [Presence] in Breast cancer specimen by Immune stain")
    her2_obs["valueCodeableConcept"] = {"text": "Positive (HER2 amplified)"}
    her2_entry = {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": her2_obs,
                  "request": {"method": "POST", "url": "Observation"}}
    state["her2_entry"] = her2_entry

    her2_writeback_ok = False
    try:
        tx = {"resourceType": "Bundle", "type": "transaction", "entry": [her2_entry]}
        resp = as_dict(client.fhir.execute_bundle(fhir_provider_id=provider, request=tx))
        for e in resp.get("entry", []) or []:
            print("  created", (e.get("response") or {}).get("location") or "")
        her2_writeback_ok = True
    except Exception as e:
        print("execute_bundle failed (instance may be read-only):", type(e).__name__, str(e)[:300])
    state["her2_writeback_ok"] = her2_writeback_ok

    # --- Step 1.5.4: re-check readiness ---------------------------------------
    banner("STEP 1.5.4  Re-check readiness with HER2 resolved")
    gap_after = evaluate.check_data_requirements(_chart_resources(state, extra=[her2_obs]), library)
    ready_after = not gap_after["missing"]
    print("MISSING after collection:", ", ".join(m["label"] for m in gap_after["missing"]) or "(none)")
    print(f"ready: {ready_before} -> {ready_after}")

    state["readiness"] = {"ready_before": ready_before, "ready_after": ready_after,
                          "missing_before": [m["label"] for m in missing],
                          "follow_up_questions": follow_up_questions}
    # The structured evidence fact the agent will use once the indication is HER2-positive (kept for
    # display; cds_hooks_server/evaluate.py derives its own from the resolved receptor status).
    state["nccn_fact"] = {"regimen": "TH", "indication": "adjuvant HER2+ breast", "nccn_category": "1"}


if __name__ == "__main__":
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)
    if fresh_requested():
        reset_state()
    state, created = load_state(), {"agents": [], "prompts": []}
    try:
        run(client, env, provider, state, created)
        save_state(state)
        print("\nDONE.  Next: .venv/bin/python step2_cdshooks.py")
    finally:
        cleanup(client, created)

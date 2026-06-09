#!/usr/bin/env python3
"""Step 3 · Adjudicate & submit  (TMS prior-auth demo, PhenoML SDK v15).

Extract the CPT codes for the service, assemble the prior-auth submission from the chart step 1
built, and adjudicate it through the BCBS-MA policy #297 agent — an APPROVED case, then a DENIED
one. Reads the patient id, summary, and evidence from .state/.

Run:  .venv/bin/python step3_adjudicate.py        (run step1_intake.py + step2_evaluate.py first)
"""
import json

from common import (HERE, load_env, make_client, resolve_provider, as_dict,
                    banner, retry, cleanup, load_state, save_state, require)


def run(client, env, provider, state, created):
    require(state, "ips_text", "med_history_text", "follow_up_answers")
    ips_text = state["ips_text"]
    med_history_text = state["med_history_text"]
    follow_up_answers = state["follow_up_answers"]
    patient_id = state.get("patient_id")

    # Recreate the BCBS-MA policy #297 agent so this step stands alone (same prompt as step 2).
    banner("STEP 3.0  Create BCBS-MA policy #297 agent")
    policy_text = (HERE / "policy_297_tms.md").read_text()
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

    # --- Step 3.1: assemble + extract CPT codes -------------------------
    banner("STEP 3.1  Extract CPT codes (construe.codes.extract)")
    from phenoml.construe import ExtractRequestSystem
    cpt = client.construe.codes.extract(
        text=("Therapeutic repetitive transcranial magnetic stimulation (TMS) treatment; initial, "
              "including cortical mapping, motor threshold determination, delivery and management; "
              "plus subsequent delivery and management sessions."),
        system=ExtractRequestSystem(name="CPT", version="2025"))
    cpt_codes = [as_dict(c) for c in (cpt.codes or [])]
    state["cpt_codes"] = cpt_codes
    for c in cpt_codes:
        print(" ", c.get("code"), "-", c.get("description"))

    submission = {
        "patient": f"Patient/{patient_id}" if patient_id else "Patient/example",
        "requested_service": "rTMS for treatment-resistant major depressive disorder",
        "cpt_codes": [c.get("code") for c in cpt_codes][:3],
        "clinical_summary": ips_text,
        "medication_trial_history": med_history_text,
        "supporting_evidence": follow_up_answers,
    }

    # --- Step 3.2: adjudicate (approve path, then a denied case) --------
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


if __name__ == "__main__":
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)
    state, created = load_state(), {"agents": [], "prompts": []}
    try:
        run(client, env, provider, state, created)
        save_state(state)
        print("\nDONE.  The full pipeline has run. See evals/run_evals.py for the accuracy + "
              "determinism scorecard (Part 2).")
    finally:
        cleanup(client, created)

#!/usr/bin/env python3
"""Step 2 · Evaluate prior auth  (TMS prior-auth demo, PhenoML SDK v15).

Build the BCBS-MA policy #297 agent (its system prompt *is* the policy), evaluate the case with
the full evidence on file, then watch the decision **flip** when the psychotherapy answer is
dropped — same patient, same agent, different evidence. Reads the chart step 1 wrote to .state/.

Run:  .venv/bin/python step2_evaluate.py        (run step1_intake.py first)
"""
import json

from common import (HERE, load_env, make_client, resolve_provider, as_dict, parse_json,
                    banner, retry, cleanup, load_state, save_state, require)


def run(client, env, provider, state, created):
    require(state, "ips_text", "med_history_text", "follow_up_answers")
    ips_text = state["ips_text"]
    med_history_text = state["med_history_text"]
    follow_up_answers = state["follow_up_answers"]

    # --- Step 1.5: BCBS-MA policy agent ---------------------------------
    banner("STEP 1.5  Create BCBS-MA policy #297 agent")
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

    # --- Step 2.1: prior-auth evaluation --------------------------------
    banner("STEP 2.1  Prior-auth evaluation (full evidence, then psychotherapy dropped -> flip)")
    # The prior-auth agent needs the IPS *plus* the medication trial history (criterion #2 evidence)
    # plus the follow-up answers — all in the MESSAGE.
    PA_PROMPT = ('A provider requests prior auth for rTMS (CPT 90867/90868/90869). Evaluate the '
                 'patient below against policy #297 and return ONLY JSON: {"meets_criteria":true|false,'
                 '"satisfied":[...],"unmet":[...],"additional_info_needed":[...],"rationale":"..."}\n\n')
    pa_evidence = (
        "=== INTERNATIONAL PATIENT SUMMARY ===\n" + ips_text
        + "\n\n=== MEDICATION TRIAL HISTORY (from chart) ===\n" + med_history_text
        + "\n\n=== ADDITIONAL FOLLOW-UP INFORMATION ON FILE ===\n"
        + "\n".join(f"- {a}" for a in follow_up_answers)
    )
    pa = retry(client.agent.chat.send, label="pa.eval",
        agent_id=bcbs_agent.data.id, message=PA_PROMPT + pa_evidence, enhanced_reasoning=True)
    print("APPROVE-PATH (all evidence on file):")
    print(json.dumps(parse_json(pa.response), indent=2)[:2000])

    # Flip the decision: same patient, same agent, but DROP the psychotherapy answer
    # (follow_up_answers[0] = the CBT course, the only evidence for criterion #3) -> meets_criteria=false.
    pa_evidence_no_psych = (
        "=== INTERNATIONAL PATIENT SUMMARY ===\n" + ips_text
        + "\n\n=== MEDICATION TRIAL HISTORY (from chart) ===\n" + med_history_text
        + "\n\n=== ADDITIONAL FOLLOW-UP INFORMATION ON FILE ===\n"
        + "\n".join(f"- {a}" for a in follow_up_answers[1:])      # psychotherapy answer dropped
    )
    pa_flip = retry(client.agent.chat.send, label="pa.eval.flip",
        agent_id=bcbs_agent.data.id, message=PA_PROMPT + pa_evidence_no_psych, enhanced_reasoning=True)
    print("\nFLIP-PATH (psychotherapy answer dropped -> expect meets_criteria=false):")
    print(json.dumps(parse_json(pa_flip.response), indent=2)[:2000])

    # --- Step 2.2: workflow alternative (optional) ----------------------
    banner("STEP 2.2  Workflow alternative (create + execute)")
    patient_id = state.get("patient_id")
    try:
        if env.get("SKIP_WORKFLOW", "").strip().lower() in ("1", "true", "yes", "on"):
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
            wf_run = client.workflows.execute(wf.workflow_id, input_data={"patient_id": patient_id})
            print(as_dict(wf_run))
    except Exception as e:
        print("workflow step skipped/failed:", type(e).__name__, str(e)[:300])


if __name__ == "__main__":
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)
    state, created = load_state(), {"agents": [], "prompts": []}
    try:
        run(client, env, provider, state, created)
        save_state(state)
        print("\nDONE.  Next: .venv/bin/python step3_adjudicate.py")
    finally:
        cleanup(client, created)

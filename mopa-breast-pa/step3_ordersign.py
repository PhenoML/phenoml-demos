#!/usr/bin/env python3
"""Step 3 - Order-sign & adjudicate  (MOPA breast-cancer prior-auth demo, PhenoML SDK v15).

The DTR has been answered (HER2 resolved POSITIVE in Step 1.5). Send the order-sign envelope: the
oncology-crd service applies UM-9, finds TH is NCCN Category 1 for adjuvant HER2-positive breast
cancer (medically accepted), and returns Response A, a pre-approved card plus a Coverage
systemAction. Then a contrast: the same regimen against a HER2-NEGATIVE result, which is not a
medically accepted use and is DENIED. Same regimen, same service, the receptor status flips it.

Run:  .venv/bin/python step3_ordersign.py        (run steps 1, 1.5, and 2 first)
"""
import json, uuid

from common import (load_env, make_client, resolve_provider, banner, cleanup,
                    load_state, save_state, require, reset_state, fresh_requested)
from cds_hooks_server import evaluate
from step2_cdshooks import build_envelope, call_cds, classify, _show


def run(client, env, provider, state, created):
    require(state, "draft_order_entries", "chart_resources", "regimen_requestgroup",
            "her2_entry", "patient_full_url")
    state.setdefault("requirements", evaluate.load_library())

    # --- Step 3.1: order-sign with HER2 positive -> Response A + Coverage -------
    banner("STEP 3.1  order-sign, HER2 positive -> Response A (pre-approved + Coverage)")
    env_sign = build_envelope(state, "order-sign", her2_entry=state["her2_entry"])
    state["order_sign_envelope"] = env_sign
    resp = call_cds(env, client, provider, state, created, env_sign)
    _show(resp)
    state["final_card"] = (resp.get("cards") or [None])[0]
    state["coverage_systemaction"] = (resp.get("systemActions") or [None])[0]
    print("outcome:", classify(resp))
    if state["coverage_systemaction"]:
        print("Coverage:", json.dumps(state["coverage_systemaction"]["resource"]))

    # --- Step 3.2: DENY contrast, HER2 negative --------------------------------
    banner("STEP 3.2  Contrast: same regimen, HER2 NEGATIVE -> DENIED")
    # A contrasting hypothetical: had the reflex ISH returned HER2-negative, TH would not be the
    # accepted adjuvant regimen (not a listed Category 1-2A use), so UM-9 denies it. We hand-build
    # the negative HER2 Observation as the only receptor difference.
    her2_neg = {"resourceType": "Observation", "status": "final",
                "code": {"text": "HER2 [Presence] in Breast cancer specimen by Immune stain",
                         "coding": [{"system": "http://loinc.org", "code": "85319-2",
                                     "display": "HER2 [Presence] in Breast cancer specimen by Immune stain"}]},
                "valueCodeableConcept": {"text": "Negative (HER2 not amplified)"},
                "subject": {"reference": state["patient_full_url"]}}
    her2_neg_entry = {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": her2_neg}
    env_deny = build_envelope(state, "order-sign", her2_entry=her2_neg_entry)
    resp_deny = call_cds(env, client, provider, state, created, env_deny)
    _show(resp_deny)
    state["deny_response"] = resp_deny
    print("outcome:", classify(resp_deny))


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
        print("\nDONE.  The full pipeline has run. See evals/run_evals.py for the accuracy + "
              "determinism scorecard.")
    finally:
        cleanup(client, created)

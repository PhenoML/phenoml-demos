#!/usr/bin/env python3
"""Step 2 - CDS Hooks exchange  (MOPA breast-cancer prior-auth demo, PhenoML SDK v15).

Assemble the order-select envelope (the regimen as draftOrders + the patient's chart as prefetch)
and post it to the oncology-crd service. With HER2 still unresolved the service returns Response B
(a DTR card asking for HER2); once HER2 is on file the same order returns Response A (pre-approved).
Same order, same service, different evidence, watch the card flip.

By default the demo runs SIMULATED: it calls cds_hooks_server/evaluate.py in-process (no extra
process). Set CDS_HOOKS_URL=http://localhost:8088 to POST to a live shim instead.

Run:  .venv/bin/python step2_cdshooks.py        (run step1_intake.py + step1_5_readiness.py first)
"""
import json, uuid

import httpx

from common import (load_env, make_client, resolve_provider, banner, retry, cleanup,
                    load_state, save_state, require, reset_state, fresh_requested)
from cds_hooks_server import evaluate


def ensure_agent(client, provider, state, created):
    """Build the UM-9 agent once for the in-process (simulated) path and reuse it within this
    process. The id is only reused if it belongs to THIS process's `created` list, so a standalone
    step never points at an agent a previous process already deleted on cleanup."""
    aid = state.get("um9_agent_id")
    if aid and aid in created.get("agents", []):
        return aid
    aid = evaluate.build_agent_once(client, provider, created)
    state["um9_agent_id"] = aid
    return aid


def build_envelope(state, hook, her2_entry=None):
    """Build a CDS Hooks 2.0 request: the regimen RequestGroup + drugs as context.draftOrders, the
    Library + the patient's chart as prefetch. Pass her2_entry to include a resolved HER2 Observation
    (omit it to reproduce the intake state where HER2 is still missing)."""
    patient_id = state.get("patient_id") or "jane-smith-demo"
    draft = {"resourceType": "Bundle", "type": "collection",
             "entry": [{"fullUrl": e["fullUrl"], "resource": e["resource"]}
                       for e in state["draft_order_entries"]]}
    patient = next((e["resource"] for e in state["bundle"]["entry"]
                    if e["resource"]["resourceType"] == "Patient"), None)
    chart = [{"resource": e["resource"]} for e in state["chart_resources"]]
    if her2_entry:
        chart.append({"resource": her2_entry["resource"]})
    patient_entries = ([{"resource": patient}] if patient else []) + chart
    return {
        "hook": hook,
        "hookInstance": str(uuid.uuid4()),
        "fhirServer": state.get("fhir_server"),
        "context": {"patientId": patient_id, "userId": "Practitioner/onc-1", "draftOrders": draft},
        "prefetch": {
            "library": state.get("requirements") or evaluate.load_library(),
            "patientData": {"resourceType": "Bundle", "type": "collection", "entry": patient_entries},
        },
    }


def call_cds(env, client, provider, state, created, envelope):
    """Post to a live shim if CDS_HOOKS_URL is set, otherwise call evaluate.evaluate in-process."""
    url = (env.get("CDS_HOOKS_URL") or "").strip()
    if url:
        r = retry(httpx.post, f"{url.rstrip('/')}/cds-services/oncology-crd",
                  json=envelope, timeout=120, label="cds-hooks.post")
        return r.json()
    agent_id = ensure_agent(client, provider, state, created)
    return evaluate.evaluate(client, agent_id, envelope, state["requirements"])


def classify(resp):
    """Collapse a CDS Hooks response onto the demo's three outcomes."""
    cards = resp.get("cards") or []
    if not cards:
        return "no-card"
    if resp.get("systemActions"):
        return "pre-approved"
    card = cards[0]
    if any(l.get("type") == "smart" for l in (card.get("links") or [])) or card.get("indicator") == "warning":
        return "needs-more-info"
    if card.get("indicator") == "critical":
        return "deny"
    if card.get("indicator") == "info":
        return "pre-approved"
    return "unknown"


def _show(resp):
    for c in resp.get("cards") or []:
        print(f"  [{c.get('indicator')}] {c.get('summary')}")
        if c.get("links"):
            for l in c["links"]:
                print(f"     link ({l.get('type')}): {l.get('label')} -> {l.get('url')}")
    if resp.get("systemActions"):
        print("  systemActions:", json.dumps(resp["systemActions"])[:200])


def run(client, env, provider, state, created):
    require(state, "draft_order_entries", "chart_resources", "regimen_requestgroup", "her2_entry")
    state.setdefault("requirements", evaluate.load_library())
    mode = "live (CDS_HOOKS_URL)" if (env.get("CDS_HOOKS_URL") or "").strip() else "simulated (in-process)"

    # --- Step 2.1: order-select with HER2 still missing -> Response B (DTR) ----
    banner(f"STEP 2.1  order-select, HER2 missing -> Response B (DTR card)   [{mode}]")
    env_b = build_envelope(state, "order-select", her2_entry=None)
    state["order_select_envelope"] = env_b
    resp_b = call_cds(env, client, provider, state, created, env_b)
    _show(resp_b)
    state["cds_response_dtr"], outcome_b = resp_b, classify(resp_b)
    print("outcome:", outcome_b)

    # --- Step 2.2: order-select once HER2 is on file -> Response A (flip) -------
    banner("STEP 2.2  order-select, HER2 resolved -> Response A (pre-approved)")
    env_a = build_envelope(state, "order-select", her2_entry=state["her2_entry"])
    resp_a = call_cds(env, client, provider, state, created, env_a)
    _show(resp_a)
    state["cds_response_approved"], outcome_a = resp_a, classify(resp_a)
    print("outcome:", outcome_a)
    state["cds_outcome"] = {"her2_missing": outcome_b, "her2_resolved": outcome_a}


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
        print("\nDONE.  Next: .venv/bin/python step3_ordersign.py")
    finally:
        cleanup(client, created)

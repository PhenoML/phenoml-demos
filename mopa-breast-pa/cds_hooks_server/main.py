#!/usr/bin/env python3
"""A thin CDS Hooks 2.0 shim we own (FastAPI), for the MOPA oncology-crd service.

There is no maintained pip-installable CDS Hooks server framework, so this is a minimal shim that
implements just the two endpoints the demo needs. The actual judgment lives in evaluate.py, which
both this server and the in-process simulated path import, so they always agree.

  GET  /cds-services                 -> the discovery document
  POST /cds-services/oncology-crd    -> resolve the Library, check DataRequirements, call the UM-9
                                        agent, return Response A (pre-approved + Coverage) / B (DTR)

Run live:  uvicorn cds_hooks_server.main:app --port 8088
Then point the demo at it with CDS_HOOKS_URL=http://localhost:8088 (otherwise step2/step3 call
evaluate.py in-process, no server needed).
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import load_env, make_client, resolve_provider, cleanup  # noqa: E402
from cds_hooks_server import evaluate  # noqa: E402

# The discovery document. CRD normally registers order-select and order-sign as separate hooks; we
# expose one service the demo posts both envelopes to (the request's `hook` field distinguishes
# them) to keep the shim minimal. Prefetch templates use the {{context.patientId}} token form.
DISCOVERY = {"services": [{
    "hook": "order-select",
    "id": "oncology-crd",
    "title": "Oncology Prior-Auth CRD (OncoHealth UM-9)",
    "description": "Checks an ordered oncology regimen for PA readiness and medical acceptance "
                   "under OncoHealth UM-9, returning a pre-approved card, a DTR card, or a denial.",
    "prefetch": {
        "library": "Library?identifier=mopa-breast-requirements",
        "condition": "Condition?patient={{context.patientId}}&code=254837009",
        "tumorMarkers": "Observation?patient={{context.patientId}}&category=laboratory",
        "stage": "Observation?patient={{context.patientId}}&code=21908-9",
        "ecog": "Observation?patient={{context.patientId}}&code=89247-1",
    },
}]}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the UM-9 agent ONCE at startup (not per request) and load the Library. If credentials
    # are absent we still serve discovery and the DTR path (which needs no agent); only the
    # medical-acceptance judgment is unavailable. Agents/prompts are deleted on shutdown.
    app.state.created = {"agents": [], "prompts": []}
    app.state.library = evaluate.load_library()
    app.state.client = None
    app.state.agent_id = None
    try:
        env = load_env()
        client = make_client(env)
        provider = resolve_provider(client, env)
        app.state.client = client
        app.state.agent_id = evaluate.build_agent_once(client, provider, app.state.created)
        print(f"[cds-hooks] UM-9 agent ready: {app.state.agent_id}")
    except SystemExit as e:
        print(f"[cds-hooks] no credentials, serving discovery + DTR only ({e})")
    except Exception as e:
        print(f"[cds-hooks] agent init failed, serving discovery + DTR only: {type(e).__name__}: {e}")
    try:
        yield
    finally:
        if app.state.client and app.state.created["agents"]:
            cleanup(app.state.client, app.state.created)


app = FastAPI(title="MOPA oncology-crd CDS Hooks shim", lifespan=lifespan)


@app.get("/cds-services")
def discovery():
    return DISCOVERY


@app.post("/cds-services/oncology-crd")
async def oncology_crd(request: Request):
    body = await request.json()
    try:
        return evaluate.evaluate(app.state.client, app.state.agent_id, body, app.state.library)
    except Exception as e:
        # Never 500 the EHR: surface the failure as an info card so the order flow continues.
        return {"cards": [{
            "summary": "Prior-auth service unavailable",
            "indicator": "info",
            "detail": f"The UM-9 judgment could not be completed: {type(e).__name__}: {str(e)[:200]}",
            "source": {"label": "OncoHealth UM-9 Chemotherapy Review Criteria"},
        }], "systemActions": []}

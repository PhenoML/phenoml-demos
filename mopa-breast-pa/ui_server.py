#!/usr/bin/env python3
"""FastAPI backend for the MOPA prior-auth UI.

Two personas over one pipeline:
  Provider  - paste a pathology report -> lang2fhir/construe/IPS + readiness gap-check (HER2) ->
              resolve HER2 -> submit a preauthorization Claim to the EHR (Medplum, via PhenoML).
  Payer     - review the queue of Claims -> get the OncoHealth UM-9 agent's recommendation
              (rebuilds the CDS Hooks order-sign envelope + runs cds_hooks_server/evaluate.py) ->
              approve/deny (human-in-the-loop) -> write a ClaimResponse (+ Coverage on approve).

Runs at the demo top level so `import pipeline, pa_fhir`, `from common import ...`,
`from cds_hooks_server import evaluate`, and `from step2_cdshooks import build_envelope` resolve
exactly like the step scripts. The UM-9 and readiness agents are built ONCE at startup (lifespan)
and deleted on shutdown - never per request.

Run:  .venv/bin/uvicorn ui_server:app --port 8001 --reload
"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from common import load_env, make_client, resolve_provider, parse_json, retry, cleanup
from cds_hooks_server import evaluate
from step2_cdshooks import build_envelope, classify
import pipeline
import pa_fhir

READINESS_PROMPT = (
    "You are a prior-authorization readiness reviewer for medical oncology. You are given the "
    "ordered regimen and the list of required data elements that are missing or unresolved. "
    "Write one concise, specific follow-up question per missing element to collect it from the "
    'care team. Return ONLY JSON: {"follow_up_questions":[...]}')

# In-memory cache of intake results keyed by intake_id, so /submit does not re-run the (paid)
# lang2fhir/construe extraction. A demo-scale dict; fine to lose on restart.
INTAKES: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = None
    app.state.provider = None
    app.state.um9_agent_id = None
    app.state.readiness_agent_id = None
    app.state.library = evaluate.load_library()
    app.state.created = {"agents": [], "prompts": []}
    app.state.writable = False
    try:
        env = load_env()
        client = make_client(env)
        provider = resolve_provider(client, env)
        app.state.client, app.state.provider = client, provider
        # Build both agents once (UM-9 for judgment, readiness for phrasing follow-ups).
        app.state.um9_agent_id = evaluate.build_agent_once(client, provider, app.state.created)
        rp = client.agent.prompts.create(name="mopa-readiness-ui", content=READINESS_PROMPT,
                                         description="MOPA oncology PA readiness reviewer (UI).")
        app.state.created["prompts"].append(rp.data.id)
        ra = client.agent.create(name="MOPA Readiness Agent (UI)", prompts=[rp.data.id],
                                 provider=provider, tags=["mopa", "readiness", "ui"])
        app.state.created["agents"].append(ra.data.id)
        app.state.readiness_agent_id = ra.data.id
        print(f"[ui] agents ready: um9={app.state.um9_agent_id} readiness={ra.data.id}")
    except SystemExit as e:
        print(f"[ui] no credentials; API will return 503 until configured ({e})")
    except Exception as e:
        print(f"[ui] agent init failed: {type(e).__name__}: {e}")
    try:
        yield
    finally:
        if app.state.client and app.state.created["agents"]:
            cleanup(app.state.client, app.state.created)


app = FastAPI(title="MOPA prior-auth UI backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173",
                   "http://127.0.0.1:5174", "http://localhost:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


def _require_client():
    if app.state.client is None:
        raise HTTPException(503, "PhenoML client not initialized. Set PHENOML_CLIENT_ID / "
                                 "PHENOML_CLIENT_SECRET (and PHENOML_FHIR_PROVIDER_ID) and restart.")
    return app.state.client, app.state.provider


# ---------- helpers -------------------------------------------------------
def _chart_resource_dicts(artifacts: dict, extra=None) -> list:
    """Plain resource dicts (chart entries + regimen) for the readiness gap-check."""
    res = [e["resource"] for e in artifacts["chart_resources"]] + [artifacts["regimen_requestgroup"]]
    return res + (extra or [])


def _readiness(client, artifacts: dict, extra=None) -> dict:
    gap = evaluate.check_data_requirements(_chart_resource_dicts(artifacts, extra), app.state.library)
    follow_ups = []
    if gap["missing"] and app.state.readiness_agent_id:
        msg = ("Ordered regimen: TH (paclitaxel + trastuzumab), adjuvant, breast cancer.\n"
               "Missing or unresolved required elements: "
               + ", ".join(m["label"] for m in gap["missing"]) + "\nReturn the JSON.")
        try:
            r = retry(client.agent.chat.send, label="readiness.chat",
                      agent_id=app.state.readiness_agent_id, message=msg)
            follow_ups = parse_json(r.response).get("follow_up_questions", [])
        except Exception as e:
            follow_ups = [f"(readiness agent unavailable: {type(e).__name__})"]
    return {"satisfied": gap["satisfied"], "missing": gap["missing"],
            "follow_up_questions": follow_ups}


def _static_her2_entry(patient_url: str, positive: bool) -> dict:
    """A static HER2 Observation entry (no network call) for the reviewer's what-if toggle."""
    value = "Positive (HER2 amplified)" if positive else "Negative (HER2 not amplified)"
    return {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "request": {"method": "POST", "url": "Observation"},
            "resource": {"resourceType": "Observation", "status": "final",
                         "code": {"text": "HER2 [Presence] in Breast cancer specimen by Immune stain",
                                  "coding": [{"system": "http://loinc.org", "code": "85319-2",
                                              "display": "HER2 [Presence] in Breast cancer specimen by Immune stain"}]},
                         "valueCodeableConcept": {"text": value},
                         "subject": {"reference": patient_url}}}


# ---------- request models ------------------------------------------------
class IntakeReq(BaseModel):
    report_text: str


class SubmitReq(BaseModel):
    intake_id: str
    her2_result: str = ("HER2 status by reflex in-situ hybridization (ISH): POSITIVE (HER2 gene "
                        "amplified). Resolves the earlier equivocal IHC 2+ result.")
    her2_positive: bool = True


class RecommendReq(BaseModel):
    her2_override: str | None = None   # None -> use resolved HER2; "positive" / "negative" -> what-if


class DecisionReq(BaseModel):
    decision: str                       # "approve" | "deny"
    note: str = ""
    citations: list = []
    coverage: dict | None = None        # the systemAction from the recommendation, on approve


# ---------- endpoints -----------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "healthy", "configured": app.state.client is not None,
            "provider": app.state.provider, "um9_agent": app.state.um9_agent_id}


@app.get("/api/sample-report")
def sample_report():
    return {"report_text": (pipeline.HERE / "sample_path_report.txt").read_text()}


@app.post("/api/intake")
def intake(req: IntakeReq):
    client, provider = _require_client()
    if not (req.report_text or "").strip():
        raise HTTPException(400, "report_text is required")
    artifacts = pipeline.run_intake(client, provider, req.report_text)
    readiness = _readiness(client, artifacts)
    intake_id = uuid.uuid4().hex[:12]
    INTAKES[intake_id] = {**artifacts, "readiness": readiness}
    return {
        "intake_id": intake_id,
        "patient_name": pa_fhir.patient_name(artifacts),
        "patient_id": artifacts["patient_id"],
        "resources": [e["resource"] for e in artifacts["chart_resources"]],
        "construe_codes": artifacts["construe_codes"],
        "regimen": artifacts["regimen_requestgroup"],
        "ips_text": artifacts["ips_text"],
        "readiness": readiness,
        "write": artifacts["write"],
    }


@app.post("/api/submit")
def submit(req: SubmitReq):
    client, provider = _require_client()
    artifacts = INTAKES.get(req.intake_id)
    if not artifacts:
        raise HTTPException(404, "unknown intake_id (re-run intake)")

    # Resolve HER2 and write it back to the EHR, exactly like Step 1.5.
    her2_entry = pipeline.build_her2_observation(client, req.her2_result,
                                                 artifacts["patient_full_url"], positive=req.her2_positive)
    write = pipeline.persist_chart(client, provider, {"resourceType": "Bundle", "type": "transaction",
                                                      "entry": []}, [her2_entry], [])
    readiness_after = _readiness(client, artifacts, extra=[her2_entry["resource"]])

    snapshot = {
        "bundle": artifacts["bundle"],
        "chart_resources": artifacts["chart_resources"],
        "regimen_requestgroup": artifacts["regimen_requestgroup"],
        "draft_order_entries": artifacts["draft_order_entries"],
        "patient_id": artifacts["patient_id"],
        "patient_full_url": artifacts["patient_full_url"],
        "requirements": app.state.library,
        "her2_entry": her2_entry,
        "ips_text": artifacts["ips_text"],
        "construe_codes": artifacts["construe_codes"],
        "readiness": readiness_after,
        "nccn_fact": {"regimen": "TH", "indication": "adjuvant HER2+ breast", "nccn_category": "1"},
    }
    record = pa_fhir.submit_claim(client, provider, snapshot)
    return {"claim": pa_fhir._light(record), "her2_writeback": write, "readiness": readiness_after}


@app.get("/api/claims")
def claims():
    return {"claims": pa_fhir.list_claims()}


@app.get("/api/claims/{claim_id}")
def claim_detail(claim_id: str):
    record = pa_fhir.get_claim(claim_id)
    if not record:
        raise HTTPException(404, "unknown claim")
    snap = record["snapshot"]
    return {
        "claim": pa_fhir._light(record),
        "patient_name": record["patient_name"],
        "ips_text": snap.get("ips_text"),
        "regimen": snap.get("regimen_requestgroup"),
        "resources": [e["resource"] for e in snap.get("chart_resources", [])]
                     + ([snap["her2_entry"]["resource"]] if snap.get("her2_entry") else []),
        "readiness": snap.get("readiness"),
        "construe_codes": snap.get("construe_codes"),
        "decision": record.get("decision"),
    }


@app.post("/api/claims/{claim_id}/recommendation")
def recommendation(claim_id: str, req: RecommendReq):
    client, provider = _require_client()
    record = pa_fhir.get_claim(claim_id)
    if not record:
        raise HTTPException(404, "unknown claim")
    snap = record["snapshot"]

    # Pick the HER2 evidence: resolved (default, as submitted) or a reviewer what-if override.
    if req.her2_override == "negative":
        her2_entry = _static_her2_entry(snap["patient_full_url"], positive=False)
    elif req.her2_override == "positive":
        her2_entry = _static_her2_entry(snap["patient_full_url"], positive=True)
    else:  # None -> the resolved HER2 collected at submit
        her2_entry = snap.get("her2_entry")

    envelope = build_envelope({**snap, "requirements": app.state.library}, "order-sign",
                              her2_entry=her2_entry)
    resp = evaluate.evaluate(client, app.state.um9_agent_id, envelope, app.state.library)
    outcome = classify(resp)
    card = (resp.get("cards") or [{}])[0]
    coverage = (resp.get("systemActions") or [None])[0]
    decision = {"pre-approved": "APPROVED", "deny": "DENIED",
                "needs-more-info": "NEEDS_INFO"}.get(outcome, outcome.upper())
    return {"outcome": outcome, "decision": decision, "card": card,
            "coverage": coverage, "her2_used": req.her2_override or "resolved"}


@app.post("/api/claims/{claim_id}/decision")
def decision(claim_id: str, req: DecisionReq):
    client, provider = _require_client()
    if req.decision.lower() not in ("approve", "approved", "deny", "denied"):
        raise HTTPException(400, "decision must be 'approve' or 'deny'")
    try:
        record = pa_fhir.record_decision(client, provider, claim_id, req.decision, req.note,
                                         req.citations, req.coverage)
    except KeyError:
        raise HTTPException(404, "unknown claim")
    return {"claim": pa_fhir._light(record)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ui_server:app", host="127.0.0.1", port=8001, reload=True)

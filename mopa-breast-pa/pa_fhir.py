#!/usr/bin/env python3
"""Prior-auth persistence layer for the MOPA web UI: Claim (submission) + ClaimResponse (decision).

The step-script demo produces CDS Hooks cards + a Coverage systemAction but nothing durable to build
a review queue on. The UI needs a persistent prior-auth request, so this module models it the
standard FHIR / Da Vinci PAS way:

  - Claim (use=preauthorization)  -> the provider's submission (the payer's queue item)
  - ClaimResponse (request->Claim) -> the reviewer's decision (approved / denied)
  - Coverage                       -> written on approval (the pre-approval record)

Medplum (reached THROUGH PhenoML: client.fhir.* proxies to the registered FHIR provider) is the
system of record. Because writing needs a dedicated instance, every write degrades gracefully: on a
read-only provider the resource is not persisted but a local registry (.state/claims.json) keeps the
demo fully functional. The registry also holds the intake "snapshot" (chart + regimen + library +
resolved HER2) the reviewer needs to rebuild the CDS Hooks envelope and re-run the UM-9 judgment.
"""
import json, uuid
from datetime import datetime, timezone
from pathlib import Path

from common import as_dict

HERE = Path(__file__).resolve().parent
CLAIMS_FILE = HERE / ".state" / "claims.json"

CLAIM_TYPE = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type",
                          "code": "professional"}]}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- local registry (queue + snapshot; survives restart & read-only) ----
def _load_registry() -> dict:
    if CLAIMS_FILE.exists():
        return json.loads(CLAIMS_FILE.read_text())
    return {"claims": {}}


def _save_registry(reg: dict):
    CLAIMS_FILE.parent.mkdir(exist_ok=True)
    CLAIMS_FILE.write_text(json.dumps(reg, indent=2))


def _created_id(resp) -> str | None:
    """Pull the server-assigned id out of a fhir.create response (the created resource, or a
    location-ish dict). Returns None if it cannot be found."""
    d = as_dict(resp)
    if isinstance(d, dict):
        if d.get("id"):
            return d["id"]
        loc = (d.get("meta") or {}).get("versionId")  # not an id, but guard anyway
        _ = loc
    return None


def _patient_ref(snapshot: dict) -> dict:
    pid = snapshot.get("patient_id")
    return {"reference": f"Patient/{pid}"} if pid else {"display": patient_name(snapshot)}


def patient_name(snapshot: dict) -> str:
    """Best-effort display name from the extracted Patient resource."""
    for e in (snapshot.get("bundle") or {}).get("entry", []):
        r = e.get("resource") or {}
        if r.get("resourceType") == "Patient":
            n = (r.get("name") or [{}])[0]
            if n.get("text"):
                return n["text"]
            given = " ".join(n.get("given") or [])
            return (given + " " + n.get("family", "")).strip() or "Unknown patient"
    return "Unknown patient"


# ---------- resource builders --------------------------------------------
def build_claim(snapshot: dict, local_id: str) -> dict:
    """A minimal-but-valid preauthorization Claim for the ordered regimen. The evidence snapshot
    (IPS + readiness) rides along as an extension so the queue can show context without a re-fetch."""
    regimen_text = ((snapshot.get("regimen_requestgroup") or {}).get("code") or {}).get(
        "text", "TH (paclitaxel + trastuzumab)")
    evidence = {"ips": (snapshot.get("ips_text") or "")[:4000],
                "readiness": snapshot.get("readiness"),
                "nccn_fact": snapshot.get("nccn_fact")}
    return {
        "resourceType": "Claim",
        "identifier": [{"system": "https://mopa.demo/claim", "value": local_id}],
        "status": "active",
        "type": CLAIM_TYPE,
        "use": "preauthorization",
        "patient": _patient_ref(snapshot),
        "created": _now(),
        "provider": {"display": "Lakeside Oncology"},
        "priority": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/processpriority",
                                 "code": "normal"}]},
        "insurance": [{"sequence": 1, "focal": True,
                       "coverage": {"display": "Commercial plan (OncoHealth UM)"}}],
        "item": [{"sequence": 1, "productOrService": {"text": regimen_text}}],
        "extension": [{"url": "https://mopa.demo/StructureDefinition/pa-evidence",
                       "valueString": json.dumps(evidence)}],
    }


def build_claim_response(snapshot: dict, fhir_claim_id: str | None, decision: str,
                         rationale: str, citations: list) -> dict:
    """A ClaimResponse recording the reviewer's decision (complete/approved or complete/denied)."""
    approved = decision.lower().startswith("approv")
    resp = {
        "resourceType": "ClaimResponse",
        "status": "active",
        "type": CLAIM_TYPE,
        "use": "preauthorization",
        "patient": _patient_ref(snapshot),
        "created": _now(),
        "insurer": {"display": "OncoHealth (delegated UM)"},
        "outcome": "complete",
        "disposition": (rationale or "")[:1000] or ("Approved" if approved else "Denied"),
        "item": [{"itemSequence": 1, "adjudication": [{
            "category": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/adjudication",
                "code": "eligible" if approved else "denied"}]}}]}],
        "extension": [
            {"url": "https://mopa.demo/StructureDefinition/pa-decision",
             "valueString": "approved" if approved else "denied"},
            {"url": "https://mopa.demo/StructureDefinition/pa-citations",
             "valueString": json.dumps(citations or [])},
        ],
    }
    if fhir_claim_id:
        resp["request"] = {"reference": f"Claim/{fhir_claim_id}"}
    return resp


# ---------- write / read through PhenoML -> Medplum ----------------------
def _try_create(client, provider, resource_type: str, resource: dict):
    """Create a resource on the FHIR provider. Returns (id_or_None, error_or_None); never raises,
    so a read-only instance degrades to a local-only record instead of failing the request."""
    try:
        resp = client.fhir.create(fhir_provider_id=provider, fhir_path=resource_type, request=resource)
        return _created_id(resp), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:200]}"


def submit_claim(client, provider, snapshot: dict) -> dict:
    """Persist a preauthorization Claim (best-effort) and record it in the local registry. Returns
    the queue record."""
    local_id = uuid.uuid4().hex[:12]
    claim = build_claim(snapshot, local_id)
    fhir_id, err = _try_create(client, provider, "Claim", claim)
    record = {
        "id": local_id,
        "fhir_claim_id": fhir_id,
        "persisted": bool(fhir_id),
        "persist_error": err,
        "patient_name": patient_name(snapshot),
        "patient_id": snapshot.get("patient_id"),
        "regimen_text": claim["item"][0]["productOrService"]["text"],
        "created": claim["created"],
        "status": "queued",              # queued -> approved / denied
        "decision": None,
        "snapshot": snapshot,            # working data to rebuild the CDS envelope on review
    }
    reg = _load_registry()
    reg["claims"][local_id] = record
    _save_registry(reg)
    return record


def _light(record: dict) -> dict:
    """A record without the heavy snapshot, for the queue list."""
    return {k: v for k, v in record.items() if k != "snapshot"}


def list_claims(client=None, provider=None) -> list:
    """The payer queue: registry records (newest first), snapshot stripped. Reads are registry-backed
    so the queue is stable even on a read-only FHIR instance; each record carries fhir_claim_id +
    persisted so the UI can show whether it lives in Medplum."""
    reg = _load_registry()
    records = [_light(r) for r in reg["claims"].values()]
    return sorted(records, key=lambda r: r.get("created", ""), reverse=True)


def get_claim(local_id: str) -> dict | None:
    return _load_registry()["claims"].get(local_id)


def record_decision(client, provider, local_id: str, decision: str, rationale: str,
                    citations: list, coverage_action: dict | None) -> dict:
    """Write a ClaimResponse (+ Coverage on approve) for the claim and update the registry record."""
    reg = _load_registry()
    record = reg["claims"].get(local_id)
    if not record:
        raise KeyError(local_id)
    if record.get("status") in ("approved", "denied"):
        # Already decided: refuse to write a second ClaimResponse / overwrite the recorded outcome.
        raise ValueError(f"claim already {record['status']}")
    snapshot = record["snapshot"]
    cr = build_claim_response(snapshot, record.get("fhir_claim_id"), decision, rationale, citations)
    cr_id, cr_err = _try_create(client, provider, "ClaimResponse", cr)

    coverage_id = None
    approved = decision.lower().startswith("approv")
    if approved and coverage_action and coverage_action.get("resource"):
        coverage_id, _ = _try_create(client, provider, "Coverage", coverage_action["resource"])

    record["status"] = "approved" if approved else "denied"
    record["decision"] = {"decision": "approved" if approved else "denied",
                          "rationale": rationale, "citations": citations or [],
                          "claim_response_id": cr_id, "claim_response_error": cr_err,
                          "coverage_id": coverage_id, "decided_at": _now()}
    reg["claims"][local_id] = record
    _save_registry(reg)
    return record

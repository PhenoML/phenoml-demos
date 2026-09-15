"""Shared plumbing for the GLP-1 fhir2omop demo (PhenoML SDK v17).

Env/auth, the PhenomlClient factory, FHIR search pagination, tag conventions, and
small helpers shared by seed_glp1_data.py and app.py. The interesting demo logic
lives in those two files; only boilerplate lives here.

Credentials come from glp1-fhir2omop/.env (preferred) or the repo-root ../.env.
Auth: PHENOML_CLIENT_ID + PHENOML_CLIENT_SECRET (OAuth client credentials).
"""
import base64
import time
import os
import sys
import urllib.parse
from pathlib import Path

import httpx
from dotenv import dotenv_values
from phenoml import PhenomlClient

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / ".state"  # gitignored; seed plan/result artifacts land here

# Every resource this demo writes carries a tag from this system so it can be
# found (and deleted) without ambiguity. SEED_TAG marks synthetic source data,
# EXTRACT_TAG marks resources lang2fhir derived from the notes, and each
# extracted resource also carries a "doc-<DocumentReference.id>" tag linking it
# back to the note it came from (that tag doubles as the idempotency check).
TAG_SYSTEM = "https://phenoml.com/demos/glp1"
SEED_TAG = "glp1-demo-seed"
EXTRACT_TAG = "lang2fhir-extracted"

RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"

# The three GLP-1 products this demo revolves around (RxNorm codes supplied by demo spec).
MEDS = {
    "zepbound": {
        "brand": "Zepbound",
        "generic": "tirzepatide",
        "rxnorm": "2734642",
        "display": "Zepbound 10 MG per 0.5 ML Auto-Injector (tirzepatide)",
        "dose_text": "10 mg (0.5 mL auto-injector)",
        "dose_mg": 10,
        "indication": "obesity",
    },
    "wegovy": {
        "brand": "Wegovy",
        "generic": "semaglutide",
        "rxnorm": "2554104",
        "display": "Wegovy 1.7 MG per 0.75 ML Auto-Injector (semaglutide)",
        "dose_text": "1.7 mg (0.75 mL auto-injector)",
        "dose_mg": 1.7,
        "indication": "obesity",
    },
    "ozempic": {
        "brand": "Ozempic",
        "generic": "semaglutide",
        "rxnorm": "1991311",
        "display": "Ozempic 2 MG dose Pen Injector (semaglutide)",
        "dose_text": "2 mg (pen injector)",
        "dose_mg": 2,
        "indication": "t2dm",
    },
}
GLP1_CODES = [m["rxnorm"] for m in MEDS.values()]


# ---------- config / auth -------------------------------------------------
def load_env() -> dict:
    env = dict(os.environ)  # real env vars are the base layer
    for p in (HERE.parent / ".env", HERE / ".env"):  # .env files override; local wins
        if p.exists():
            values = {k: (v or "").strip().strip('"').strip("'") for k, v in dotenv_values(p).items()}
            env.update({k: v for k, v in values.items() if v})  # blank .env lines never mask real values
    return env


def make_client(env: dict) -> PhenomlClient:
    cid, csec = env.get("PHENOML_CLIENT_ID"), env.get("PHENOML_CLIENT_SECRET")
    if not (cid and csec):
        sys.exit("Missing PHENOML_CLIENT_ID / PHENOML_CLIENT_SECRET — fill in glp1-fhir2omop/.env "
                 "(see .env.example).")
    kw = {
        # lang2fhir.create_multi and fhir2omop.create can run well past the default
        # timeout on big inputs; 300s keeps them from dying mid-call.
        "timeout": float(env.get("PHENOML_TIMEOUT", "300")),
        # No silent SDK auto-retry: a retried POST that half-succeeded would double-write
        # FHIR resources. retry() below is the one visible retry layer, used only on reads.
        "max_retries": 0,
    }
    if env.get("PHENOML_BASE_URL"):
        kw["base_url"] = env["PHENOML_BASE_URL"]
    return PhenomlClient(client_id=cid, client_secret=csec, **kw)


def resolve_provider(env: dict) -> str:
    pid = env.get("PHENOML_FHIR_PROVIDER_ID") or env.get("FHIR_PROVIDER_ID") or ""
    if not pid:
        sys.exit("Set PHENOML_FHIR_PROVIDER_ID in glp1-fhir2omop/.env (see .env.example).")
    return pid


# ---------- helpers -------------------------------------------------------
def as_dict(obj):
    """SDK response models are pydantic with snake_case attrs; FHIR + the frontend need
    camelCase JSON, so always dump with by_alias=True."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, list):
        return [as_dict(x) for x in obj]
    return obj


def retry(fn, *args, attempts=3, base=4, label="", **kwargs):
    """Retry transient transport errors on NON-mutating calls only (searches,
    lang2fhir, fhir2omop). Never wrap fhir.create with this."""
    for i in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except httpx.TransportError as e:
            if i == attempts:
                raise
            wait = base * i
            print(f"  [retry {i}/{attempts}] {label}: {type(e).__name__}; waiting {wait}s", flush=True)
            time.sleep(wait)


def tag(code: str) -> dict:
    return {"system": TAG_SYSTEM, "code": code}


def ref(resource_type: str, rid: str) -> dict:
    return {"reference": f"{resource_type}/{rid}"}


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(data: str) -> str:
    return base64.b64decode(data).decode("utf-8", errors="replace")


def patient_name(patient: dict) -> str:
    for n in patient.get("name") or []:
        if n.get("text"):
            return n["text"]
        parts = list(n.get("given") or []) + ([n["family"]] if n.get("family") else [])
        if parts:
            return " ".join(parts)
    return patient.get("id", "unknown")


def get_tag_codes(resource: dict) -> set:
    return {t.get("code") for t in (resource.get("meta") or {}).get("tag") or []
            if t.get("system") == TAG_SYSTEM}


# ---------- FHIR gateway wrappers -----------------------------------------
def fhir_search_page(client, provider_id: str, path: str, params: dict | None = None) -> dict:
    """One search request. Params go through the SDK's documented query-param escape
    hatch; the PhenoML gateway proxies them verbatim to the upstream FHIR server."""
    opts = {"additional_query_parameters": {k: str(v) for k, v in (params or {}).items()}} if params else None
    out = retry(client.fhir.search, label=f"search {path}",
                fhir_provider_id=provider_id, fhir_path=path, request_options=opts)
    return out or {}


def search_all(client, provider_id: str, resource_type: str, params: dict, max_pages: int = 30) -> list[dict]:
    """Search + follow Bundle next-links. Returns the entry resources across pages."""
    resources, qp = [], {k: str(v) for k, v in params.items()}
    for _ in range(max_pages):
        bundle = fhir_search_page(client, provider_id, resource_type, qp)
        resources.extend(e["resource"] for e in bundle.get("entry") or [] if e.get("resource"))
        nxt = next((l.get("url") for l in bundle.get("link") or [] if l.get("relation") == "next"), None)
        if not nxt:
            break
        # Re-issue the search with exactly the query the server put on the next link.
        qp = {k: v[-1] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(nxt).query).items()}
    return resources


def fhir_read(client, provider_id: str, resource_type: str, rid: str) -> dict:
    return fhir_search_page(client, provider_id, f"{resource_type}/{rid}") or {}


def fhir_create(client, provider_id: str, resource: dict) -> dict:
    """Create one resource; returns the server copy (with id). Deliberately NOT retried."""
    created = client.fhir.create(fhir_provider_id=provider_id,
                                 fhir_path=resource["resourceType"], request=resource)
    created = as_dict(created) or {}
    if not created.get("id"):
        raise RuntimeError(f"create {resource['resourceType']} returned no id: {str(created)[:300]}")
    return created


def fhir_delete(client, provider_id: str, resource_type: str, rid: str):
    client.fhir.delete(fhir_provider_id=provider_id, fhir_path=f"{resource_type}/{rid}")


def subject_id(resource: dict) -> str | None:
    r = ((resource.get("subject") or resource.get("patient") or {}).get("reference") or "")
    return r.split("/", 1)[1] if r.startswith("Patient/") else None

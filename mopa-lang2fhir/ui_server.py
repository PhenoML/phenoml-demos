#!/usr/bin/env python3
"""FastAPI backend for the MOPA Lang2FHIR demo."""
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from common import configured_provider, load_env, make_client
import pipeline
import profiles

EXTRACTIONS: dict[str, dict] = {}

app = FastAPI(title="MOPA Lang2FHIR demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractReq(BaseModel):
    report_text: str
    include_her2: bool = True
    her2_result: str = pipeline.DEFAULT_HER2
    her2_positive: bool = True


class IdReq(BaseModel):
    extraction_id: str


def _client():
    env = load_env()
    try:
        return make_client(env), env
    except Exception as exc:
        raise HTTPException(503, str(exc))


@app.get("/api/health")
def health():
    env = load_env()
    configured = bool(env.get("PHENOML_CLIENT_ID") and env.get("PHENOML_CLIENT_SECRET"))
    capability = False
    if configured:
        try:
            client = make_client(env)
            capability = callable(getattr(getattr(client, "lang2fhir", None), "upload_profile", None))
        except Exception:
            capability = False
    return {
        "configured": configured,
        "fhir_provider_id": configured_provider(env),
        "profile_upload_capable": capability,
    }


@app.get("/api/source-data")
def source_data():
    return pipeline.source_data()


@app.post("/api/extract")
def extract(req: ExtractReq):
    if not req.report_text.strip():
        raise HTTPException(400, "report_text is required")
    client, _env = _client()
    try:
        result = pipeline.extract(
            client,
            req.report_text,
            include_her2=req.include_her2,
            her2_result=req.her2_result,
            her2_positive=req.her2_positive,
        )
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {str(exc)[:400]}")

    extraction_id = uuid.uuid4().hex[:12]
    EXTRACTIONS[extraction_id] = result
    return {
        "extraction_id": extraction_id,
        "resources": result["resources"],
        "base_resources": result["base_resources"],
        "bundle": result["bundle"],
        "summary_bundle": result["summary_bundle"],
        "regimen": result["regimen"],
        "source_map": result["source_map"],
    }


@app.post("/api/summary")
def summary(req: IdReq):
    client, _env = _client()
    result = EXTRACTIONS.get(req.extraction_id)
    if not result:
        raise HTTPException(404, "unknown extraction_id; run extraction again")
    try:
        return pipeline.summarize(client, result["summary_bundle"])
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {str(exc)[:400]}")


@app.post("/api/fhir/write")
def fhir_write(req: IdReq):
    client, env = _client()
    result = EXTRACTIONS.get(req.extraction_id)
    if not result:
        raise HTTPException(404, "unknown extraction_id; run extraction again")
    if not configured_provider(env):
        raise HTTPException(400, "PHENOML_FHIR_PROVIDER_ID is required in mopa-lang2fhir/.env")
    try:
        return pipeline.write_bundle(client, env, result["bundle"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"{type(exc).__name__}: {str(exc)[:400]}")


@app.get("/api/profiles")
def profile_list():
    return {"profiles": profiles.list_profiles()}


@app.post("/api/profiles/upload")
def profile_upload():
    client, _env = _client()
    return profiles.upload_profiles(client)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ui_server:app", host="127.0.0.1", port=8002, reload=True)

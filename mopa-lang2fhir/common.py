#!/usr/bin/env python3
"""Shared helpers for the MOPA Lang2FHIR demo."""
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values
from phenoml import PhenomlClient

HERE = Path(__file__).resolve().parent
SOURCE_DEMO = HERE.parent / "mopa-breast-pa"


def load_env() -> dict:
    env = dict(os.environ)
    for path in (HERE.parent / ".env", HERE / ".env"):
        if path.exists():
            env.update({
                k: (v or "").strip().strip('"').strip("'")
                for k, v in dotenv_values(path).items()
            })
    return env


def make_client(env: dict) -> PhenomlClient:
    cid = env.get("PHENOML_CLIENT_ID")
    secret = env.get("PHENOML_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("Set PHENOML_CLIENT_ID and PHENOML_CLIENT_SECRET in mopa-lang2fhir/.env")

    kw = {"timeout": float(env.get("PHENOML_TIMEOUT", "300")), "max_retries": 0}
    if env.get("PHENOML_BASE_URL"):
        kw["base_url"] = env["PHENOML_BASE_URL"]
    return PhenomlClient(client_id=cid, client_secret=secret, **kw)


def configured_provider(env: dict) -> str | None:
    value = (env.get("PHENOML_FHIR_PROVIDER_ID") or "").strip()
    if not value or value == "your_fhir_provider_uuid_here":
        return None
    return value


def as_dict(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, list):
        return [as_dict(x) for x in obj]
    return obj


def retry(fn, *args, attempts=3, base=4, label="", **kwargs):
    for i in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except httpx.TransportError:
            if i == attempts:
                raise
            time.sleep(base * i)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())

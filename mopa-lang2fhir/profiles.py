#!/usr/bin/env python3
"""Local OncoHealth profile registry and optional Lang2FHIR upload."""
from pathlib import Path
import json

from common import HERE, as_dict, read_json

PROFILE_DIR = HERE / "profiles"


def list_profiles() -> list[dict]:
    profiles = []
    for path in sorted(PROFILE_DIR.glob("*.json")):
        try:
            data = read_json(path)
            ok = data.get("resourceType") == "StructureDefinition"
            profiles.append({
                "file": path.name,
                "id": data.get("id"),
                "url": data.get("url"),
                "name": data.get("name"),
                "type": data.get("type"),
                "valid": ok,
                "error": None if ok else "resourceType must be StructureDefinition",
            })
        except Exception as exc:
            profiles.append({
                "file": path.name,
                "id": None,
                "url": None,
                "name": None,
                "type": None,
                "valid": False,
                "error": f"{type(exc).__name__}: {str(exc)[:180]}",
            })
    return profiles


def upload_profiles(client) -> dict:
    upload = getattr(getattr(client, "lang2fhir", None), "upload_profile", None)
    if not callable(upload):
        return {
            "ok": False,
            "message": "client.lang2fhir.upload_profile is not available in this SDK",
            "results": [],
        }

    results = []
    for path in sorted(PROFILE_DIR.glob("*.json")):
        try:
            profile = read_json(path)
            if profile.get("resourceType") != "StructureDefinition":
                raise ValueError("resourceType must be StructureDefinition")
            try:
                resp = upload(profile=json.dumps(profile))
            except TypeError:
                resp = upload(json.dumps(profile))
            results.append({"file": path.name, "ok": True, "response": as_dict(resp)})
        except Exception as exc:
            results.append({"file": path.name, "ok": False,
                            "error": f"{type(exc).__name__}: {str(exc)[:300]}"})

    return {
        "ok": bool(results) and all(item["ok"] for item in results),
        "message": "upload attempted",
        "results": results,
    }

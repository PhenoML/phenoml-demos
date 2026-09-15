#!/usr/bin/env python3
"""GLP-1 Cohort Studio — demo app over the seeded synthetic data.

What it does:
  1. Lists the cohort: every patient with a MedicationRequest for one of the demo
     GLP-1 RxNorm codes, plus their diagnoses, progress notes, and anything
     lang2fhir has already extracted.
  2. Runs lang2fhir (create_multi) over selected progress-note DocumentReferences,
     keeps the extracted Conditions/Observations, repoints them at the real
     Patient/Encounter, tags them, and stores them back on the same FHIR provider.
  3. Runs fhir2omop over the selected patients' FHIR data and renders the OMOP
     CDM rows (person, drug_exposure, condition_occurrence, ...) with mappings.
Bonus: natural-language cohort selection via client.cohort.analyze.

Run:  python app.py   (serves http://localhost:8017)
"""
import os
import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from common import (HERE, MEDS, GLP1_CODES, SEED_TAG, EXTRACT_TAG, TAG_SYSTEM, RXNORM,
                    load_env, make_client, resolve_provider, as_dict, retry, tag, ref,
                    unb64, patient_name, get_tag_codes, search_all, fhir_read,
                    fhir_create, subject_id)

ENV = load_env()
CLIENT = make_client(ENV)
PROVIDER = resolve_provider(ENV)
EXTRACT_CONCURRENCY = int(ENV.get("EXTRACT_CONCURRENCY", "4"))

app = FastAPI(title="GLP-1 Cohort Studio")

# ---------- tiny in-memory job registry (single-process demo server) --------
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def new_job(kind: str, total: int) -> dict:
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "running",
           "total": total, "done": 0, "log": [], "result": None, "error": None}
    with JOBS_LOCK:
        JOBS[job["id"]] = job
    return job


def job_log(job, msg):
    with JOBS_LOCK:
        job["log"].append(msg)


def job_step(job, msg=None):
    with JOBS_LOCK:
        job["done"] += 1
        if msg:
            job["log"].append(msg)


# ---------- cohort ----------------------------------------------------------
def code_label(r: dict, fallback: str = "resource") -> str:
    """Human label for a coded resource; codings may lack display and code.text may be absent."""
    code = r.get("code") or {}
    return (code.get("text")
            or next((c.get("display") for c in code.get("coding") or [] if c.get("display")), None)
            or next((c.get("code") for c in code.get("coding") or [] if c.get("code")), None)
            or fallback)


def med_of(mr: dict) -> dict | None:
    for c in (mr.get("medicationCodeableConcept") or {}).get("coding") or []:
        for key, m in MEDS.items():
            if c.get("code") == m["rxnorm"]:
                return {"key": key, "brand": m["brand"], "rxnorm": m["rxnorm"]}
    return None


@app.get("/api/config")
def config():
    return {"base_url": ENV.get("PHENOML_BASE_URL"), "provider_id": PROVIDER,
            "meds": [{"key": k, "brand": m["brand"], "rxnorm": m["rxnorm"],
                      "indication": m["indication"]} for k, m in MEDS.items()]}


@app.get("/api/cohort")
def cohort():
    medreqs = search_all(CLIENT, PROVIDER, "MedicationRequest",
                         {"code": ",".join(GLP1_CODES), "_count": 200})
    by_patient: dict[str, dict] = {}
    for mr in medreqs:
        pid, med = subject_id(mr), med_of(mr)
        if not pid or not med:
            continue
        row = by_patient.setdefault(pid, {"patient_id": pid, "meds": [], "diagnoses": [],
                                          "notes": [], "extracted": []})
        if med["rxnorm"] not in {m["rxnorm"] for m in row["meds"]}:
            row["meds"].append({**med, "authoredOn": mr.get("authoredOn")})

    if not by_patient:
        return {"patients": [], "hint": "No GLP-1 MedicationRequests found — run seed_glp1_data.py first."}

    # Patient names in chunked _id searches (one call per 30 patients, not per patient).
    pids = list(by_patient)
    for i in range(0, len(pids), 30):
        for p in search_all(CLIENT, PROVIDER, "Patient",
                            {"_id": ",".join(pids[i:i + 30]), "_count": 100}):
            row = by_patient.get(p["id"])
            if row is not None:
                row["name"] = patient_name(p)
                row["birthDate"] = p.get("birthDate")

    # Demo-tagged clinical context, three searches total (not per patient).
    for c in search_all(CLIENT, PROVIDER, "Condition", {"_tag": f"{TAG_SYSTEM}|{SEED_TAG}", "_count": 500}):
        row = by_patient.get(subject_id(c) or "")
        if row is not None:
            row["diagnoses"].append((c.get("code") or {}).get("text") or "condition")

    for d in search_all(CLIENT, PROVIDER, "DocumentReference", {"_tag": f"{TAG_SYSTEM}|{SEED_TAG}", "_count": 500}):
        row = by_patient.get(subject_id(d) or "")
        if row is None:
            continue
        tags = get_tag_codes(d)
        row["notes"].append({
            "id": d["id"], "title": d.get("description") or "progress note",
            "date": d.get("date"), "kind": "followup" if "note-followup" in tags else "initial",
        })

    for rtype in ("Condition", "Observation"):
        for r in search_all(CLIENT, PROVIDER, rtype, {"_tag": f"{TAG_SYSTEM}|{EXTRACT_TAG}", "_count": 500}):
            row = by_patient.get(subject_id(r) or "")
            if row is None:
                continue
            doc = next((t[4:] for t in get_tag_codes(r) if t.startswith("doc-")), None)
            row["extracted"].append({"type": rtype, "id": r["id"],
                                     "label": code_label(r, rtype), "doc_id": doc})

    patients = sorted(by_patient.values(), key=lambda r: (r.get("name") or "", r["patient_id"]))
    for row in patients:
        row.setdefault("name", row["patient_id"])
        row["notes"].sort(key=lambda n: n.get("date") or "")
        row["extracted_doc_ids"] = sorted({e["doc_id"] for e in row["extracted"] if e["doc_id"]})
    return {"patients": patients}


@app.get("/api/notes/{doc_id}")
def note_detail(doc_id: str):
    d = fhir_read(CLIENT, PROVIDER, "DocumentReference", doc_id)
    if d.get("resourceType") != "DocumentReference":
        raise HTTPException(404, f"DocumentReference/{doc_id} not found")
    att = (d.get("content") or [{}])[0].get("attachment") or {}
    extracted = []
    for rtype in ("Condition", "Observation"):
        for r in search_all(CLIENT, PROVIDER, rtype,
                            {"_tag": f"{TAG_SYSTEM}|doc-{doc_id}", "_count": 100}):
            extracted.append({"type": rtype, "id": r["id"], "label": code_label(r, rtype),
                              "codings": (r.get("code") or {}).get("coding") or []})
    return {"id": doc_id, "title": d.get("description"), "date": d.get("date"),
            "patient": (d.get("subject") or {}).get("reference"),
            "kind": "followup" if "note-followup" in get_tag_codes(d) else "initial",
            "text": unb64(att["data"]) if att.get("data") else "(no inline text)",
            "extracted": extracted}


# ---------- lang2fhir extraction ---------------------------------------------
class ExtractReq(BaseModel):
    doc_ids: list[str]
    force: bool = False


def already_extracted(doc_id: str) -> bool:
    for rtype in ("Condition", "Observation"):
        if search_all(CLIENT, PROVIDER, rtype,
                      {"_tag": f"{TAG_SYSTEM}|doc-{doc_id}", "_count": 1}, max_pages=1):
            return True
    return False


KEEP_TYPES = {"Condition", "Observation"}  # meds/encounters/patients would duplicate seeded data


def extract_one(job, doc_id: str, force: bool) -> dict:
    doc = fhir_read(CLIENT, PROVIDER, "DocumentReference", doc_id)
    pid = subject_id(doc)
    att = (doc.get("content") or [{}])[0].get("attachment") or {}
    if not (pid and att.get("data")):
        return {"doc_id": doc_id, "status": "error", "error": "no subject or inline note text"}
    if not force and already_extracted(doc_id):
        return {"doc_id": doc_id, "patient_id": pid, "status": "skipped",
                "error": "already extracted (use force to redo)"}

    note_date = (doc.get("date") or "")[:10]
    enc_ref = ((doc.get("context") or {}).get("encounter") or [{}])[0].get("reference")

    resp = as_dict(retry(CLIENT.lang2fhir.create_multi, label=f"create_multi {doc_id}",
                         text=unb64(att["data"]), version="R4"))
    entries = ((resp or {}).get("bundle") or {}).get("entry") or []
    created, seen = [], set()
    for e in entries:
        r = e.get("resource") or {}
        if r.get("resourceType") not in KEEP_TYPES:
            continue
        # lang2fhir stamps a placeholder subject — OVERWRITE it or the resource lands
        # orphaned on the server (present, but invisible to patient-scoped searches).
        r.pop("id", None)
        r["subject"] = ref("Patient", pid)
        r["meta"] = {"tag": [tag(EXTRACT_TAG), tag(f"doc-{doc_id}")]}
        if enc_ref:
            r["encounter"] = {"reference": enc_ref}
        if r["resourceType"] == "Condition":
            r.setdefault("recordedDate", note_date)
            r.setdefault("onsetDateTime", note_date)
        else:
            r.setdefault("status", "final")
            r.setdefault("effectiveDateTime", note_date)
        label = code_label(r, r["resourceType"])
        key = (r["resourceType"], label.lower())
        if key in seen:  # create_multi occasionally repeats a finding
            continue
        seen.add(key)
        stored = fhir_create(CLIENT, PROVIDER, r)
        created.append({"type": stored["resourceType"], "id": stored["id"], "label": label})
    return {"doc_id": doc_id, "patient_id": pid, "status": "created", "created": created,
            "note_kind": "followup" if "note-followup" in get_tag_codes(doc) else "initial"}


def run_extract_job(job, doc_ids, force):
    results = []
    try:
        with ThreadPoolExecutor(max_workers=EXTRACT_CONCURRENCY) as pool:
            futures = {pool.submit(extract_one, job, d, force): d for d in doc_ids}
            for fut in as_completed(futures):
                doc_id = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    res = {"doc_id": doc_id, "status": "error",
                           "error": f"{type(e).__name__}: {str(e)[:200]}"}
                results.append(res)
                labels = ", ".join(c["label"] for c in res.get("created") or []) or res.get("error", "")
                job_step(job, f"[{res['status']}] note {doc_id}: {labels or 'no new structured findings'}")
        with JOBS_LOCK:
            job["status"] = "done"
            job["result"] = {"results": results,
                             "created_total": sum(len(r.get("created") or []) for r in results)}
    except Exception as e:
        with JOBS_LOCK:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {str(e)[:300]}"


@app.post("/api/extract")
def extract(req: ExtractReq):
    if not req.doc_ids:
        raise HTTPException(400, "doc_ids is empty")
    job = new_job("lang2fhir", total=len(req.doc_ids))
    threading.Thread(target=run_extract_job, args=(job, req.doc_ids, req.force), daemon=True).start()
    return {"job_id": job["id"]}


# ---------- fhir2omop ---------------------------------------------------------
class OmopReq(BaseModel):
    patient_ids: list[str]


def run_omop_job(job, patient_ids):
    try:
        want = set(patient_ids)
        resources = []
        for i in range(0, len(patient_ids), 30):
            resources += search_all(CLIENT, PROVIDER, "Patient",
                                    {"_id": ",".join(patient_ids[i:i + 30]), "_count": 100})
        job_step(job, f"fetched {len(resources)} Patient resources")

        for rtype in ("Condition", "MedicationRequest", "Encounter", "Observation"):
            found, seen_ids = [], set()
            for tcode in (SEED_TAG, EXTRACT_TAG):
                for r in search_all(CLIENT, PROVIDER, rtype,
                                    {"_tag": f"{TAG_SYSTEM}|{tcode}", "_count": 500}):
                    if r["id"] not in seen_ids and subject_id(r) in want:
                        seen_ids.add(r["id"])
                        found.append(r)
            resources += found
            job_step(job, f"fetched {len(found)} {rtype} resources")

        bundle = {"resourceType": "Bundle", "type": "collection",
                  "entry": [{"resource": r} for r in resources]}
        job_log(job, f"running fhir2omop on {len(resources)} resources ...")
        resp = as_dict(retry(CLIENT.fhir2omop.create, label="fhir2omop",
                             fhir_resources=bundle))
        job_step(job, "fhir2omop returned")

        tables = {k: v for k, v in (resp.get("tables") or {}).items() if v}
        mappings = resp.get("mappings") or []
        status_counts = Counter()
        for m in mappings:
            status_counts[str(m.get("mapping_status") or "UNKNOWN").upper()] += 1
        with JOBS_LOCK:
            job["status"] = "done"
            job["result"] = {
                "tables": tables,
                "mappings": mappings,
                "dropped": resp.get("dropped") or [],
                "summary": resp.get("summary"),
                "vocab_version": resp.get("vocab_version"),
                "stats": {"resources_sent": len(resources),
                          "patients": len(patient_ids),
                          "rows": {k: len(v) for k, v in tables.items()},
                          "mapping_status": dict(status_counts)},
            }
    except Exception as e:
        with JOBS_LOCK:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {str(e)[:300]}"


@app.post("/api/omop")
def omop(req: OmopReq):
    if not req.patient_ids:
        raise HTTPException(400, "patient_ids is empty")
    job = new_job("fhir2omop", total=6)  # 1 patient fetch + 4 type fetches + the transform
    threading.Thread(target=run_omop_job, args=(job, req.patient_ids), daemon=True).start()
    return {"job_id": job["id"]}


# ---------- natural-language cohort (bonus: client.cohort.analyze) -----------
class CohortReq(BaseModel):
    text: str


@app.post("/api/cohort/analyze")
def cohort_analyze(req: CohortReq):
    import urllib.parse
    resp = as_dict(retry(CLIENT.cohort.analyze, label="cohort.analyze", text=req.text))
    queries, include_sets, exclude_sets = [], [], []
    for q in resp.get("queries") or []:
        rtype, raw = q.get("resource_type"), (q.get("search_params") or "").lstrip("?")
        info = {"concept": q.get("concept"), "resource_type": rtype,
                "search_params": raw, "exclude": bool(q.get("exclude"))}
        try:
            params = {k: v[-1] for k, v in urllib.parse.parse_qs(raw).items()}
            params.setdefault("_count", "200")
            found = search_all(CLIENT, PROVIDER, rtype, params, max_pages=5)
            pids = {r["id"] for r in found} if rtype == "Patient" else \
                   {subject_id(r) for r in found if subject_id(r)}
            info["matched_patients"] = len(pids)
            (exclude_sets if info["exclude"] else include_sets).append(pids)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        queries.append(info)
    selected = set.intersection(*include_sets) if include_sets else set()
    for ex in exclude_sets:
        selected -= ex
    return {"message": resp.get("message"), "queries": queries,
            "patient_ids": sorted(selected)}


@app.get("/api/jobs/{job_id}")
def job_state(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "unknown job")
        return dict(job)


app.mount("/", StaticFiles(directory=Path(HERE, "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8017")))

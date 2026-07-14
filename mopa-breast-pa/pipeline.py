#!/usr/bin/env python3
"""Return-based intake + readiness pipeline for the MOPA breast-cancer prior-auth demo.

This is the single source of truth for the Layer 1 work that used to live inline in
step1_intake.py and step1_5_readiness.py: pathology report -> mCODE FHIR (lang2fhir) -> validated
codes with citations (construe) -> the TH RequestGroup -> IPS -> EHR write-back, plus assembling the
resolved-HER2 Observation. Every function RETURNS data (no prints, no .state); the callers decide
how to surface it:

  - the CLI step scripts import these and keep their own banners/prints (course narrative),
  - the web backend (ui_server.py) calls run_intake() / build_her2_observation() and serves JSON.

The judgment side (DataRequirement gap-check, the UM-9 agent, the CDS Hooks envelope) is NOT here:
cds_hooks_server/evaluate.py already owns it framework-free and both paths reuse it unchanged.
"""
import copy, json, uuid
from pathlib import Path

from common import as_dict, retry

HERE = Path(__file__).resolve().parent
LOINC, SNOMED = "http://loinc.org", "http://snomed.info/sct"

# The documented, definitive mCODE elements we structure at intake. HER2 is deliberately absent:
# it is equivocal (IHC 2+, ISH pending) in the report, so it is the gap the readiness step closes.
# (spec = resource-profile, code system, code, display, source text, definitive value)
CHART_SPECS = [
    ("condition-encounter-diagnosis", SNOMED, "254837009", "Malignant neoplasm of breast",
     "Invasive ductal carcinoma of the right breast, Nottingham histologic grade 2.", None),
    ("observation-clinical-result", LOINC, "21908-9", "Stage group.clinical Cancer",
     "Cancer clinical stage group: Stage IIB (T2 N1 M0), AJCC 8th edition.", "Stage IIB"),
    ("observation-lab", LOINC, "85337-4",
     "Estrogen receptor Ag [Presence] in Breast cancer specimen by Immune stain",
     "Estrogen receptor (ER) status by immunohistochemistry: negative, 0% nuclear staining.",
     "Negative 0%"),
    ("observation-lab", LOINC, "85339-0",
     "Progesterone receptor Ag [Presence] in Breast cancer specimen by Immune stain",
     "Progesterone receptor (PR) status by immunohistochemistry: negative, 0% nuclear staining.",
     "Negative 0%"),
    ("observation-clinical-result", LOINC, "89247-1", "ECOG performance status",
     "ECOG performance status: 0 (fully active).", "0 (fully active)"),
]

# Construe validates codes WITH citations (the exact text spans justifying each code). Guarded per
# system: an instance may not enable every code system, and a missing one must not abort intake.
CONSTRUE_JOBS = {
    "rxnorm": ("RXNORM", "Paclitaxel intravenous; trastuzumab intravenous."),
    "loinc": ("LOINC", "HER2 receptor status; estrogen receptor status; progesterone receptor "
                       "status in breast cancer specimen by immunohistochemistry."),
    "snomed": ("SNOMED_CT_US_LITE", "Invasive ductal carcinoma of breast; clinical stage IIB."),
}


# ---------- FHIR bundle helpers (moved here from step1_intake) ------------
def _entry(resource: dict) -> dict:
    """Wrap a resource as a FHIR transaction entry with a fresh bundle-local fullUrl."""
    return {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource,
            "request": {"method": "POST", "url": resource["resourceType"]}}


def _lang2fhir(client, resource, text, patient_full_url):
    """lang2fhir.create one resource from natural-language text, then repoint its subject at the
    patient's bundle-local fullUrl (lang2fhir stamps a placeholder subject; overwrite it)."""
    r = as_dict(retry(client.lang2fhir.create, label=f"lang2fhir.{resource}",
                      version="R4", resource=resource, text=text))
    r["subject"] = {"reference": patient_full_url}
    return r


def _stamp(resource, system, code, display, value=None):
    """Normalize a lang2fhir resource onto the identifying code (and a definitive value) the payer's
    DataRequirement keys on, so the downstream gap-check is deterministic (PhenoML's Layer 1 job)."""
    cc = resource.setdefault("code", {})
    codings = cc.setdefault("coding", [])
    if not any(c.get("system") == system and c.get("code") == code for c in codings):
        codings.append({"system": system, "code": code, "display": display})
    cc.setdefault("text", display)
    if value is not None:
        vcc = resource.get("valueCodeableConcept") or {}
        vcc["text"] = value
        resource["valueCodeableConcept"] = vcc
    return resource


# ---------- fine-grained intake steps (each RETURNS data) -----------------
def extract_bundle(client, report_text: str):
    """Pathology report -> FHIR transaction Bundle (lang2fhir.create_multi). Returns (bundle, resources)."""
    multi = retry(client.lang2fhir.create_multi, label="create_multi", text=report_text, version="R4")
    return as_dict(multi.bundle), as_dict(multi.resources)


def patient_full_url(bundle: dict) -> str:
    """The single Patient's bundle-local fullUrl. Raises ValueError if not exactly one (the IPS +
    EHR steps assume a single patient)."""
    patients = [e for e in bundle.get("entry", [])
                if e.get("resource", {}).get("resourceType") == "Patient"]
    if len(patients) != 1:
        raise ValueError(f"expected exactly 1 Patient in the bundle, found {len(patients)}")
    return patients[0]["fullUrl"]


def structure_chart(client, patient_url: str) -> list:
    """Structure the documented mCODE evidence elements as FHIR transaction entries (diagnosis,
    stage, ER, PR, ECOG). Deliberately omits HER2 (the gap). Returns a list of transaction entries."""
    entries = []
    for res, system, code, display, text, value in CHART_SPECS:
        r = _stamp(_lang2fhir(client, res, text, patient_url), system, code, display, value)
        entries.append(_entry(r))
    return entries


def validate_codes(client) -> dict:
    """Validate codes with citations (construe.codes.extract). Returns {system_key: [code dicts]};
    a code system the instance does not enable comes back as an empty list, never an exception."""
    from phenoml.construe import ExtractRequestSystem
    out = {}
    for key, (system, text) in CONSTRUE_JOBS.items():
        try:
            res = retry(client.construe.codes.extract, label=f"construe.{key}",
                        text=text, system=ExtractRequestSystem(name=system))
            out[key] = [as_dict(c) for c in (res.codes or [])]
        except Exception as e:
            out[key] = []
            out.setdefault("_errors", {})[key] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def assemble_regimen(client, patient_url: str):
    """The TH regimen as a RequestGroup binding two component-drug MedicationRequests. lang2fhir
    emits the drugs; the RequestGroup is hand-assembled from regimen_th.json (it is the unit of
    authorization). Returns (regimen dict, [rg_entry, pac_entry, tra_entry])."""
    paclitaxel = _lang2fhir(client, "medicationrequest",
        "Paclitaxel 80 mg/m2 intravenous, weekly, adjuvant therapy for breast cancer.", patient_url)
    trastuzumab = _lang2fhir(client, "medicationrequest",
        "Trastuzumab intravenous, weekly, HER2-targeted adjuvant therapy for breast cancer.", patient_url)
    pac_entry, tra_entry = _entry(paclitaxel), _entry(trastuzumab)

    regimen = json.loads((HERE / "regimen_th.json").read_text())
    regimen["subject"] = {"reference": patient_url}
    regimen["action"][0]["resource"] = {"reference": pac_entry["fullUrl"]}
    regimen["action"][1]["resource"] = {"reference": tra_entry["fullUrl"]}
    rg_entry = _entry(regimen)
    return regimen, [rg_entry, pac_entry, tra_entry]


def make_ips(client, bundle: dict) -> str:
    """International Patient Summary narrative (summary.create mode=ips)."""
    ips = retry(client.summary.create, label="summary.create", fhir_resources=bundle, mode="ips")
    return ips.summary or ""


def persist_chart(client, provider: str, bundle: dict, chart_resources: list, draft_order_entries: list):
    """Fold the Patient + structured evidence + drugs + RequestGroup into ONE transaction and write
    it (fhir.execute_bundle). Returns {"patient_id": str|None, "locations": [...], "ok": bool,
    "error": str|None}. Writing needs a dedicated instance; a read-only instance is reported, not
    raised, so the rest of the pipeline still runs on the in-memory chart."""
    tx_bundle = copy.deepcopy(bundle)
    tx_bundle["entry"].extend(chart_resources + draft_order_entries)
    try:
        resp = as_dict(client.fhir.execute_bundle(fhir_provider_id=provider, request=tx_bundle))
    except Exception as e:
        return {"patient_id": None, "locations": [], "ok": False,
                "error": f"{type(e).__name__}: {str(e)[:300]}"}
    locations, patient_id = [], None
    for e in resp.get("entry", []) or []:
        loc = (e.get("response") or {}).get("location") or ""
        if loc:
            locations.append(loc)
        if "Patient/" in loc and patient_id is None:
            patient_id = loc.split("Patient/")[1].split("/")[0]
    return {"patient_id": patient_id, "locations": locations, "ok": True, "error": None}


# ---------- readiness: assemble the resolved-HER2 Observation -------------
def build_her2_observation(client, her2_text: str, patient_url: str, positive: bool = True) -> dict:
    """Structure a resolved HER2 result as an observation-lab (lang2fhir), stamped onto the canonical
    HER2 LOINC with a definitive value so it satisfies the HER2 DataRequirement. Returns a
    transaction entry ({fullUrl, resource, request})."""
    obs = as_dict(retry(client.lang2fhir.create, label="lang2fhir.her2",
                        version="R4", resource="observation-lab", text=her2_text))
    obs["subject"] = {"reference": patient_url}
    obs.setdefault("code", {}).setdefault("coding", []).append(
        {"system": LOINC, "code": "85319-2",
         "display": "HER2 [Presence] in Breast cancer specimen by Immune stain"})
    obs["code"].setdefault("text", "HER2 [Presence] in Breast cancer specimen by Immune stain")
    obs["valueCodeableConcept"] = {"text": "Positive (HER2 amplified)" if positive
                                    else "Negative (HER2 not amplified)"}
    return {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": obs,
            "request": {"method": "POST", "url": "Observation"}}


# ---------- high-level composer (what the web backend calls) --------------
def run_intake(client, provider: str, report_text: str) -> dict:
    """Compose the full intake in one call and return every artifact the demo needs downstream:
    bundle, resources, chart_resources, patient_full_url, construe_codes, regimen_requestgroup,
    draft_order_entries, ips_text, and the EHR write result. The CLI step scripts call the
    fine-grained functions above so they can print between sub-steps; the server calls this."""
    bundle, resources = extract_bundle(client, report_text)
    p_url = patient_full_url(bundle)
    chart_resources = structure_chart(client, p_url)
    construe_codes = validate_codes(client)
    regimen, draft_order_entries = assemble_regimen(client, p_url)
    ips_text = make_ips(client, bundle)
    write = persist_chart(client, provider, bundle, chart_resources, draft_order_entries)
    return {
        "path_report_text": report_text,
        "bundle": bundle,
        "resources": resources,
        "patient_full_url": p_url,
        "chart_resources": chart_resources,
        "construe_codes": construe_codes,
        "regimen_requestgroup": regimen,
        "draft_order_entries": draft_order_entries,
        "ips_text": ips_text,
        "patient_id": write["patient_id"],
        "write": write,
    }

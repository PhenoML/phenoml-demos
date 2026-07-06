#!/usr/bin/env python3
"""Lang2FHIR extraction, Bundle assembly, summary, and FHIR Proxy write."""
import copy
import json
import uuid

from common import SOURCE_DEMO, as_dict, configured_provider, read_json, retry

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"

SAMPLE_REPORT = SOURCE_DEMO / "sample_path_report.txt"
REQUIREMENTS = SOURCE_DEMO / "mopa_requirements.json"
REGIMEN = SOURCE_DEMO / "regimen_th.json"

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

DEFAULT_HER2 = (
    "HER2 status by reflex in-situ hybridization (ISH): POSITIVE (HER2 gene amplified). "
    "Resolves the earlier equivocal IHC 2+ result."
)


def source_data() -> dict:
    requirements = read_json(REQUIREMENTS)
    regimen = read_json(REGIMEN)
    mapped = []
    for item in requirements.get("dataRequirement", []):
        codes = [c for cf in item.get("codeFilter", []) for c in cf.get("code", [])]
        label = codes[0].get("display") if codes else item["type"]
        mapped.append({
            "type": item["type"],
            "label": label,
            "code": codes[0].get("code") if codes else None,
            "source": "pathology report" if item["type"] != "RequestGroup" else "regimen template",
            "used": True,
        })
    return {
        "report_text": SAMPLE_REPORT.read_text(),
        "requirements": requirements,
        "mapped_requirements": mapped,
        "regimen_template": regimen,
        "artifacts": [
            {"name": "sample_path_report.txt", "use": "Lang2FHIR clinical text input", "used": True},
            {"name": "mopa_requirements.json", "use": "selects oncology facts for the Bundle", "used": True},
            {"name": "regimen_th.json", "use": "RequestGroup template for TH regimen", "used": True},
            {"name": "policy_um9_oncohealth.md", "use": "payer adjudication only", "used": False},
            {"name": "cds_hooks_server/", "use": "payer CDS Hooks exchange only", "used": False},
        ],
    }


def _entry(resource: dict) -> dict:
    return {
        "fullUrl": f"urn:uuid:{uuid.uuid4()}",
        "resource": resource,
        "request": {"method": "POST", "url": resource["resourceType"]},
    }


def _lang2fhir(client, resource: str, text: str, patient_url: str | None = None) -> dict:
    out = as_dict(retry(client.lang2fhir.create, label=f"lang2fhir.{resource}",
                       version="R4", resource=resource, text=text))
    if patient_url:
        out["subject"] = {"reference": patient_url}
    return out


def _stamp(resource: dict, system: str, code: str, display: str, value: str | None = None) -> dict:
    codeable = resource.setdefault("code", {})
    codings = codeable.setdefault("coding", [])
    if not any(c.get("system") == system and c.get("code") == code for c in codings):
        codings.append({"system": system, "code": code, "display": display})
    codeable.setdefault("text", display)
    if value is not None:
        resource["valueCodeableConcept"] = {"text": value}
    return resource


def patient_full_url(bundle: dict) -> str:
    patients = [
        e for e in bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") == "Patient"
    ]
    if len(patients) != 1:
        raise ValueError(f"expected exactly 1 Patient in Lang2FHIR bundle, found {len(patients)}")
    return patients[0]["fullUrl"]


def _structure_chart(client, patient_url: str) -> list[dict]:
    entries = []
    for resource, system, code, display, text, value in CHART_SPECS:
        item = _stamp(_lang2fhir(client, resource, text, patient_url), system, code, display, value)
        entries.append(_entry(item))
    return entries


def _her2_observation(client, patient_url: str, text: str, positive: bool) -> dict:
    obs = _lang2fhir(client, "observation-lab", text, patient_url)
    value = "Positive (HER2 amplified)" if positive else "Negative (HER2 not amplified)"
    obs = _stamp(obs, LOINC, "85319-2",
                 "HER2 [Presence] in Breast cancer specimen by Immune stain", value)
    return _entry(obs)


def _assemble_regimen(client, patient_url: str) -> tuple[dict, list[dict]]:
    paclitaxel = _lang2fhir(
        client,
        "medicationrequest",
        "Paclitaxel 80 mg/m2 intravenous, weekly, adjuvant therapy for breast cancer.",
        patient_url,
    )
    trastuzumab = _lang2fhir(
        client,
        "medicationrequest",
        "Trastuzumab intravenous, weekly, HER2-targeted adjuvant therapy for breast cancer.",
        patient_url,
    )
    pac_entry = _entry(paclitaxel)
    tra_entry = _entry(trastuzumab)

    regimen = read_json(REGIMEN)
    regimen["subject"] = {"reference": patient_url}
    regimen["meta"] = {
        "profile": ["https://pheno.ml/demo/oncohealth/StructureDefinition/oncohealth-regimen-requestgroup"]
    }
    regimen["action"][0]["resource"] = {"reference": pac_entry["fullUrl"]}
    regimen["action"][1]["resource"] = {"reference": tra_entry["fullUrl"]}
    rg_entry = _entry(regimen)
    return regimen, [rg_entry, pac_entry, tra_entry]


def _summary_bundle(transaction_bundle: dict) -> dict:
    bundle = copy.deepcopy(transaction_bundle)
    bundle["type"] = "collection"
    for entry in bundle.get("entry", []):
        entry.pop("request", None)
    return bundle


def extract(client, report_text: str, include_her2: bool = True,
            her2_result: str = DEFAULT_HER2, her2_positive: bool = True) -> dict:
    multi = retry(client.lang2fhir.create_multi, label="create_multi",
                  text=report_text, version="R4")
    base_bundle = as_dict(multi.bundle)
    extracted = as_dict(multi.resources)
    patient_url = patient_full_url(base_bundle)

    chart_entries = _structure_chart(client, patient_url)
    regimen, regimen_entries = _assemble_regimen(client, patient_url)
    her2_entry = _her2_observation(client, patient_url, her2_result, her2_positive) if include_her2 else None

    transaction = copy.deepcopy(base_bundle)
    transaction["type"] = "transaction"
    transaction["entry"].extend(chart_entries + regimen_entries + ([her2_entry] if her2_entry else []))

    selected_resources = [e["resource"] for e in chart_entries + regimen_entries]
    if her2_entry:
        selected_resources.append(her2_entry["resource"])

    return {
        "bundle": transaction,
        "summary_bundle": _summary_bundle(transaction),
        "resources": selected_resources,
        "base_resources": extracted,
        "regimen": regimen,
        "patient_full_url": patient_url,
        "source_map": source_data()["mapped_requirements"],
    }


def summarize(client, bundle: dict) -> dict:
    resp = retry(client.summary.create, label="summary.create", fhir_resources=bundle, mode="ips")
    return {"summary": getattr(resp, "summary", "") or as_dict(resp).get("summary", "")}


def write_bundle(client, env: dict, bundle: dict) -> dict:
    provider = configured_provider(env)
    if not provider:
        raise ValueError("PHENOML_FHIR_PROVIDER_ID is required in mopa-lang2fhir/.env")

    response = as_dict(client.fhir.execute_bundle(fhir_provider_id=provider, request=bundle))
    locations = []
    patient_id = None
    for entry in response.get("entry", []) or []:
        loc = (entry.get("response") or {}).get("location") or ""
        if loc:
            locations.append(loc)
        if "Patient/" in loc and patient_id is None:
            patient_id = loc.split("Patient/")[1].split("/")[0]
    return {
        "provider": provider,
        "locations": locations,
        "patient_id": patient_id,
        "response": response,
    }

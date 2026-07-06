#!/usr/bin/env python3
"""Step 1 - Intake & evidence  (MOPA breast-cancer prior-auth demo, PhenoML SDK v15).

Pathology report -> FHIR mCODE-shaped resources (lang2fhir) -> validated codes with citations
(construe) -> a RequestGroup that IS the ordered regimen (TH = paclitaxel + trastuzumab) ->
International Patient Summary -> write the chart back to the EHR in one transaction. Hands the
chart, the regimen, the codes, the IPS, and the patient id to the readiness step via .state/.

The deliberate gap: the path report documents diagnosis, stage, and ER/PR, but HER2 is equivocal
(IHC 2+, ISH pending), so no definitive HER2 is structured here. Step 1.5 detects and collects it.

Run:  .venv/bin/python step1_intake.py        (then step1_5_readiness.py, step2_cdshooks.py, ...)
"""
import copy, json, sys, uuid

from common import (HERE, load_env, make_client, resolve_provider, as_dict, parse_json,
                    banner, retry, cleanup, load_state, save_state, reset_state, fresh_requested)


def _entry(resource: dict) -> dict:
    """Wrap a resource as a FHIR transaction entry with a fresh bundle-local fullUrl."""
    return {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource,
            "request": {"method": "POST", "url": resource["resourceType"]}}


def _lang2fhir(client, resource, text, patient_full_url):
    """lang2fhir.create one resource from natural-language text, then repoint its subject at the
    patient's bundle-local fullUrl. lang2fhir stamps a placeholder subject; a plain setdefault
    would no-op (the key already exists), leaving the resource orphaned, so we overwrite it."""
    r = as_dict(retry(client.lang2fhir.create, label=f"lang2fhir.{resource}",
                      version="R4", resource=resource, text=text))
    r["subject"] = {"reference": patient_full_url}
    return r


def _stamp(resource, system, code, display, value=None):
    """Normalize a lang2fhir resource onto the identifying code (and a definitive value) the payer's
    DataRequirement keys on. lang2fhir codes from free text, so the exact LOINC/SNOMED it picks can
    differ from the Library's; stamping the canonical code is part of PhenoML's Layer 1 job (make the
    chart conform to the payer's required data) and makes the gap-check deterministic."""
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


def run(client, env, provider, state, created):
    # --- Step 1.1: pathology report -> FHIR bundle (lang2fhir.create_multi) ----
    banner("STEP 1.1  Pathology report -> FHIR bundle (lang2fhir.create_multi)")
    report = (HERE / "sample_path_report.txt").read_text()
    state["path_report_text"] = report
    if state.get("bundle") and state.get("chart_resources") is not None:
        print("(reusing cached chart from .state/ - re-run with --fresh to re-extract)")
        bundle = state["bundle"]
    else:
        multi = retry(client.lang2fhir.create_multi, label="create_multi", text=report, version="R4")
        bundle, extracted = as_dict(multi.bundle), as_dict(multi.resources)
        state["bundle"], state["resources"] = bundle, extracted
        print(f"extracted {len(bundle.get('entry', []))} resources:")
        for r in extracted or []:
            print(f"  - {r.get('resourceType')}: {r.get('description')}")

    patients = [e["resource"] for e in bundle.get("entry", [])
                if e.get("resource", {}).get("resourceType") == "Patient"]
    if len(patients) != 1:
        sys.exit(f"expected exactly 1 Patient in the bundle, found {len(patients)}; the IPS + EHR "
                 "steps assume a single patient. Re-run with --fresh to re-extract.")
    patient_full_url = next(e["fullUrl"] for e in bundle["entry"]
                            if e["resource"]["resourceType"] == "Patient")
    state["patient_full_url"] = patient_full_url

    # --- Step 1.2: structure the documented mCODE elements (lang2fhir.create) --
    banner("STEP 1.2  Structure the mCODE evidence elements (lang2fhir.create)")
    # We feed the *elements* of the IG's oncology profiles to lang2fhir as natural language and let
    # it return conformant base resources. We deliberately structure ONLY the documented, definitive
    # facts: diagnosis, stage, ER, PR, ECOG. HER2 is equivocal (IHC 2+, ISH pending) in the report,
    # so there is NO definitive HER2 element here - that is the gap the readiness step must close.
    # (Authoring the real OncologyLineOfTherapy / tumor-marker StructureDefinitions via
    # upload_profile is deferred; see the README.)
    LOINC, SNOMED = "http://loinc.org", "http://snomed.info/sct"
    chart_specs = [
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
    chart_resources = []
    for res, system, code, display, text, value in chart_specs:
        r = _stamp(_lang2fhir(client, res, text, patient_full_url), system, code, display, value)
        chart_resources.append(_entry(r))
        print(f"  + {r.get('resourceType')}: {r.get('code', {}).get('text')}")
    state["chart_resources"] = chart_resources

    # --- Step 1.3: validate codes with citations (construe.codes.extract) ------
    banner("STEP 1.3  Validate codes with citations (construe.codes.extract)")
    from phenoml.construe import ExtractRequestSystem
    # Construe returns codes with CITATIONS (the exact text spans that justify each code). We
    # validate three systems: RxNorm for the drugs, LOINC for the tumor-marker tests, SNOMED for
    # the stage/diagnosis. Each call is guarded: an instance may not enable every code system, and
    # a missing system must not abort intake.
    construe_jobs = {
        "rxnorm": ("RXNORM", "Paclitaxel intravenous; trastuzumab intravenous."),
        "loinc": ("LOINC", "HER2 receptor status; estrogen receptor status; progesterone receptor "
                            "status in breast cancer specimen by immunohistochemistry."),
        "snomed": ("SNOMED_CT_US_LITE", "Invasive ductal carcinoma of breast; clinical stage IIB."),
    }
    construe_codes = {}
    for key, (system, text) in construe_jobs.items():
        try:
            res = retry(client.construe.codes.extract, label=f"construe.{key}",
                        text=text, system=ExtractRequestSystem(name=system))
            codes = [as_dict(c) for c in (res.codes or [])]
        except Exception as e:
            codes = []
            print(f"  construe {system} skipped: {type(e).__name__}: {str(e)[:120]}")
        construe_codes[key] = codes
        for c in codes:
            cites = c.get("citations") or []
            cite = f'  cite="{(cites[0] or {}).get("text", "")}"' if cites else ""
            print(f"  [{system}] {c.get('code')} - {c.get('description')}{cite}")
    state["construe_codes"] = construe_codes

    # --- Step 1.4: assemble the regimen as a RequestGroup ---------------------
    banner("STEP 1.4  Assemble the regimen RequestGroup (TH = paclitaxel + trastuzumab)")
    # The component drugs come from lang2fhir (resource='medicationrequest'); the RequestGroup that
    # binds them into one orderable regimen is NOT something lang2fhir emits, so we hand-assemble it
    # from regimen_th.json. The regimen, not a single drug, is the unit of authorization: its
    # action[] references the two MedicationRequest fullUrls, and its extensions carry the regimen
    # intent (adjuvant), the line of therapy (1L), and the disease context (breast).
    paclitaxel = _lang2fhir(client, "medicationrequest",
        "Paclitaxel 80 mg/m2 intravenous, weekly, adjuvant therapy for breast cancer.", patient_full_url)
    trastuzumab = _lang2fhir(client, "medicationrequest",
        "Trastuzumab intravenous, weekly, HER2-targeted adjuvant therapy for breast cancer.", patient_full_url)
    pac_entry, tra_entry = _entry(paclitaxel), _entry(trastuzumab)

    regimen = json.loads((HERE / "regimen_th.json").read_text())
    regimen["subject"] = {"reference": patient_full_url}
    regimen["action"][0]["resource"] = {"reference": pac_entry["fullUrl"]}
    regimen["action"][1]["resource"] = {"reference": tra_entry["fullUrl"]}
    rg_entry = _entry(regimen)
    state["regimen_requestgroup"] = regimen
    # The draft orders the prescriber would carry into the CDS Hooks exchange (Step 2): the regimen
    # plus its component drugs.
    state["draft_order_entries"] = [rg_entry, pac_entry, tra_entry]
    print(f"  RequestGroup {rg_entry['fullUrl']} -> action: paclitaxel, trastuzumab")
    print(f"  extensions: regimen-intent (adjuvant), treatment-line (1L), disease-context (breast)")

    # --- Step 1.5: International Patient Summary (summary.create mode=ips) ------
    banner("STEP 1.5  International Patient Summary (summary.create mode=ips)")
    ips = retry(client.summary.create, label="summary.create", fhir_resources=bundle, mode="ips")
    ips_text = ips.summary or ""
    state["ips_text"] = ips_text
    print(ips_text[:1500])

    # --- Step 1.6: persist the full chart + regimen in ONE transaction ---------
    banner("STEP 1.6  Persist the chart + regimen (fhir.execute_bundle)")
    # Fold the Patient (from create_multi), the structured mCODE evidence, the two component drugs,
    # and the RequestGroup into one transaction. A single execute_bundle persists them interlinked;
    # the server assigns real ids and rewrites the urn:uuid references. (create_multi only EXTRACTS;
    # execute_bundle is what writes.) Writing needs a dedicated instance; on a shared/experiment
    # instance this logs a read-only notice and the rest of the pipeline still runs on the in-memory
    # chart.
    tx_bundle = copy.deepcopy(bundle)
    tx_bundle["entry"].extend(chart_resources + state["draft_order_entries"])
    patient_id = None
    try:
        resp = as_dict(client.fhir.execute_bundle(fhir_provider_id=provider, request=tx_bundle))
        for e in resp.get("entry", []) or []:
            loc = (e.get("response") or {}).get("location") or ""
            print(f"  created {loc}")
            if "Patient/" in loc and patient_id is None:
                patient_id = loc.split("Patient/")[1].split("/")[0]
        print(f"persisted {len(resp.get('entry', []) or [])} resources; Patient/{patient_id}")
    except Exception as e:
        print("execute_bundle failed (instance may be read-only):", type(e).__name__, str(e)[:300])
    state["patient_id"] = patient_id


if __name__ == "__main__":
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)
    if fresh_requested():
        reset_state()
    state, created = load_state(), {"agents": [], "prompts": []}
    try:
        run(client, env, provider, state, created)
        save_state(state)
        print("\nDONE.  Next: .venv/bin/python step1_5_readiness.py")
    finally:
        cleanup(client, created)

#!/usr/bin/env python3
"""Step 1 - Intake & evidence  (MOPA breast-cancer prior-auth demo, PhenoML SDK v15).

Pathology report -> FHIR mCODE-shaped resources (lang2fhir) -> validated codes with citations
(construe) -> a RequestGroup that IS the ordered regimen (TH = paclitaxel + trastuzumab) ->
International Patient Summary -> write the chart back to the EHR in one transaction. Hands the
chart, the regimen, the codes, the IPS, and the patient id to the readiness step via .state/.

The deliberate gap: the path report documents diagnosis, stage, and ER/PR, but HER2 is equivocal
(IHC 2+, ISH pending), so no definitive HER2 is structured here. Step 1.5 detects and collects it.

The extraction/structuring/write logic lives in pipeline.py (shared with the web backend); this
script keeps the banners and printed narrative so it still reads top-to-bottom as a course.

Run:  .venv/bin/python step1_intake.py        (then step1_5_readiness.py, step2_cdshooks.py, ...)
"""
from common import (load_env, make_client, resolve_provider, banner,
                    cleanup, load_state, save_state, reset_state, fresh_requested)
import pipeline


def run(client, env, provider, state, created):
    # --- Step 1.1: pathology report -> FHIR bundle (lang2fhir.create_multi) ----
    banner("STEP 1.1  Pathology report -> FHIR bundle (lang2fhir.create_multi)")
    report = (pipeline.HERE / "sample_path_report.txt").read_text()
    state["path_report_text"] = report
    if state.get("bundle") and state.get("chart_resources") is not None:
        print("(reusing cached chart from .state/ - re-run with --fresh to re-extract)")
        bundle = state["bundle"]
    else:
        bundle, extracted = pipeline.extract_bundle(client, report)
        state["bundle"], state["resources"] = bundle, extracted
        print(f"extracted {len(bundle.get('entry', []))} resources:")
        for r in extracted or []:
            print(f"  - {r.get('resourceType')}: {r.get('description')}")

    p_url = pipeline.patient_full_url(bundle)  # raises if not exactly one Patient
    state["patient_full_url"] = p_url

    # --- Step 1.2: structure the documented mCODE elements (lang2fhir.create) --
    banner("STEP 1.2  Structure the mCODE evidence elements (lang2fhir.create)")
    # We feed the *elements* of the IG's oncology profiles to lang2fhir as natural language and let
    # it return conformant base resources. We deliberately structure ONLY the documented, definitive
    # facts: diagnosis, stage, ER, PR, ECOG. HER2 is equivocal (IHC 2+, ISH pending), so there is NO
    # definitive HER2 element here - that is the gap the readiness step must close.
    chart_resources = pipeline.structure_chart(client, p_url)
    state["chart_resources"] = chart_resources
    for e in chart_resources:
        r = e["resource"]
        print(f"  + {r.get('resourceType')}: {r.get('code', {}).get('text')}")

    # --- Step 1.3: validate codes with citations (construe.codes.extract) ------
    banner("STEP 1.3  Validate codes with citations (construe.codes.extract)")
    construe_codes = pipeline.validate_codes(client)
    state["construe_codes"] = construe_codes
    for key, (system, _text) in pipeline.CONSTRUE_JOBS.items():
        err = (construe_codes.get("_errors") or {}).get(key)
        if err:
            print(f"  construe {system} skipped: {err}")
            continue
        for c in construe_codes.get(key, []):
            cites = c.get("citations") or []
            cite = f'  cite="{(cites[0] or {}).get("text", "")}"' if cites else ""
            print(f"  [{system}] {c.get('code')} - {c.get('description')}{cite}")

    # --- Step 1.4: assemble the regimen as a RequestGroup ---------------------
    banner("STEP 1.4  Assemble the regimen RequestGroup (TH = paclitaxel + trastuzumab)")
    # The component drugs come from lang2fhir; the RequestGroup that binds them into one orderable
    # regimen is hand-assembled from regimen_th.json. The regimen, not a single drug, is the unit of
    # authorization: its action[] references the two MedicationRequest fullUrls, and its extensions
    # carry the regimen intent (adjuvant), the line of therapy (1L), and the disease context (breast).
    regimen, draft_order_entries = pipeline.assemble_regimen(client, p_url)
    state["regimen_requestgroup"] = regimen
    state["draft_order_entries"] = draft_order_entries
    print(f"  RequestGroup {draft_order_entries[0]['fullUrl']} -> action: paclitaxel, trastuzumab")
    print(f"  extensions: regimen-intent (adjuvant), treatment-line (1L), disease-context (breast)")

    # --- Step 1.5: International Patient Summary (summary.create mode=ips) ------
    banner("STEP 1.5  International Patient Summary (summary.create mode=ips)")
    ips_text = pipeline.make_ips(client, bundle)
    state["ips_text"] = ips_text
    print(ips_text[:1500])

    # --- Step 1.6: persist the full chart + regimen in ONE transaction ---------
    banner("STEP 1.6  Persist the chart + regimen (fhir.execute_bundle)")
    # A single execute_bundle persists the Patient, structured evidence, drugs, and RequestGroup
    # interlinked; the server assigns real ids and rewrites the urn:uuid references. Writing needs a
    # dedicated instance; on a read-only instance this logs a notice and the pipeline continues on
    # the in-memory chart.
    write = pipeline.persist_chart(client, provider, bundle, chart_resources, draft_order_entries)
    for loc in write["locations"]:
        print(f"  created {loc}")
    if write["ok"]:
        print(f"persisted {len(write['locations'])} resources; Patient/{write['patient_id']}")
    else:
        print("execute_bundle failed (instance may be read-only):", write["error"])
    state["patient_id"] = write["patient_id"]


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

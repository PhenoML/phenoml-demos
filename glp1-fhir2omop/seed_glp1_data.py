#!/usr/bin/env python3
"""Seed synthetic GLP-1 data into the demo FHIR provider.

For 50 male patients already on the FHIR server:
  - 12 -> Zepbound 10 mg   (RxNorm 2734642), diagnosis: obesity
  - 12 -> Wegovy 1.7 mg    (RxNorm 2554104), diagnosis: obesity
  - 20 -> Ozempic 2 mg     (RxNorm 1991311), diagnosis: type 2 diabetes
  -  remainder: untouched controls
Each prescribed patient gets: indication Condition(s), an initiation Encounter +
progress-note DocumentReference, a MedicationRequest, and a follow-up Encounter +
progress-note DocumentReference. For 10% of the OZEMPIC patients (and only them),
the follow-up note narrative reports headaches and nausea — deliberately left
UNSTRUCTURED so the app can surface them later with lang2fhir.

Usage:
  python seed_glp1_data.py --check      # auth + provider smoke test, no writes
  python seed_glp1_data.py --dry-run    # build everything, print plan, write nothing
  python seed_glp1_data.py --yes        # seed for real (asks first without --yes)
  python seed_glp1_data.py --reset --yes  # delete everything this demo ever tagged
"""
import argparse
import json
import random
import sys
from datetime import date, timedelta

from common import (HERE, STATE_DIR, MEDS, SEED_TAG, EXTRACT_TAG, TAG_SYSTEM,
                    RXNORM, SNOMED, ICD10, LOINC,
                    load_env, make_client, resolve_provider, patient_name,
                    search_all, fhir_create, fhir_delete, tag, ref, b64, subject_id)

SEED = 42                      # deterministic assignment across runs
N_PATIENTS = 50
PLAN_COUNTS = {"zepbound": 12, "wegovy": 12, "ozempic": 20}   # rest = controls
AE_RATE = 0.10                 # share of OZEMPIC patients whose follow-up note reports headaches + nausea

DIAGNOSES = {
    "obesity": {
        "text": "Obesity",
        "coding": [{"system": SNOMED, "code": "414916001", "display": "Obesity (disorder)"},
                   {"system": ICD10, "code": "E66.9", "display": "Obesity, unspecified"}],
    },
    "morbid_obesity": {
        "text": "Morbid (severe) obesity",
        "coding": [{"system": SNOMED, "code": "238136002", "display": "Morbid obesity (disorder)"},
                   {"system": ICD10, "code": "E66.01", "display": "Morbid (severe) obesity due to excess calories"}],
    },
    "t2dm": {
        "text": "Type 2 diabetes mellitus",
        "coding": [{"system": SNOMED, "code": "44054006", "display": "Type 2 diabetes mellitus"},
                   {"system": ICD10, "code": "E11.9", "display": "Type 2 diabetes mellitus without complications"}],
    },
}


# ---------- note narratives -------------------------------------------------
def _vitals(rng, med_key):
    w = rng.randint(238, 322) if med_key != "ozempic" else rng.randint(196, 288)
    h = rng.randint(66, 75)
    bmi = round(703 * w / (h * h), 1)
    return {"weight": w, "height": h, "bmi": bmi,
            "bp": f"{rng.randint(118, 148)}/{rng.randint(72, 92)}", "hr": rng.randint(64, 88),
            "a1c": round(rng.uniform(7.6, 9.4), 1)}


def initial_note(name, pid, med, dx_texts, v, dos):
    m = MEDS[med]
    if m["indication"] == "t2dm":
        subj = (f"{name} is a male patient with type 2 diabetes mellitus on metformin 1000 mg twice daily "
                f"with suboptimal glycemic control (most recent hemoglobin A1c {v['a1c']}%). He reports "
                "adherence to oral therapy and no hypoglycemic episodes. No history of pancreatitis, "
                "medullary thyroid carcinoma, or MEN 2 syndrome.")
        assess = "\n".join(f"{i+1}. {t}" for i, t in enumerate(dx_texts))
        plan = (f"- Start {m['brand']} ({m['generic']}) with titration to {m['dose_text']} subcutaneously once weekly.\n"
                "- Continue metformin at current dose.\n"
                "- Injection technique education provided; sharps disposal reviewed.\n"
                "- Home glucose log; repeat labs at next visit.\n"
                "- Return to clinic in 4-6 weeks.")
        obj = (f"Weight: {v['weight']} lb   Height: {v['height']} in   BMI: {v['bmi']} kg/m2\n"
               f"BP: {v['bp']}   HR: {v['hr']}\nHemoglobin A1c: {v['a1c']}%")
        clinic = "ENDOCRINOLOGY / DIABETES CLINIC"
    else:
        subj = (f"{name} is a male patient presenting for medical weight management. Multiple prior "
                "structured attempts at lifestyle modification including calorie restriction and increased "
                "physical activity without sustained weight loss. No history of pancreatitis, medullary "
                "thyroid carcinoma, or MEN 2 syndrome.")
        assess = "\n".join(f"{i+1}. {t} — BMI {v['bmi']} kg/m2." for i, t in enumerate(dx_texts))
        plan = (f"- Start {m['brand']} ({m['generic']}) {m['dose_text']} subcutaneously once weekly.\n"
                "- Injection technique education provided; sharps disposal reviewed.\n"
                "- Continue lifestyle modification; nutrition referral placed.\n"
                "- Return to clinic in 4-6 weeks for dose assessment.")
        obj = (f"Weight: {v['weight']} lb   Height: {v['height']} in   BMI: {v['bmi']} kg/m2\n"
               f"BP: {v['bp']}   HR: {v['hr']}")
        clinic = "WEIGHT MANAGEMENT CLINIC"
    return (f"PROGRESS NOTE — {clinic}\n"
            f"Patient: {name} (FHIR ID {pid})\nDate of service: {dos}\nVisit type: Initial pharmacotherapy visit\n\n"
            f"SUBJECTIVE:\n{subj}\n\nOBJECTIVE:\n{obj}\n\nASSESSMENT:\n{assess}\n\nPLAN:\n{plan}\n")


def followup_note(name, pid, med, dx_texts, v, dos, weeks, adverse):
    m = MEDS[med]
    dw = v["dw"]
    if adverse:  # ozempic-only arm: headaches + nausea live ONLY in this narrative
        subj = (f"{name} returns for follow-up {weeks} weeks after starting {m['brand']} ({m['generic']}). "
                "Since initiation he reports recurrent headaches, occurring three to four times per week, "
                "frontal, moderate intensity, partially relieved with acetaminophen. He also reports "
                "persistent nausea, most pronounced for 24-48 hours after each weekly injection, with "
                "occasional early satiety. No vomiting, no abdominal pain radiating to the back. "
                "Adherent to weekly injections.")
        assess = "\n".join([f"1. {dx_texts[0]} — improving glycemic control on semaglutide."] +
                           [f"{i+2}. {t}" for i, t in enumerate(
                               ["Headache — new since starting semaglutide, suspect medication-related.",
                                "Nausea — likely GLP-1 receptor agonist gastrointestinal effect."])])
        plan = ("- Supportive care: hydration, smaller frequent meals.\n"
                "- Acetaminophen PRN headache; ondansetron 4 mg PO PRN nausea.\n"
                f"- Hold dose escalation of {m['brand']}; if symptoms persist at next visit, consider dose reduction.\n"
                "- Return to clinic in 4 weeks.")
    else:
        subj = (f"{name} returns for follow-up {weeks} weeks after starting {m['brand']} ({m['generic']}). "
                "Tolerating the medication well with no adverse effects reported. Adherent to weekly "
                "injections. Reports improved energy and reduced appetite.")
        assess = "\n".join(f"{i+1}. {t} — improving on {m['brand']}." for i, t in enumerate(dx_texts))
        plan = (f"- Continue {m['brand']} {m['dose_text']} subcutaneously once weekly.\n"
                "- Continue lifestyle modification.\n"
                "- Return to clinic in 3 months.")
    obj = (f"Weight: {v['weight'] - dw} lb (down {dw} lb from baseline)   BP: {v['bp']}   HR: {v['hr']}")
    if m["indication"] == "t2dm":
        obj += f"\nHome glucose log: fasting averages improved to {v['fg']} mg/dL"
    return (f"PROGRESS NOTE — FOLLOW-UP VISIT\n"
            f"Patient: {name} (FHIR ID {pid})\nDate of service: {dos}\nVisit type: Pharmacotherapy follow-up\n\n"
            f"SUBJECTIVE:\n{subj}\n\nOBJECTIVE:\n{obj}\n\nASSESSMENT:\n{assess}\n\nPLAN:\n{plan}\n")


# ---------- FHIR resource builders ------------------------------------------
def build_condition(pid, enc_id, dx, onset, recorded):
    return {
        "resourceType": "Condition",
        "meta": {"tag": [tag(SEED_TAG)]},
        "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                       "code": "active"}]},
        "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                           "code": "confirmed"}]},
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                  "code": "problem-list-item", "display": "Problem List Item"}]}],
        "code": {"coding": dx["coding"], "text": dx["text"]},
        "subject": ref("Patient", pid),
        "encounter": ref("Encounter", enc_id),
        "onsetDateTime": onset.isoformat(),
        "recordedDate": recorded.isoformat(),
    }


def build_encounter(pid, day, kind):
    t = ({"code": "185349003", "display": "Encounter for check up"} if kind == "initial"
         else {"code": "185389009", "display": "Follow-up visit"})
    return {
        "resourceType": "Encounter",
        "meta": {"tag": [tag(SEED_TAG)]},
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                  "code": "AMB", "display": "ambulatory"},
        "type": [{"coding": [{"system": SNOMED, **t}], "text": t["display"]}],
        "subject": ref("Patient", pid),
        "period": {"start": f"{day.isoformat()}T09:00:00Z", "end": f"{day.isoformat()}T09:30:00Z"},
    }


def build_medication_request(pid, med_key, enc_id, cond_ids, authored):
    m = MEDS[med_key]
    return {
        "resourceType": "MedicationRequest",
        "meta": {"tag": [tag(SEED_TAG)]},
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"system": RXNORM, "code": m["rxnorm"], "display": m["display"]}],
            "text": f"{m['brand']} {m['dose_text']}",
        },
        "subject": ref("Patient", pid),
        "encounter": ref("Encounter", enc_id),
        "authoredOn": authored.isoformat(),
        "reasonReference": [ref("Condition", cid) for cid in cond_ids],
        "dosageInstruction": [{
            "text": f"Inject {m['dose_text']} subcutaneously once weekly",
            "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "wk"}},
            "route": {"coding": [{"system": SNOMED, "code": "34206005", "display": "Subcutaneous route"}]},
            "doseAndRate": [{"doseQuantity": {"value": m["dose_mg"], "unit": "mg",
                                              "system": "http://unitsofmeasure.org", "code": "mg"}}],
        }],
        "dispenseRequest": {"numberOfRepeatsAllowed": 2,
                            "expectedSupplyDuration": {"value": 28, "unit": "days",
                                                       "system": "http://unitsofmeasure.org", "code": "d"}},
    }


def build_document_reference(pid, enc_id, day, kind, title, text):
    return {
        "resourceType": "DocumentReference",
        "meta": {"tag": [tag(SEED_TAG), tag(f"note-{kind}")]},
        "status": "current",
        "docStatus": "final",
        "type": {"coding": [{"system": LOINC, "code": "11506-3", "display": "Progress note"}],
                 "text": "Progress note"},
        "category": [{"coding": [{"system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                                  "code": "clinical-note", "display": "Clinical Note"}]}],
        "subject": ref("Patient", pid),
        "date": f"{day.isoformat()}T09:30:00Z",
        "description": title,
        "content": [{"attachment": {"contentType": "text/plain", "language": "en-US",
                                    "data": b64(text), "title": title,
                                    "creation": f"{day.isoformat()}T09:30:00Z"}}],
        "context": {"encounter": [ref("Encounter", enc_id)],
                    "period": {"start": f"{day.isoformat()}T09:00:00Z", "end": f"{day.isoformat()}T09:30:00Z"}},
    }


# ---------- planning ---------------------------------------------------------
def assign_meds(patients):
    """Deterministically assign meds to the fetched patients. Scales the plan down
    proportionally if the server returned fewer than N_PATIENTS males."""
    patients = sorted(patients, key=lambda p: p["id"])
    rng = random.Random(SEED)
    rng.shuffle(patients)
    counts = dict(PLAN_COUNTS)
    want = sum(counts.values())
    if len(patients) < want + 1:  # keep at least 1 control when scaling down
        scale = max(len(patients) - 1, 0) / want
        counts = {k: int(v * scale) for k, v in counts.items()}
    plan, i = [], 0
    for med_key, n in counts.items():
        for p in patients[i:i + n]:
            plan.append({"patient": p, "med": med_key, "adverse": False})
        i += n
    controls = patients[i:]
    oz = [row for row in plan if row["med"] == "ozempic"]
    n_ae = max(1, round(AE_RATE * len(oz))) if oz else 0
    for row in oz[:n_ae]:
        row["adverse"] = True
    return plan, controls


def build_patient_payload(row, today):
    """Everything to create for one patient, in dependency order, plus the note texts."""
    p, med_key, adverse = row["patient"], row["med"], row["adverse"]
    pid, name = p["id"], patient_name(p)
    rng = random.Random(f"{SEED}:{pid}")
    start = today - timedelta(days=rng.randint(60, 120))
    weeks = rng.randint(4, 8)
    fu_day = start + timedelta(weeks=weeks)
    v = _vitals(rng, med_key)
    v["dw"] = rng.randint(4, 14) if med_key != "ozempic" else rng.randint(3, 9)
    v["fg"] = rng.randint(108, 138)

    if med_key == "ozempic":
        dxs = [DIAGNOSES["t2dm"]] + ([DIAGNOSES["obesity"]] if rng.random() < 0.5 else [])
    else:
        dxs = [DIAGNOSES["morbid_obesity"] if rng.random() < 0.4 else DIAGNOSES["obesity"]]
    dx_texts = [d["text"] for d in dxs]

    onset = start - timedelta(days=rng.randint(90, 720))
    m = MEDS[med_key]
    return {
        "patient_id": pid, "name": name, "med": med_key, "adverse": adverse,
        "start": start, "fu_day": fu_day, "weeks": weeks, "dxs": dxs,
        "notes": {
            "initial": {"title": f"{m['brand']} initiation visit — progress note",
                        "day": start,
                        "text": initial_note(name, pid, med_key, dx_texts, v, start.isoformat())},
            "followup": {"title": f"{m['brand']} follow-up visit — progress note",
                         "day": fu_day,
                         "text": followup_note(name, pid, med_key, dx_texts, v, fu_day.isoformat(),
                                               weeks, adverse)},
        },
        "onset": onset,
    }


# ---------- execution ---------------------------------------------------------
def seed_one(client, provider, payload):
    pid = payload["patient_id"]
    created = []

    enc1 = fhir_create(client, provider, build_encounter(pid, payload["start"], "initial"))
    created.append(("Encounter", enc1["id"]))
    cond_ids = []
    for dx in payload["dxs"]:
        c = fhir_create(client, provider, build_condition(pid, enc1["id"], dx,
                                                          payload["onset"], payload["start"]))
        cond_ids.append(c["id"])
        created.append(("Condition", c["id"]))
    mr = fhir_create(client, provider, build_medication_request(pid, payload["med"], enc1["id"],
                                                                cond_ids, payload["start"]))
    created.append(("MedicationRequest", mr["id"]))
    n1 = payload["notes"]["initial"]
    d1 = fhir_create(client, provider, build_document_reference(pid, enc1["id"], n1["day"],
                                                                "initial", n1["title"], n1["text"]))
    created.append(("DocumentReference", d1["id"]))

    enc2 = fhir_create(client, provider, build_encounter(pid, payload["fu_day"], "followup"))
    created.append(("Encounter", enc2["id"]))
    n2 = payload["notes"]["followup"]
    d2 = fhir_create(client, provider, build_document_reference(pid, enc2["id"], n2["day"],
                                                                "followup", n2["title"], n2["text"]))
    created.append(("DocumentReference", d2["id"]))
    return created


def cmd_check(client, provider):
    provs = client.fhir_provider.list()
    provs = provs.model_dump(by_alias=True) if hasattr(provs, "model_dump") else provs
    names = {p.get("id"): p.get("name") for p in (provs or {}).get("fhir_providers", [])}
    print(f"[check] auth OK — {len(names)} FHIR provider(s) visible")
    print(f"[check] target provider {provider} -> {names.get(provider, 'NOT LISTED (check the id)')}")
    males = search_all(client, provider, "Patient", {"gender": "male", "_count": N_PATIENTS}, max_pages=1)
    print(f"[check] male patients on server (first page, _count={N_PATIENTS}): {len(males)}")
    for p in males[:3]:
        print(f"        e.g. {patient_name(p)}  ({p['id']})")


def cmd_reset(client, provider, yes):
    print("Deleting every resource tagged by this demo "
          f"(_tag {SEED_TAG} or {EXTRACT_TAG}) — patients themselves are never touched.")
    if not yes and input("Type 'delete' to continue: ").strip() != "delete":
        sys.exit("aborted")
    # DocumentReference first, then things that reference others, so nothing dangles mid-way.
    for rtype in ("DocumentReference", "MedicationRequest", "Observation", "Condition", "Encounter"):
        for tcode in (SEED_TAG, EXTRACT_TAG):
            found = search_all(client, provider, rtype, {"_tag": f"{TAG_SYSTEM}|{tcode}", "_count": 200})
            for r in found:
                try:
                    fhir_delete(client, provider, rtype, r["id"])
                    print(f"  deleted {rtype}/{r['id']}")
                except Exception as e:
                    print(f"  FAILED delete {rtype}/{r['id']}: {type(e).__name__}: {str(e)[:120]}")
    print("reset complete")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="auth/provider smoke test, no writes")
    ap.add_argument("--dry-run", action="store_true", help="plan + sample notes, no writes")
    ap.add_argument("--reset", action="store_true", help="delete all demo-tagged resources")
    ap.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    args = ap.parse_args()

    env = load_env()
    client = make_client(env)
    provider = resolve_provider(env)
    print(f"[env] base_url={env.get('PHENOML_BASE_URL')}  provider={provider}")

    if args.check:
        return cmd_check(client, provider)
    if args.reset:
        return cmd_reset(client, provider, args.yes)

    # Guard against double-seeding: the tag is the source of truth.
    existing = search_all(client, provider, "MedicationRequest",
                          {"_tag": f"{TAG_SYSTEM}|{SEED_TAG}", "_count": 1}, max_pages=1)
    if existing and not args.dry_run:
        sys.exit("Demo-tagged MedicationRequests already exist on this provider. "
                 "Run `python seed_glp1_data.py --reset --yes` first (or inspect via the app).")

    print(f"[1/3] fetching up to {N_PATIENTS} male patients ...")
    patients = search_all(client, provider, "Patient",
                          {"gender": "male", "_count": N_PATIENTS}, max_pages=1)[:N_PATIENTS]
    if not patients:
        sys.exit("No male patients found on this provider — is the provider id right?")
    print(f"      got {len(patients)}")

    plan, controls = assign_meds(patients)
    today = date.today()
    payloads = [build_patient_payload(row, today) for row in plan]
    n_ae = sum(1 for p in payloads if p["adverse"])
    by_med = {k: sum(1 for p in payloads if p["med"] == k) for k in MEDS}

    print(f"[2/3] plan: " + ", ".join(f"{v} {MEDS[k]['brand']}" for k, v in by_med.items()) +
          f", {len(controls)} controls; {n_ae} Ozempic patient(s) with headache+nausea follow-up notes")
    for p in payloads:
        if p["adverse"]:
            print(f"      AE arm: {p['name']} ({p['patient_id']})")

    if args.dry_run:
        sample_ok = next(p for p in payloads if not p["adverse"])
        sample_ae = next((p for p in payloads if p["adverse"]), None)
        print("\n----- sample initiation note -----\n" + sample_ok["notes"]["initial"]["text"])
        if sample_ae:
            print("----- sample ADVERSE-EVENT follow-up note (ozempic arm) -----\n" +
                  sample_ae["notes"]["followup"]["text"])
        STATE_DIR.mkdir(exist_ok=True)
        plan_file = STATE_DIR / "seed_plan.json"
        plan_file.write_text(json.dumps([{**{k: str(v) if isinstance(v, date) else v
                                             for k, v in p.items() if k != "dxs"},
                                          "dx": [d["text"] for d in p["dxs"]]} for p in payloads],
                                        indent=2, default=str))
        print(f"[dry-run] wrote plan to {plan_file.relative_to(HERE)} — nothing sent to FHIR")
        return

    if not args.yes and input(f"Create ~{len(payloads) * 6} resources on provider {provider}? [y/N] ").strip().lower() != "y":
        sys.exit("aborted")

    print(f"[3/3] creating resources ...")
    results, failures = [], []
    for i, p in enumerate(payloads, 1):
        try:
            created = seed_one(client, provider, p)
            results.append({"patient_id": p["patient_id"], "name": p["name"], "med": p["med"],
                            "adverse": p["adverse"],
                            "created": [f"{t}/{i_}" for t, i_ in created]})
            flag = "  [AE note]" if p["adverse"] else ""
            print(f"  {i:>2}/{len(payloads)}  {p['name']:<28} {MEDS[p['med']]['brand']:<9} "
                  f"+{len(created)} resources{flag}")
        except Exception as e:
            failures.append({"patient_id": p["patient_id"], "error": f"{type(e).__name__}: {str(e)[:200]}"})
            print(f"  {i:>2}/{len(payloads)}  {p['name']:<28} FAILED: {type(e).__name__}: {str(e)[:120]}")

    STATE_DIR.mkdir(exist_ok=True)
    out = {"provider": provider, "seeded": results, "failures": failures,
           "controls": [{"id": c["id"], "name": patient_name(c)} for c in controls]}
    (STATE_DIR / "seed_result.json").write_text(json.dumps(out, indent=2))
    total = sum(len(r["created"]) for r in results)
    print(f"\ndone: {total} resources across {len(results)} patients "
          f"({len(failures)} failures) — details in .state/seed_result.json")
    print("next: python app.py  (then open http://localhost:8017)")


if __name__ == "__main__":
    main()

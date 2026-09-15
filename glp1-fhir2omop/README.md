# GLP-1 Cohort Studio — lang2fhir + fhir2omop demo

Synthetic GLP-1 pharmacovigilance arc, end to end on one FHIR provider:

1. **Seed** — take 50 male patients already on the FHIR server and give most of them a
   synthetic GLP-1 story: an indication diagnosis, an initiation encounter + progress note,
   a `MedicationRequest`, and a follow-up encounter + progress note.

   | arm | RxNorm | patients | structured diagnosis |
   |---|---|---|---|
   | Zepbound 10 mg auto-injector | `2734642` | 12 | obesity / morbid obesity |
   | Wegovy 1.7 mg auto-injector | `2554104` | 12 | obesity / morbid obesity |
   | Ozempic 2 mg pen | `1991311` | 20 | type 2 diabetes (± obesity) |
   | controls (untouched) | — | ~6 | — |

   **The hook:** 10% of the *Ozempic* patients (2 of 20) report **headaches and nausea**
   in their follow-up visit note — narrative text only, nothing structured. Every other
   patient's follow-up says they tolerate the drug with no adverse effects.

2. **lang2fhir** — the app runs `lang2fhir.create_multi` over the progress-note
   `DocumentReference`s, keeps the extracted `Condition`/`Observation` resources,
   repoints them at the real `Patient`/`Encounter` (lang2fhir returns a placeholder
   subject), tags them, and writes them back to the same provider. The buried
   headache/nausea findings become structured, queryable data.

3. **fhir2omop** — select a cohort (checkboxes, one-click "everyone on a GLP-1", or a
   natural-language description via `cohort.analyze`) and map their FHIR data to OMOP
   CDM v5.4 rows: `person`, `visit_occurrence`, `condition_occurrence`, `drug_exposure`,
   `measurement`, `observation` — with concept mappings, dropped-resource accounting,
   and CSV export per table.

All demo writes carry a `meta.tag` from `https://phenoml.com/demos/glp1`
(`glp1-demo-seed` for seeded data, `lang2fhir-extracted` + `doc-<id>` for extractions),
so everything is discoverable and fully reversible. Patients themselves are never modified.

> Synthetic data for demo purposes only — no real patient information.

## Setup

```bash
cd glp1-fhir2omop
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Fill in the two credential lines in `.env` (already scaffolded; base URL and FHIR
provider id are preset):

```
PHENOML_CLIENT_ID=...
PHENOML_CLIENT_SECRET=...
```

## Run

```bash
python seed_glp1_data.py --check     # smoke test: auth, provider visible, male patient count
python seed_glp1_data.py --dry-run   # print the assignment plan + sample notes; writes nothing
python seed_glp1_data.py --yes       # create ~270 resources (44 patients x ~6 resources)

python app.py                        # then open http://localhost:8017
```

In the app:

1. **Select** the cohort (e.g. the Ozempic quick-select, or type
   `male patients on semaglutide` into the natural-language box).
2. **Run lang2fhir** on the follow-up notes — watch the two AE patients light up with
   extracted `Headache` / `Nausea` conditions while everyone else extracts clean.
   Click any row to read the raw notes (AE language highlighted) per patient.
3. **Run fhir2omop** — inspect/download the OMOP tables. The extracted AEs land in
   `condition_occurrence` next to the seeded diagnoses and `drug_exposure` rows.

Start over anytime:

```bash
python seed_glp1_data.py --reset --yes   # deletes every demo-tagged resource
```

## Files

| file | role |
|---|---|
| `common.py` | env/auth, client factory, FHIR search pagination, tag conventions |
| `seed_glp1_data.py` | synthetic-data seeder (`--check` / `--dry-run` / `--reset`) |
| `app.py` | FastAPI backend: cohort, note viewer, lang2fhir + fhir2omop jobs |
| `static/` | zero-build frontend |
| `.state/` | gitignored artifacts (seed plan/result JSON) |

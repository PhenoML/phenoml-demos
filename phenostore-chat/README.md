# PhenoStore Chat

A simple web app to search a PhenoStore FHIR server in **natural language**. Type a
plain-English question, and the app translates it into a FHIR query (via the
[PhenoML SDK](https://github.com/PhenoML/phenoml-ts-sdk)), runs it against your
PhenoStore instance, and shows a summary plus the raw FHIR JSON.

Two query modes, chosen with a toggle in the UI:

- **FHIR Search** — `lang2Fhir.search()` translates the question into a single
  resource-type query (e.g. _"active medication requests for metformin"_ →
  `MedicationRequest?...`).
- **Cohort Builder** — `cohort.analyze()` breaks a population description into
  multiple include/exclude concepts (e.g. _"female patients over 65 with diabetes
  but not hypertension"_) and runs each against PhenoStore.

In both modes the translated queries are executed against your FHIR provider via
`fhir.search()`. All PhenoML credentials stay on the server — the browser only
talks to `/api/query`.

## Architecture

```
Browser (public/index.html)  ──POST /api/query──▶  Express server (server.ts)
                                                        │
                                                        ├─ lang2Fhir.search / cohort.analyze  (NL → FHIR query)
                                                        └─ fhir.search                        (query → results)
                                                                   │
                                                            PhenoStore FHIR server
```

## Setup

```bash
cd phenostore-chat
npm install
cp .env.example .env   # then fill in your credentials
```

Required environment variables (see `.env.example`):

| Variable                | Description                                              |
| ----------------------- | ------------------------------------------------------- |
| `PHENOML_CLIENT_ID`     | OAuth client ID from the PhenoML Developer Console       |
| `PHENOML_CLIENT_SECRET` | OAuth client secret                                      |
| `PHENOML_BASE_URL`      | Your PhenoML instance URL (default `experiment.app.pheno.ml`) |
| `PHENOSTORE_PROVIDER_ID`| The FHIR provider ID to query                            |

## Run

```bash
npm run dev     # tsx watch, restarts on change
# or
npm start
```

Open <http://localhost:3000> and start asking questions.

Health check: `curl http://localhost:3000/health`

## Notes

- Result size is bounded with a default `_count=50` on each query.
- The summary text is generated deterministically from the FHIR results (no extra
  LLM), so it accurately reflects what was returned.

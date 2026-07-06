# MOPA Lang2FHIR Demo

This demo reuses the breast cancer data from `mopa-breast-pa` and focuses on the provider-side data package:

1. Select the prior-auth artifacts that matter for Lang2FHIR.
2. Generate oncology FHIR resources and a transaction Bundle.
3. Optionally write the Bundle through PhenoML's FHIR Proxy to the FHIR Provider named in `.env`.
4. Run FHIR2Summary with `summary.create(..., mode="ips")` against the in-memory Bundle.
5. Optionally upload local OncoHealth demo profiles to Lang2FHIR.

It does not run the payer queue, CDS Hooks review, Claim review, or UM-9 recommendation flow.

## Prerequisites

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set these values in `mopa-lang2fhir/.env`:

```bash
PHENOML_CLIENT_ID=...
PHENOML_CLIENT_SECRET=...
PHENOML_BASE_URL=
PHENOML_FHIR_PROVIDER_ID=...
```

`PHENOML_FHIR_PROVIDER_ID` is required only for the write action. The demo does not borrow a provider for writes.

## Run

```bash
make dev
```

Open http://localhost:5174.

Manual backend/frontend:

```bash
.venv/bin/uvicorn ui_server:app --port 8002 --reload
cd ui && npm install && npm run dev
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Credential state, configured FHIR Provider id, and profile upload capability |
| `GET /api/source-data` | Source report, data map, requirements, and regimen template |
| `POST /api/extract` | Run Lang2FHIR and assemble the transaction Bundle |
| `POST /api/fhir/write` | Write the transaction Bundle through the FHIR Proxy |
| `POST /api/summary` | Run FHIR2Summary IPS mode |
| `GET /api/profiles` | List local OncoHealth demo profiles |
| `POST /api/profiles/upload` | Upload local profiles when the SDK supports `lang2fhir.upload_profile` |

## Source Data

The demo reads these files from `../mopa-breast-pa`:

| File | Use |
|---|---|
| `sample_path_report.txt` | Lang2FHIR clinical text input |
| `mopa_requirements.json` | Data selection map for oncology evidence |
| `regimen_th.json` | TH regimen RequestGroup template |

`policy_um9_oncohealth.md` and `cds_hooks_server/` are intentionally not used because this demo stops before payer adjudication.

## FHIR Write

The write endpoint calls:

```python
client.fhir.execute_bundle(
    fhir_provider_id=PHENOML_FHIR_PROVIDER_ID,
    request=bundle,
)
```

The response reports created resource locations and the assigned `Patient/{id}` when the FHIR Provider returns one. If the FHIR Provider rejects the write, summary generation still works because it uses the in-memory Bundle.

## Profiles

Local demo profiles live in `profiles/`:

- `oncohealth-oncology-evidence-observation.json`
- `oncohealth-regimen-requestgroup.json`
- `oncohealth-summary-package.json`

The upload action is optional. If the installed SDK does not expose `client.lang2fhir.upload_profile`, the UI reports that and the rest of the demo still works.

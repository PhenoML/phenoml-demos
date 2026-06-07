# TMS Prior-Auth Pipeline — a runnable PhenoML demo

An end-to-end **payer prior-authorization pipeline** built on the [PhenoML Python SDK](https://github.com/PhenoML/phenoml-python-sdk) (**v15**).

**Scenario:** a patient with treatment-resistant depression is referred for **repetitive transcranial magnetic stimulation (rTMS)**. We ingest the referral, build an International Patient Summary, have a **referral agent** review it and ask follow-ups, write the answers back to the EHR, then run the case past a **BCBS-Massachusetts policy agent** (its system prompt *is* [Medical Policy #297](./policy_297_tms.md)) to evaluate the prior auth and adjudicate the claim.

> ✅ **Every snippet below was executed end-to-end against a live PhenoML instance (SDK `15.0.3`).** The notes call out the things that bit us so they don't bite you.

```
  Referral note / PDF
         │  lang2fhir.document_multi / create_multi
         ▼
  FHIR transaction Bundle ──► summary.create(mode="ips") ──► IPS narrative
         │                                                       │
         │                       referral agent reviews the IPS, asks follow-ups
         │                                                       │ answers
         ▼                                                       ▼
  fhir.create  ◄── write Patient + follow-up resources to the EHR ◄┘
         │
         ▼
  BCBS-MA policy agent  (system prompt = policy #297)
         ├─ Step 2 · evaluate prior auth        (or a PhenoML workflow)
         └─ Step 3 · adjudicate submission ──► APPROVED / DENIED + rationale
```

> ⚠️ **For demonstration / education only.** Not medical, billing, or legal advice. The policy text is extracted from a public BCBS-MA PDF; always use the current official policy for real decisions.

---

## Prerequisites

```bash
pip install phenoml python-dotenv          # SDK v15+
cp .env.example .env                        # then fill in your credentials
```

`.env` — the SDK uses **OAuth client credentials**; this demo also supports the **legacy username/password** login (Basic auth → token) since some accounts still use it:

```
# preferred (v15-native):
PHENOML_CLIENT_ID=...
PHENOML_CLIENT_SECRET=...
# OR legacy login:
PHENOML_USERNAME=...
PHENOML_PASSWORD=...

PHENOML_BASE_URL=https://your-instance.app.pheno.ml   # blank = SDK default
PHENOML_FHIR_PROVIDER_ID=<a FHIR provider UUID>        # client.fhir_provider.list() to find one
```

The snippets run **top to bottom in one Python session**. (A consolidated runner is in [`run_demo.py`](./run_demo.py): `python run_demo.py`.)

---

## Setup

```python
import base64, json, os, re
from pathlib import Path
import httpx
from dotenv import load_dotenv
from phenoml import PhenomlClient            # async apps: from phenoml import AsyncPhenomlClient

load_dotenv()

def mint_legacy_token(base_url, username, password):
    """Legacy accounts: Basic-auth the username/password against /auth/token to get a JWT."""
    cred = base64.b64encode(f"{username}:{password}".encode()).decode()
    r = httpx.post(f"{base_url}/auth/token",
                   headers={"Authorization": f"Basic {cred}", "content-type": "application/json"},
                   timeout=30)
    r.raise_for_status()
    return r.json()["token"]

def make_client() -> PhenomlClient:
    base_url = os.environ.get("PHENOML_BASE_URL") or None
    cid, csec = os.environ.get("PHENOML_CLIENT_ID"), os.environ.get("PHENOML_CLIENT_SECRET")
    user, pw = os.environ.get("PHENOML_USERNAME"), os.environ.get("PHENOML_PASSWORD")
    # timeout matters: multi-resource extraction + agent reasoning routinely exceed the ~60s default.
    kw = {"timeout": 300.0, "max_retries": 2}   # single retry layer (the SDK's); bounded so a flaky call won't spam document/multi
    if base_url:
        kw["base_url"] = base_url
    if cid and csec:                                   # v15-native OAuth client credentials
        return PhenomlClient(client_id=cid, client_secret=csec, **kw)
    if user and pw:                                    # legacy: mint a token, pass it as a callable
        token = mint_legacy_token(base_url, user, pw)
        return PhenomlClient(token=lambda: token, **kw)
    raise SystemExit("Set PHENOML_CLIENT_ID/_SECRET or PHENOML_USERNAME/_PASSWORD in .env")

client = make_client()
FHIR_PROVIDER_ID = os.environ.get("PHENOML_FHIR_PROVIDER_ID", "")

def as_dict(obj):
    # by_alias=True is REQUIRED. SDK response models use snake_case attrs (resource_type, full_url),
    # but FHIR/the API expect camelCase (resourceType, fullUrl). Without it, summary.create (IPS)
    # rejects the bundle with HTTP 500 "resourceType field is missing or not a string".
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, list):
        return [as_dict(x) for x in obj]
    return obj

def parse_json(text: str):
    """Best-effort: pull the first JSON object/array out of an LLM reply."""
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}|\[.*\]", text or "", re.DOTALL)
        return json.loads(m.group(0)) if m else {}
```

---

## Step 1 — Build the pipeline

### 1.1 · Document → FHIR (`document/multi`)

`lang2fhir.document_multi` extracts text from a **PDF or image** and returns a FHIR **transaction Bundle** with linked resources. If you don't have a PDF, `create_multi` does the same from raw text (identical response shape) — that's the path used below.

```python
SAMPLE_NOTE = Path("sample_referral_note.txt").read_text()
PDF_PATH = "referral.pdf"   # optional: a real PDF/image

if Path(PDF_PATH).exists():
    content_b64 = base64.b64encode(Path(PDF_PATH).read_bytes()).decode()
    doc = client.lang2fhir.document_multi(version="R4", content=content_b64,
                                          detection_effort="standard", validation_method="none")
    bundle, extracted = as_dict(doc.bundle), as_dict(doc.resources)
else:
    multi = client.lang2fhir.create_multi(text=SAMPLE_NOTE, version="R4")
    bundle, extracted = as_dict(multi.bundle), as_dict(multi.resources)

print(f"extracted {len(bundle.get('entry', []))} resources:")
for r in extracted or []:
    print(f"  - {r.get('resourceType')}: {r.get('description')}")

# The failed/discontinued medication trials are 'stopped'/'completed' (see note in 1.2), so they do
# NOT appear in the IPS current-medication section — but they are the key evidence for policy
# criterion #2. Pull the trial history out here so the prior-auth/adjudication agent can see it.
med_history_text = "\n".join(
    f"- {r.get('description')}" for r in (extracted or []) if r.get("resourceType") == "MedicationRequest"
) or "(no medication trials documented)"
```

> **Verified output:** 11 resources — Patient, Practitioner, Coverage, ServiceRequest, Encounter, Condition (severe recurrent MDD, F33.2), two Observations (PHQ-9 = 22, MADRS = 31), and three MedicationRequests (sertraline, venlafaxine, bupropion).

### 1.2 · Generate the IPS (`summary.create`, `mode="ips"`)

IPS mode produces an [International Patient Summary](https://hl7.org/fhir/uv/ips/) per ISO 27269. It requires a Bundle with **exactly one Patient** that has an identifier — `create_multi`/`document_multi` add a synthetic identifier when the source has none, so the Bundle is IPS-ready.

```python
patients = [e["resource"] for e in bundle.get("entry", [])
            if e.get("resource", {}).get("resourceType") == "Patient"]
assert len(patients) == 1, f"IPS needs exactly one Patient; found {len(patients)}"

ips = client.summary.create(fhir_resources=bundle, mode="ips")
ips_text = ips.summary
print(ips_text)
```

> **Note (why no meds in the IPS):** the IPS *Medication Summary* lists **current/active** meds. The three antidepressants here are coded `completed`/`stopped` (they're *failed/discontinued past trials*), so the IPS shows "No known medications" — which is correct. The trial history (the prior-auth evidence) lives in the `MedicationRequest` resources, which is why 1.1 captures `med_history_text` separately.

### 1.3 · The referral agent reviews the IPS

```python
REFERRAL_AGENT_PROMPT = """You are a referral intake specialist preparing a prior-authorization
packet for rTMS for depression under BCBS-MA Medical Policy #297. Given the patient summary, decide
whether the record documents EACH item and list what is MISSING or AMBIGUOUS:
1. Confirmed SEVERE major depressive disorder documented by a standardized rating scale (PHQ-9, MADRS).
2. At least ONE of: (a) failure of 2 medication trials, (b) intolerance across 2 trials,
   (c) prior rTMS response >= 3 months ago, or (d) ECT candidacy where ECT is not superior.
3. Failure of an adequate psychotherapy trial, documented by a standardized rating scale.
4. Contraindication screen: seizure history, acute/chronic psychosis, relevant neurologic
   conditions, or an implanted magnetic-sensitive device within 30 cm of the coil.

Return ONLY JSON: {"present": [...], "missing": [...], "follow_up_questions": [...]}"""

rp = client.agent.prompts.create(name="tms-referral-intake", content=REFERRAL_AGENT_PROMPT,
                                 description="Reviews a patient summary for TMS prior-auth completeness.")
referral_agent = client.agent.create(name="TMS Referral Intake Agent", prompts=[rp.data.id],
                                     provider=FHIR_PROVIDER_ID, tags=["tms", "prior-auth"])

# IMPORTANT: put the clinical data in `message`, NOT in `context`. The agent does not surface the
# `context=` field to the model — passing the IPS there makes the agent reply "please provide the
# patient information". The referral agent reviews the IPS (the clean summary).
review = client.agent.chat.send(
    agent_id=referral_agent.data.id,
    message="Review the following International Patient Summary against the policy #297 rTMS "
            "criteria and return the JSON.\n\n" + ips_text,
)
print(review.response)
follow_up_questions = parse_json(review.response).get("follow_up_questions", [])
```

> **Verified output:** `present`: severe MDD + standardized rating scale; `missing`/`follow_up_questions`: medication-trial history (not in the IPS), psychotherapy trial, and the contraindication screen.

### 1.4 · Write the follow-up answers back to the EHR as FHIR

Persist the **Patient** first so the new resources can attach to it, then convert each free-text answer to a FHIR resource (`lang2fhir.create`) and **POST it** (`fhir.create`).

```python
created_patient = as_dict(client.fhir.create(
    fhir_provider_id=FHIR_PROVIDER_ID, fhir_path="Patient", request=patients[0]))
patient_id = created_patient.get("id")
print("Patient on EHR:", patient_id)

# In production these are the provider's responses to follow_up_questions:
follow_up_answers = [
    "Completed 16 sessions of cognitive behavioral therapy over 12 weeks with no significant "
    "improvement; PHQ-9 remained 20 or higher throughout.",
    "No personal or family history of seizures and no implanted magnetic-sensitive devices; "
    "no psychotic features in the current episode.",
]

for answer in follow_up_answers:
    resource = as_dict(client.lang2fhir.create(version="R4", resource="auto", text=answer))
    resource.setdefault("subject", {"reference": f"Patient/{patient_id}"})   # link to the patient
    saved = as_dict(client.fhir.create(
        fhir_provider_id=FHIR_PROVIDER_ID, fhir_path=resource["resourceType"], request=resource))
    print(f"  wrote {saved.get('resourceType')}/{saved.get('id')} to the EHR")
```

> **Verified output:** `Patient/<uuid>` created, then a Procedure (the CBT course) and a Condition written to the live Medplum sandbox. `resource="auto"` lets lang2fhir pick the type; pass a specific profile (e.g. `"simple-observation"`, `"questionnaireresponse"`) if you want to pin it.
>
> **Dedicated-instance shortcut:** to write the whole extracted Bundle at once (transaction), use `client.fhir.execute_bundle(fhir_provider_id=FHIR_PROVIDER_ID, request=bundle)`. Bundle/PUT/PATCH/DELETE require a **dedicated** instance; shared instances allow only `GET` + per-resource `POST` (`fhir.create`), which is why we POST individually above.

### 1.5 · The BCBS-MA policy agent (prompt = the policy text)

```python
POLICY_TEXT = Path("policy_297_tms.md").read_text()

bcbs_prompt = client.agent.prompts.create(
    name="bcbs-ma-policy-297",
    content="You are a BCBS-MA utilization-management reviewer. Apply the following policy EXACTLY "
            "as written, cite the criteria you rely on, and never invent criteria.\n\n" + POLICY_TEXT,
    description="BCBS-MA Medical Policy #297 (TMS) as an agent.")
bcbs_agent = client.agent.create(name="BCBS-MA Policy #297 Agent", prompts=[bcbs_prompt.data.id],
                                 provider=FHIR_PROVIDER_ID, tags=["bcbs-ma", "policy-297"])
print("BCBS agent:", bcbs_agent.data.id)
```

---

## Step 2 — Evaluate the prior authorization

### 2.1 · Agent path

Send the BCBS agent the IPS **plus** the medication-trial history (criterion #2 evidence) **plus** the follow-up answers — all in the `message`.

```python
pa_evidence = (
    "=== INTERNATIONAL PATIENT SUMMARY ===\n" + ips_text
    + "\n\n=== MEDICATION TRIAL HISTORY (from chart) ===\n" + med_history_text
    + "\n\n=== ADDITIONAL FOLLOW-UP INFORMATION ON FILE ===\n"
    + "\n".join(f"- {a}" for a in follow_up_answers)
)
pa = client.agent.chat.send(
    agent_id=bcbs_agent.data.id,
    message='A provider requests prior auth for rTMS (CPT 90867/90868/90869). Evaluate the patient '
            'below against policy #297 and return ONLY JSON: {"meets_criteria":true|false,'
            '"satisfied":[...],"unmet":[...],"additional_info_needed":[...],"rationale":"..."}\n\n'
            + pa_evidence,
    enhanced_reasoning=True,
)
print(json.dumps(parse_json(pa.response), indent=2))
```

> **Verified output:** `"meets_criteria": true` — satisfied: Criterion 1 (severe MDD + rating scale), Criterion 2a (sertraline + venlafaxine failures), Criterion 3 (CBT trial), and no contraindications. Drop the psychotherapy answer and re-run to watch it flip to `false` with `additional_info_needed`.

### 2.2 · Workflow alternative (deterministic, repeatable)

For a high-volume, deterministic path, model the same evidence-gathering as a PhenoML **workflow**.

```python
wf = client.workflows.create(
    name="TMS PA - gather supporting evidence",
    workflow_instructions=(
        "Given a patient reference, gather the evidence needed to evaluate an rTMS prior "
        "authorization under BCBS-MA policy #297: severe MDD Condition, depression rating-scale "
        "Observations (PHQ-9/MADRS), antidepressant MedicationRequest history, and any psychotherapy "
        "Observations. Flag which policy criteria are NOT supported by the records found."),
    sample_data={"patient_id": "example-patient-id"},
    fhir_provider_id=FHIR_PROVIDER_ID,
)
print("workflow:", wf.workflow_id)
run = client.workflows.execute(wf.workflow_id, input_data={"patient_id": patient_id})
print(as_dict(run))
```

> **Note:** workflow *creation* generates an execution graph with an LLM and can be **slow** (tens of seconds to a few minutes) — give it a generous `timeout`. **Agent vs. workflow:** use the agent for nuanced, conversational review; use the workflow when you want the same FHIR lookups + criteria checks to run identically every time (the nightly PA queue). A workflow can also be attached to an agent as a tool via `agent.create(..., workflows=[wf.workflow_id])`.

---

## Step 3 — Submit to the payer and adjudicate

### 3.1 · Assemble the submission (with billing codes)

```python
from phenoml.construe import ExtractRequestSystem

cpt = client.construe.codes.extract(
    text="Therapeutic repetitive transcranial magnetic stimulation (TMS) treatment; initial, "
         "including cortical mapping, motor threshold determination, delivery and management; "
         "plus subsequent delivery and management sessions.",
    system=ExtractRequestSystem(name="CPT", version="2025"))
cpt_codes = [as_dict(c) for c in (cpt.codes or [])]
for c in cpt_codes:
    print(c.get("code"), "-", c.get("description"))   # e.g. 90867 ...

submission = {
    "patient": f"Patient/{patient_id}",
    "requested_service": "rTMS for treatment-resistant major depressive disorder",
    "cpt_codes": [c.get("code") for c in cpt_codes][:3],
    "clinical_summary": ips_text,
    "medication_trial_history": med_history_text,
    "supporting_evidence": follow_up_answers,
}
```

### 3.2 · Adjudicate against the payer agent

```python
SCHEMA = ('Respond ONLY as JSON: {"decision":"APPROVED"|"DENIED","covered_codes":[...],'
          '"rationale":"...","policy_citations":[...],"conditions_or_limits":"..."}')

decision = client.agent.chat.send(
    agent_id=bcbs_agent.data.id,
    message="Adjudicate this prior-authorization submission under policy #297. " + SCHEMA
            + "\n\nSUBMISSION:\n" + json.dumps(submission, indent=2),
    enhanced_reasoning=True)
print("APPROVE-PATH:\n", decision.response)
```

> **Verified output:** `"decision": "APPROVED"`, `covered_codes: ["90867"]`, full policy citations, and `conditions_or_limits` = the policy's ≤30-session + 3-week-taper limit.

A case that fails the policy:

```python
denied_case = {
    "patient": "Patient/example-2",
    "requested_service": "rTMS for depression",
    "clinical_summary": "Mild major depressive disorder. One antidepressant trial (sertraline) for "
                        "4 weeks. No psychotherapy trial. No standardized rating scale on file.",
}
denied = client.agent.chat.send(
    agent_id=bcbs_agent.data.id,
    message="Adjudicate the following submission under policy #297. " + SCHEMA
            + "\n\nSUBMISSION:\n" + json.dumps(denied_case, indent=2),
    enhanced_reasoning=True)
print("DENY-PATH:\n", denied.response)
```

> **Verified output:** denied — the agent correctly cites *mild* MDD with no rating scale, only one medication trial (criterion 2 needs two), and no psychotherapy trial. (Per policy #297, a request that doesn't meet criteria is **Investigational**, which the agent often uses as the decision term.)

---

## Cleanup (optional)

```python
for agent_id in [referral_agent.data.id, bcbs_agent.data.id]:
    try: client.agent.delete(agent_id)
    except Exception as e: print("skip agent delete:", e)
for prompt_id in [rp.data.id, bcbs_prompt.data.id]:
    try: client.agent.prompts.delete(prompt_id)
    except Exception as e: print("skip prompt delete:", e)
```

---

## Appendix — things testing taught us

**SDK surface used (v15.x):** `lang2fhir.document_multi` / `create_multi` / `create` · `summary.create(mode="ips")` · `agent.prompts.create` · `agent.create` · `agent.chat.send` · `fhir.create` / `execute_bundle` · `workflows.create` / `execute` · `construe.codes.extract`.

**Gotchas baked into the snippets above:**
1. **`by_alias=True`** when dumping any SDK model to a dict — otherwise FHIR fields come out snake_case (`resource_type`) and IPS generation 500s. *(see `as_dict`)*
2. **Clinical data goes in `message`, not `context`** — `agent.chat.send(context=...)` does not reach the model; agents will say "please provide the patient information." *(Steps 1.3, 2.1, 3.2)*
3. **Raise the client `timeout`** (≥300s) — multi-resource extraction and workflow-graph generation exceed the default and raise `ReadTimeout`/`RemoteProtocolError`. `max_retries` helps with transient server disconnects.
4. **IPS = current meds only** — failed/discontinued trials (`completed`/`stopped`) won't appear; carry the `MedicationRequest` history separately for prior-auth. *(Step 1.1 → 2.1)*
5. **Auth:** v15 is `PhenomlClient(client_id=, client_secret=)`; legacy accounts mint a token via Basic-auth `POST /auth/token` and pass it as `token=lambda: tok`. *(see `make_client`)*

**Shared vs dedicated instances:** shared instances allow FHIR `GET` + `POST`; `PUT`/`PATCH`/`DELETE`/Bundle need a dedicated instance. The demo uses per-resource `POST` so it runs anywhere.

**Policy text:** the BCBS-MA #297 criteria live in [`policy_297_tms.md`](./policy_297_tms.md) and are loaded verbatim as the payer agent's system prompt.

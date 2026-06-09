# Part 1 — Building the Agents

> **Course module 1 of 2.** Next: [Part 2 — Determinism & Evals](./part-2-determinism-evals.md).
> Install + credentials are in the [course index](./README.md#prerequisites).

In this module you build the two LLM agents at the heart of a payer prior-authorization pipeline for **rTMS** (repetitive transcranial magnetic stimulation) under [BCBS-MA Medical Policy #297](./policy_297_tms.md):

1. a **referral intake agent** that reviews a patient summary for completeness and asks follow-up questions, and
2. a **BCBS-MA policy #297 agent** whose system prompt *is* the payer's medical policy — it evaluates the request against the criteria and adjudicates APPROVED/DENIED.

You'll run them against ready-made clinical inputs, evaluate a prior auth, watch a decision **flip** when the evidence changes, and adjudicate the claim.

> ✅ **Every code snippet runs against a live PhenoML instance (SDK `15.0.3`).** Answers to each exercise are hidden behind a **`▸ Reveal`** toggle — commit to a prediction *before* you open it.
>
> The upstream data plumbing — document→FHIR extraction, IPS generation, and writing answers back to the EHR — is implemented end-to-end in [`run_demo.py`](./run_demo.py). This module starts from a ready-made patient summary (the fixtures below) so we can focus on the *agents*.

> ⚠️ **For demonstration / education only.** Not medical, billing, or legal advice.

## Learning objectives

By the end of Part 1 you can:
- author a **system prompt** that turns an LLM into a role-bound reviewer that returns machine-usable JSON;
- explain why clinical data must go in the agent's `message`, not `context`;
- assemble multi-source evidence and demonstrate **evidence-sensitivity** (same patient + same agent, different evidence → different decision);
- choose between a conversational **agent** and a deterministic **workflow**;
- adjudicate a submission to a structured APPROVED/DENIED decision with billing codes and policy citations.

---

## Setup

```python
import json, os, re
from pathlib import Path
from dotenv import load_dotenv
from phenoml import PhenomlClient            # async apps: from phenoml import AsyncPhenomlClient

load_dotenv()

def make_client() -> PhenomlClient:
    base_url = os.environ.get("PHENOML_BASE_URL") or None
    cid, csec = os.environ.get("PHENOML_CLIENT_ID"), os.environ.get("PHENOML_CLIENT_SECRET")
    # timeout matters: multi-resource extraction + agent reasoning routinely exceed the ~60s default.
    kw = {"timeout": 300.0, "max_retries": 2}
    if base_url:
        kw["base_url"] = base_url
    if cid and csec:                                   # v15-native OAuth client credentials
        return PhenomlClient(client_id=cid, client_secret=csec, **kw)
    raise SystemExit("Set PHENOML_CLIENT_ID and PHENOML_CLIENT_SECRET in .env")

client = make_client()
FHIR_PROVIDER_ID = os.environ.get("PHENOML_FHIR_PROVIDER_ID", "")

def as_dict(obj):
    # by_alias=True is REQUIRED when you dump an SDK model for the FHIR API: SDK models use
    # snake_case attrs (resource_type), but FHIR expects camelCase (resourceType).
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, list):
        return [as_dict(x) for x in obj]
    return obj

def parse_json(text: str) -> dict:
    """Best-effort: pull the first JSON object out of an LLM reply. ALWAYS returns a dict (empty if
    none can be recovered) so every caller can safely .get() the result."""
    try:
        v = json.loads(text)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    return {}
```

---

## The clinical inputs (fixtures)

Normally these come from the upstream pipeline (document→FHIR → IPS → EHR write-back; see [`run_demo.py`](./run_demo.py)). Here we hard-code them so this module runs top-to-bottom on its own. These are the **exact frozen inputs** used by the `approve-maria-garcia` eval case in [Part 2](./part-2-determinism-evals.md) — so the two modules tell one story.

```python
patient_id = "example-patient-0001"   # placeholder; in the full demo this is a real FHIR Patient id

# The International Patient Summary (IPS): a clean, standards-based narrative of the patient.
ips_text = """Patient: Maria Garcia (DOB: 1985-07-22, 40 years old)
Gender: Female
MRN: GBH-4471

## Allergies and Intolerances
• No known allergies

## Medication List
• No known medications

## Problem List
• Major depressive disorder, recurrent severe without psychotic features

## General Observations
• Mood interview total severity score during assessment period [CMS Assessment]: 31"""

# Why is the medication history SEPARATE from the IPS? An IPS lists CURRENT/active meds only. These
# three antidepressants are *failed past trials* (FHIR status completed/stopped), so they don't show
# up in the IPS — but they are the key evidence for policy criterion #2, so we carry them alongside.
med_history_text = (
    "- Sertraline 200 mg daily for 10 weeks during the current episode — no meaningful response "
    "(PHQ-9 remained > 18).\n"
    "- Venlafaxine XR 225 mg daily for 9 weeks — minimal response, discontinued.\n"
    "- Bupropion XL 300 mg — discontinued after 2 weeks due to intolerable agitation and insomnia."
)

# In production these are the provider's answers to the referral agent's follow-up questions.
follow_up_answers = [
    "Completed 16 sessions of cognitive behavioral therapy over 12 weeks with no significant "
    "improvement; PHQ-9 remained 20 or higher throughout.",
    "No personal or family history of seizures and no implanted magnetic-sensitive devices; "
    "no psychotic features in the current episode.",
]
```

---

## Step 1 — Build the agents

### 1.1 · The referral intake agent

An agent is a **system prompt** plus configuration. This one is pinned to a single job: read a patient summary and report what policy-relevant evidence is **present**, **missing**, or **ambiguous** — and propose follow-up questions.

> **🧠 Exercise — write the prompt first (Design).** Before you read the prompt below, draft your own. The agent gates an rTMS prior auth, so it must check whether the record documents *each* requirement that policy #297 cares about and flag what's missing. **What are the (roughly four) things it should check? What output shape makes the result machine-usable by the next step?** Then compare.
>
> <details><summary>▸ Reveal — the four criteria & the output contract</summary>
>
> Policy #297 gates on four things, so the prompt enumerates them: **(1)** severe MDD confirmed by a *standardized rating scale* (PHQ-9/MADRS); **(2)** at least one of {2 failed med trials, intolerance across 2 trials, prior rTMS response ≥3 months ago, ECT candidacy where ECT isn't superior}; **(3)** a failed adequate *psychotherapy* trial; **(4)** a *contraindication screen* (seizure history, psychosis, neurologic conditions, implanted magnetic-sensitive device near the coil). The output is constrained to `{"present":[...], "missing":[...], "follow_up_questions":[...]}` so the next step can branch on it programmatically — free prose would not be machine-usable.
>
> </details>

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

# IMPORTANT: the clinical data goes in `message`, NOT `context`.
review = client.agent.chat.send(
    agent_id=referral_agent.data.id,
    message="Review the following International Patient Summary against the policy #297 rTMS "
            "criteria and return the JSON.\n\n" + ips_text,
)
print(review.response)
follow_up_questions = parse_json(review.response).get("follow_up_questions", [])
```

> **🔧 Exercise — break it (Break-it).** Move the IPS out of `message=` and pass it as `context=ips_text` instead (drop it from the message). Re-run. **What does the agent reply, and what does that tell you about how `context` is handled?**
>
> <details><summary>▸ Reveal — message vs. context</summary>
>
> The agent replies with something like *"please provide the patient information."* `agent.chat.send(context=...)` does **not** surface that field to the model — it's not the channel for the data you want reasoned over. Clinical content must go in `message`. This is one of the most common first-day mistakes with the SDK.
>
> </details>

> **🔍 Exercise — why not just `json.loads`? (Reason).** The prompt says *"Return ONLY JSON"*, yet `parse_json` still regex-searches for `{...}` rather than calling `json.loads(reply)` once. **Construct an agent reply that makes a bare `json.loads(reply)` raise, but that `parse_json` still recovers.**
>
> <details><summary>▸ Reveal</summary>
>
> Models routinely wrap JSON in prose or fences: `Here is the assessment:\n\n```json\n{"present": [...]}\n````. `json.loads` on that whole string raises `JSONDecodeError`; `parse_json`'s `re.search(r"\{.*\}", ..., DOTALL)` pulls the first `{...}` object out. `parse_json` also guards the *type* — if the model returns a top-level array or scalar, it returns `{}` so downstream `.get()` calls never crash. "Return ONLY JSON" reduces this but never eliminates it; parse defensively.
>
> </details>

### 1.2 · The policy adjudication agent

The payer agent's system prompt is the **entire policy text**, loaded verbatim, with a one-line instruction to apply it exactly and cite what it relies on.

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

> **🧠 Exercise — verbatim vs. summarized policy (Design).** We paste the whole policy in. **What do you gain over summarizing it into a few bullet criteria — and what are the failure modes of each?** Consider token cost, missed edge clauses, hallucinated criteria, and auditability. When *would* you summarize?
>
> <details><summary>▸ Reveal — discussion</summary>
>
> **Verbatim:** auditable (a denial can be traced to the exact clause), no paraphrase drift, edge clauses survive — at the cost of tokens on every call and the risk of burying the model in boilerplate. **Summarized:** cheaper and faster, but *you* now own everything you dropped; a criterion the model can't see is one it can't apply. For payer adjudication, where any denial may be appealed, verbatim + *"cite the criteria you rely on, never invent criteria"* is the defensible default. Summarize only when the policy is huge **and** you can show the summary is lossless for the decisions you actually make.
>
> </details>

> **🔧 Exercise — try to make it hallucinate (Break-it).** The prompt says *"never invent criteria."* Write a submission designed to *tempt* the agent into applying a requirement that isn't in policy #297 (e.g. an age cutoff, or a specific session count the policy never states). Run it through §3.2's adjudicate call and read the rationale/citations. **Does it stick to the policy, or invent? What prompt change would harden it further?**
>
> <details><summary>▸ Reveal — discussion</summary>
>
> A well-behaved agent refuses to apply criteria not in the text and cites only real clauses. If it invents one, that's a prompt-hardening signal — add an explicit *"if the policy is silent on a point, treat it as not a requirement."* This is exactly the failure mode the **gold labels** + `must_cite_any` checks in [Part 2](./part-2-determinism-evals.md) are built to catch: you can't eyeball every run, so you encode "must cite a real criterion" into the eval.
>
> </details>

---

## Step 2 — Evaluate the prior authorization

### 2.1 · Agent path

> **🧠 Exercise — assemble the evidence (Predict).** Before reading the code: **which evidence sources must you concatenate into the agent's `message` to evaluate criterion #2 (medication trials)? Why isn't the IPS alone enough?**
>
> <details><summary>▸ Reveal</summary>
>
> You need **IPS + `med_history_text` + `follow_up_answers`**. The IPS omits the failed trials (active meds only), so criterion #2's evidence lives *only* in `med_history_text`; criterion #3 (psychotherapy) and the contraindication screen live in the follow-up answers. Send the agent only the IPS and it cannot satisfy #2 — it will (correctly) report it as missing.
>
> </details>

```python
pa_evidence = (
    "=== INTERNATIONAL PATIENT SUMMARY ===\n" + ips_text
    + "\n\n=== MEDICATION TRIAL HISTORY (from chart) ===\n" + med_history_text
    + "\n\n=== ADDITIONAL FOLLOW-UP INFORMATION ON FILE ===\n"
    + "\n".join(f"- {a}" for a in follow_up_answers)
)
PA_PROMPT = ('A provider requests prior auth for rTMS (CPT 90867/90868/90869). Evaluate the patient '
             'below against policy #297 and return ONLY JSON: {"meets_criteria":true|false,'
             '"satisfied":[...],"unmet":[...],"additional_info_needed":[...],"rationale":"..."}\n\n')
pa = client.agent.chat.send(
    agent_id=bcbs_agent.data.id, message=PA_PROMPT + pa_evidence, enhanced_reasoning=True)
print(json.dumps(parse_json(pa.response), indent=2))
```

> **🔮 Predict:** with the full evidence (IPS + medication history + both follow-ups), will this submission meet the policy criteria? Commit, then reveal.
>
> <details><summary>▸ Reveal — verified output</summary>
>
> `"meets_criteria": true` — satisfied: Criterion 1 (severe MDD + rating scale), Criterion 2a (sertraline + venlafaxine failures), Criterion 3 (CBT trial), and no contraindications.
>
> </details>

**Flip the decision — same patient, same agent, less evidence.** Drop the psychotherapy follow-up answer (the only evidence for criterion #3) and re-run:

```python
# follow_up_answers[0] is the CBT/psychotherapy answer; keep only the contraindication screen.
pa_evidence_no_psych = (
    "=== INTERNATIONAL PATIENT SUMMARY ===\n" + ips_text
    + "\n\n=== MEDICATION TRIAL HISTORY (from chart) ===\n" + med_history_text
    + "\n\n=== ADDITIONAL FOLLOW-UP INFORMATION ON FILE ===\n"
    + "\n".join(f"- {a}" for a in follow_up_answers[1:])      # psychotherapy answer dropped
)
pa_flip = client.agent.chat.send(
    agent_id=bcbs_agent.data.id, message=PA_PROMPT + pa_evidence_no_psych, enhanced_reasoning=True)
print(json.dumps(parse_json(pa_flip.response), indent=2))
```

> **🔮 Predict:** which criterion moves to `unmet`, and does `meets_criteria` flip? Reveal after you've decided.
>
> <details><summary>▸ Reveal — expected output</summary>
>
> `"meets_criteria": false` — criteria 1 & 2 and the contraindication screen still pass, but criterion #3 moves to `unmet`. Same patient, same agent — only the evidence changed.
>
> </details>

> **🧪 Exercise — predict the next flips (Predict).** For each, write your prediction *before* running, then run it:
> 1. Drop the **contraindication** follow-up answer (`follow_up_answers[:1]`) instead of the psychotherapy one.
> 2. Drop the **medication history** (`med_history_text`) but keep both follow-ups.
> 3. Drop **both** follow-ups (keep only the IPS).
>
> <details><summary>▸ Reveal — reasoning (then verify; the LLM's wording will vary)</summary>
>
> 1. **Subtle.** The dropped answer *documents the absence* of contraindications. Removing it doesn't create a positive contraindication, so the agent typically moves the screen to `additional_info_needed` rather than denying outright — it may still "meet" with a caveat, or ask for the screen. The lesson: some evidence is **gating** (criterion #2), and some is a **screen** whose *absence* triggers a request, not a denial.
> 2. **Hard flip.** `med_history_text` is the only evidence for criterion #2 → unmet → does **not** meet.
> 3. **Hard flip.** Removing both follow-ups strips criterion #3 *and* the screen → criterion #3 unmet → does **not** meet.
>
> Across all of these the *direction* of the flip is stable even though the rationale wording varies run-to-run — which is exactly what [Part 2](./part-2-determinism-evals.md) measures.
>
> </details>

### 2.2 · Workflow alternative (deterministic, repeatable)

For a high-volume, deterministic path, model the same evidence-gathering as a PhenoML **workflow** instead of a conversational agent.

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
# NOTE: execute needs a REAL persisted patient. Our `patient_id` is a placeholder fixture, so this
# call is illustrative — run it against a patient you actually wrote to FHIR (see run_demo.py).
run = client.workflows.execute(wf.workflow_id, input_data={"patient_id": patient_id})
print(as_dict(run))
```

> **Note:** workflow *creation* generates an execution graph with an LLM and can be **slow** (give it a generous `timeout`).

> **🧠 Exercise — agent or workflow? (Design).** List **three** situations where you'd run this as a deterministic *workflow* and **three** where the conversational *agent* wins. The nightly batch that pre-screens tomorrow's PA queue — which one? When would you use **both**?
>
> <details><summary>▸ Reveal — discussion</summary>
>
> **Workflow** when you want the *same* FHIR lookups + criteria checks to run identically every time: high volume, auditable, no nuance needed (nightly PA queue, dashboards, hard gating). **Agent** when the input is messy free text, you need judgment + an explanation, or a human is in the loop (intake review, appeals, edge cases). **Both:** attach the workflow to the agent as a tool — `agent.create(..., workflows=[wf.workflow_id])` — so the agent calls the deterministic evidence-gatherer and then *reasons* over the structured result. Deterministic retrieval + flexible judgment.
>
> </details>

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

> **🔮 Predict:** APPROVED or DENIED — and which CPT code is covered? Reveal.
>
> <details><summary>▸ Reveal — verified output</summary>
>
> `"decision": "APPROVED"`, `covered_codes: ["90867"]`, full policy citations, and `conditions_or_limits` = the policy's ≤30-session + 3-week-taper limit.
>
> </details>

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

> **🧪 Exercise — the minimum flip (Extend).** Starting from the **APPROVED** `submission`, find the *smallest* change that flips the decision to DENIED. Try, one at a time: remove the rating-scale line; reduce to a single med trial; delete the psychotherapy evidence; add a seizure history. **Which single edit is sufficient on its own?**
>
> <details><summary>▸ Reveal — discussion</summary>
>
> Each gating criterion is individually **necessary**, so breaking any *one* of {severe + rating scale, ≥2 failed trials, psychotherapy trial} should flip the decision; adding a contraindication (seizure / implanted device) flips it *even when every criterion is met*. So the minimum is a single edit. This one-criterion-at-a-time sensitivity is exactly what the Part 2 case set encodes — one labeled case per failure mode.
>
> </details>

> **🔍 Exercise — the "Investigational" trap (Reason).** Run the deny case and read the `decision` field. Policy #297 calls a non-meeting request **Investigational**, not "DENIED" — and the agent often echoes that word. **If your pipeline did `if decision == "DENIED":`, what breaks? How do you make the check robust?**
>
> <details><summary>▸ Reveal</summary>
>
> A literal `== "DENIED"` misses *"Investigational"*, *"not medically necessary"*, *"NOT APPROVED"*, and friends — so a real denial sails through as "not a denial." You must **normalize** the decision word: map anything that isn't an explicit approval to DENIED. Part 2's `normalize_decision()` does exactly this — and *choosing* that mapping is itself an eval-design decision you'll examine there.
>
> </details>

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

A checklist of the gotchas baked into the snippets above:

1. **Clinical data goes in `message`, not `context`** — `agent.chat.send(context=...)` doesn't reach the model (you met this in §1.1).
2. **Raise the client `timeout`** (≥300s) — agent reasoning and workflow-graph generation exceed the ~60s default and raise `ReadTimeout`.
3. **Auth is OAuth client credentials** — `PhenomlClient(client_id=, client_secret=)` (v15-native).
4. **`by_alias=True`** whenever you dump an SDK model to a dict for the FHIR API — otherwise fields come out snake_case and FHIR/IPS calls 500. You'll hit this in the full pipeline (`run_demo.py`); this module sidesteps it by starting from a ready-made summary.
5. **IPS = current meds only** — failed/discontinued trials (`completed`/`stopped`) don't appear, which is why we carry `med_history_text` separately (see the fixtures). Also a `run_demo.py` lesson.

**Policy text:** the BCBS-MA #297 criteria live in [`policy_297_tms.md`](./policy_297_tms.md), loaded verbatim as the payer agent's system prompt.

---

## 🎓 Capstone — port the pipeline to a different policy

Pick a *different* payer medical policy (another procedure, or another payer's rTMS policy) and adapt this pipeline to it. **What's reusable as-is, what has to change, and where do the seams show?**
- Which code is policy-agnostic (the agent scaffolding, `parse_json`, the submission shape) vs. policy-specific (the referral prompt's criteria list, the contraindication screen, the covered CPT codes)?
- Does your new policy have criteria that *aren't* a simple "all must be met" gate (e.g. step-therapy ordering, time windows, quantity limits)? How would you encode those in the referral prompt and the adjudication schema?
- What new evidence sources would the referral agent need to ask for?

Then carry your new policy into [Part 2](./part-2-determinism-evals.md) and build a case set for it.

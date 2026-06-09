# Part 2 — Determinism & Evals

> **Course module 2 of 2.** Follows [Part 1 — Building the Agents](./part-1-building-agents.md), but **runs standalone**: the eval harness builds its own throwaway policy #297 agent and deletes it on exit.
> Install + credentials are in the [course index](./README.md#prerequisites).

A payer won't ship an automated prior-auth it can't trust, and "trust" is two **measurable** questions:

1. **Is it correct?** Decisions must match expert adjudication on a labeled set.
2. **Is it consistent?** The same clinical facts must produce the same decision every time — it can't approve a case on Monday and deny it on Tuesday.

The adjudication step is an LLM, so it's **stochastic** — and the PhenoML SDK exposes **no temperature/seed/model knob**. So we don't *claim* forced determinism on the judgment step; we **measure** its stability empirically across repeated runs, and we keep it separate from the schema-constrained coding/extraction layers (which are deterministic by construction). This module is about that measurement: how [`evals/run_evals.py`](./evals/run_evals.py) scores **accuracy** and **stability**, and how you'd grow the case set.

> ⚠️ **For demonstration / education only.** Not medical, billing, or legal advice.

## Learning objectives

By the end of Part 2 you can:
- distinguish **accuracy** (vs. gold) from **stability** (across repeats) and explain why you need both;
- read the scoring code and predict its behavior on ties and edge cases;
- explain why decision **normalization** is an eval-design decision, not just string-cleanup;
- **author a new labeled case** and adjudicate the agent-vs-gold disagreements it surfaces;
- reason about a stability threshold for routing cases to human review;
- prove an eval actually catches a regression.

---

## Run it

`evals/run_evals.py` pins each case's clinical inputs (frozen submissions under `evals/cases/`) and exercises **just the adjudication step** K times each, then scores accuracy vs. gold and stability across repeats.

```bash
.venv/bin/python evals/run_evals.py --validate                  # load + check cases, NO API calls
.venv/bin/python evals/run_evals.py                             # K = EVAL_REPEATS (default 5)
EVAL_REPEATS=3 .venv/bin/python evals/run_evals.py              # quicker pass
.venv/bin/python evals/run_evals.py --case deny-mild-mdd        # one case, fast iteration
.venv/bin/python evals/run_evals.py --case deny-mild-mdd --repeats 4   # even K invites ties — see §1
```

> Run under the demo's **`.venv`** (SDK v15). The harness creates its own throwaway policy #297 agent and deletes it on exit; adjudicate-only means **no EHR writes**, so it runs on a shared instance.
>
> `run_evals.py` also accepts `EVAL_CHECK_EXTRACTION=1` to re-extract the FHIR bundle K× and check the *extraction* layer's stability. That's the schema-constrained substrate — out of scope for this module, which focuses on the judgment layer.

## What it prints

Actual output from a 3-repeat run against the live instance:

```
CASE                        EXPECT    DECISION (k runs)    CODES          CITED  STABLE
---------------------------------------------------------------------------------------
approve-maria-garcia        APPROVED  APPROVED 3/3         90867 ✓        3/3    ✓
deny-contraindication       DENIED    DENIED 3/3           — ✓            3/3    ✓
deny-mild-mdd               DENIED    DENIED 3/3           — ✓            2/2    ✓
deny-missing-psychotherapy  DENIED    DENIED 3/3           — ✓            1/1    ✓
---------------------------------------------------------------------------------------
Decision accuracy:   4/4  (100%)
Decision stability:  12/12 runs agree  (100%)
Structured layer (construe CPT):    90867 — stable 3/3  (✓)
```

Columns: **EXPECT** is the gold; **DECISION** is the modal decision and how many of the K runs agreed (a `⚠` marks an unstable case); **CODES** is the modal covered-code set with a ✓/✗ vs. expected; **CITED** is how many `must_cite_any` keywords showed up; **STABLE** is ✓ only if both the decision *and* the codes were identical across all K runs. It also writes [`evals/report.md`](./evals/report.md) (shareable) and `evals/report.json`.

> The `Structured layer (construe CPT)` line appears even though this module doesn't dig into the coding layer — it's the schema-constrained substrate, shown for contrast. Don't be surprised by it.

---

## Section 1 — The judgment layer (how scoring works)

Open [`evals/run_evals.py`](./evals/run_evals.py) and read `score_case` (≈ line 79), `normalize_decision` (≈ line 49), and `cite_hits` (≈ line 69). The scorer turns K raw agent replies into accuracy + stability for one case.

> **🧪 Exercise — stable but wrong (Construct).** Accuracy and stability are *different axes*. Describe (or actually author — see §2) a case where the agent is perfectly **stable** (all K runs agree) yet **wrong** (disagrees with your gold). **What does the scorecard show? Why is a 100%-stable-but-wrong case more dangerous than a flaky one?**
>
> <details><summary>▸ Reveal</summary>
>
> Example: a borderline case you've labeled `APPROVED` that the (conservative) policy agent confidently denies every time. The scorecard shows `DECISION DENIED 5/5`, `STABLE ✓`, **and** `✗ WRONG vs gold`. It's *more* dangerous than a flaky case because stability creates false confidence — it never trips a "flaky → send to a human" alarm. Only the **gold label** catches it. That's the whole argument for labeled evals: stability alone is a model agreeing *with itself*, not with the truth.
>
> </details>

> **🔍 Exercise — read the tiebreak (Read the code).** Find the line that picks the case's decision from K runs: `modal, agree = Counter(decisions).most_common(1)[0]`. **At K=4, when the runs split 2 APPROVED / 2 DENIED, which decision wins, and is `decision_stable` True?** Predict, then run a borderline case with `--repeats 4`.
>
> <details><summary>▸ Reveal</summary>
>
> `most_common(1)` returns the highest-count element; on a **tie**, Python's `Counter` breaks it by **insertion order** — *first decision seen wins*. So `[APPROVED, DENIED, APPROVED, DENIED]` → modal `APPROVED`, but `[DENIED, APPROVED, DENIED, APPROVED]` → modal `DENIED`. The tiebreak is **order-dependent, i.e. effectively arbitrary** — a wart worth surfacing, not trusting. And `decision_stable = (agree == k)` → `2 == 4` is False, so STABLE shows `✗` and the row gets a `⚠`. The real lesson: a tie *is* the "route to a human" signal — don't let the modal silently pick a side. Even-numbered K invites ties, which is partly why the default is **K=5**.
>
> </details>

> **🧠 Exercise — normalization is a design decision (Design).** Read `normalize_decision`. It maps `INVESTIGATIONAL` / `NOT APPROV` / `DENY` → `DENIED`, and its *final fallback* is `return "DENIED"`. **(1) Why is "Investigational → DENIED" an eval-design choice, not just string-cleanup? (2) The fallback is fail-closed (unknown → DENIED). When is that right, and when does it silently inflate your deny-case accuracy?**
>
> <details><summary>▸ Reveal — discussion</summary>
>
> **(1)** The policy's own word for "doesn't meet criteria" is *Investigational*. Deciding that counts as a denial is a clinical/business judgment baked into the scorer — flip it and your accuracy numbers move. The eval is only as meaningful as that mapping, so it belongs in code review, not buried in a regex.
> **(2)** Fail-closed (default `DENIED`) is safe for patient/payer risk — don't auto-approve garbage. But it means a garbled or empty reply on a case whose **gold is DENIED still scores as correct**. If most of your gold set is DENIED, a model that emits noise can look accurate. Mitigation: track `EMPTY`/`ERROR` separately (the harness does — see the `ERROR` sentinel in `adjudicate` and the per-run error notes) and never let them masquerade as confident denials.
>
> </details>

---

## Section 2 — The case set (and growing it)

Four labeled cases, one JSON each in `evals/cases/`, every input frozen from a live run:

| Case | Exercises | Gold |
|------|-----------|------|
| `approve-maria-garcia` | criteria 1 + 2a + 3 met, screen clear | **APPROVED**, `90867` |
| `deny-mild-mdd` | mild MDD, 1 trial, no scale, no therapy | **DENIED** |
| `deny-missing-psychotherapy` | 1 & 2 met, criterion 3 absent (the Part 1 "drop the psychotherapy answer" flip) | **DENIED** |
| `deny-contraindication` | 1/2/3 met but seizure hx + implanted device | **DENIED** |

A case is a frozen submission + expected outcome. `load_cases` requires top-level `id`, `description`, `submission`, `expected`; the submission needs `clinical_summary` + `requested_service`; `expected.decision` must normalize to APPROVED/DENIED. (`expected.covered_codes` and `must_cite_any` default to empty.) The harness supplies the `patient` field itself (`Patient/eval-<id>`), so you don't include one. **Add a case by dropping another JSON in `evals/cases/` — no code changes.**

```json
{
  "id": "approve-prior-rtms-response",
  "description": "Criterion 2c: documented prior rTMS response >= 3 months ago (instead of two med failures). Should APPROVE 90867.",
  "submission": {
    "requested_service": "rTMS for recurrent major depressive disorder",
    "cpt_codes": ["90867"],
    "clinical_summary": "Patient with severe recurrent MDD; MADRS 29. ...",
    "medication_trial_history": "...",
    "supporting_evidence": [
      "Prior course of rTMS in 2024 with documented sustained response for ~5 months before relapse."
    ]
  },
  "expected": {
    "decision": "APPROVED",
    "covered_codes": ["90867"],
    "must_cite_any": ["condition 2", "prior"]
  }
}
```

> **🏗️ Exercise — author a case the set doesn't cover (Big one).** The four cases don't exercise criterion **2c** (prior rTMS response ≥3 months ago) or **2d** (ECT candidacy where ECT isn't superior). Pick one. Write the `clinical_summary`/evidence, **decide the gold `decision`, `covered_codes`, and `must_cite_any` yourself**, drop the JSON in `evals/cases/`, then:
> ```bash
> .venv/bin/python evals/run_evals.py --validate
> .venv/bin/python evals/run_evals.py --case approve-prior-rtms-response --repeats 3
> ```
> **If the agent disagrees with your gold, you have to adjudicate: is the *agent* misreading the policy, or is your *gold label* wrong?** Write down which, and why.
>
> <details><summary>▸ Reveal — the real skill here</summary>
>
> Disagreements are **information**, not noise. If the agent cites the policy correctly and your gold was a guess, fix the gold — your label was the bug. If the agent invented a clause or missed one that's plainly in the text, that's a prompt or model finding to file. Either way the case earns its place in the set. This adjudication loop — write case → run → resolve disagreement → keep or fix — *is* eval engineering. A case set you never disagreed with probably wasn't testing anything hard.
>
> </details>

> **🎚️ Exercise — engineer instability, then set a threshold (Stretch).** Build a case deliberately on the policy's edge — strong on two criteria, *genuinely ambiguous* on a third — and run it at `--repeats 7`. **Can you get the runs to disagree (e.g. `4/7 ⚠`)?** Then the product question: **at what stability do you auto-decide vs. route to a human reviewer? Defend a threshold.**
>
> <details><summary>▸ Reveal — discussion</summary>
>
> There's no universal number — but the instability *is* the routing signal. A common pattern: auto-decide only when **all K agree** (and even then, sample-audit a slice); route any case with a single flipped repeat to a human. Larger K raises sensitivity (catches more wobble) at the cost of more API calls. The honest story for a payer: *"we don't force determinism; we measure it and escalate the unstable minority to a human."*
>
> </details>

> **📊 Exercise — read the report like a stakeholder (Reason).** After a run, open `evals/report.md` / `report.json`. **(a)** A case shows `DENIED 2/3 ⚠` and `✗` in STABLE — *bug to fix, or signal to keep?* **(b)** You're in front of a payer's technical buyer: **which two numbers do you lead with, and what is the one caveat you must state to stay honest?**
>
> <details><summary>▸ Reveal</summary>
>
> **(a)** Signal, not bug. The harness correctly caught a case where the judgment layer wavered; the response is to route that case to a human and investigate the prompt — *not* to silence the warning. **(b)** Lead with **decision accuracy vs. gold** and **decision stability (runs agree)**. The mandatory caveat is the *"measured, not forced"* line: stability is observed across N repeats on a small labeled set — it's evidence, not a guarantee, and it's only as trustworthy as the gold labels behind it. Point them at `report.json` for the per-case breakdown.
>
> </details>

---

## 🎓 Capstone — prove your eval has teeth

An eval you can't make *fail* on a real regression isn't protecting you. Introduce one and confirm the harness catches it:

- Weaken the policy agent's system prompt — drop `"never invent criteria"`, or summarize away criterion #2's "two trials" detail (edit `create_bcbs_agent` in `run_evals.py`, or the prompt in [Part 1 §1.2](./part-1-building-agents.md#12--the-policy-adjudication-agent)).
- Re-run `evals/run_evals.py` and watch for a case that moves to `✗ WRONG vs gold` or goes unstable.
- **If nothing changes, your case set has a gap** — add the case that *would* have caught it.

Report what regressed, which case caught it (or which case you had to add), and how much you'd trust this eval to gate a production deploy.

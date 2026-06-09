# TMS prior-auth — determinism & evals report

_Generated 2026-06-09T01:59:02+00:00 · 3 repeats per case · adjudicate-only_

| Case | Expected | Decision (k runs) | Codes | Cited | Stable | Correct |
|------|----------|-------------------|-------|-------|--------|---------|
| `approve-maria-garcia` | APPROVED | APPROVED 3/3 | 90867 | 3/3 | ✓ | ✓ |
| `deny-contraindication` | DENIED | DENIED 3/3 | — | 3/3 | ✓ | ✓ |
| `deny-mild-mdd` | DENIED | DENIED 3/3 | — | 2/2 | ✗ | ✓ |
| `deny-missing-psychotherapy` | DENIED | DENIED 3/3 | — | 1/1 | ✓ | ✓ |

- **Decision accuracy:** 4/4 (100%)
- **Decision stability:** 12/12 runs agree (100%)
- **Structured (construe CPT):** 90867 — stable across 3 runs

> Determinism is **measured, not forced**: the PhenoML SDK exposes no temperature/seed knob, so the judgment layer's stability is observed empirically across repeats. The coding/extraction layers are schema-constrained and deterministic by construction. Demonstration only — not medical, billing, or legal advice.

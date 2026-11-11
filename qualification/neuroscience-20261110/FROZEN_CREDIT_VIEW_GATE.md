# Frozen credit-view future-feedback noninterference — 2026-11-11

**Qualification:** RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO. This is a
reference-level metadata projection, **not** a real model-training result,
source authentication, Q24 owner integration, independent evaluation, or
production admission. Do not treat synthetic negative controls as outcomes.

## Exact base and observed defect

- Exact audited parent: PR #5999,
  `1c31c59394eb43658786bdf1c99f0978e6a93536`.
- Parent tree: `519a801df04e7645e511420b146d99f14cb8d455`.
- In the original `time_aligned_credit` API, appending one otherwise-valid
  feedback receipt **after** training cutoff 5 changes the full forensic
  `future_withheld`, `unobserved_action_count` and `transcript_digest`,
  even when the causal deltas and `causal_training_digest` stay fixed.
  A caller that serializes the whole receipt into selection features can
  thereby access hindsight-bearing metadata.
- No unauthorized adoption or real future-label use was observed: the risk
  was identified in this unprivileged reference API, not in a production caller.

## Limited fix

The frozen, typed `frozen_credit_view` contains only `arm`,
`deltas`, `matched`, `expired`, `causal_training_digest`,
`authority=DENY_ALL` and `qualification=SHADOW_ONLY`. It excludes
all three hindsight-bearing full-audit fields. The existing full
forensic receipt and its verification path remain unchanged. This
redaction is not an Owner signature, prevents no direct access to the
forensic function, and does not qualify a candidate for deployment.

## Executed local evidence

On HeptaRuntime host `ai395`, in a fresh isolated sparse Git checkout
at the exact parent (not another agent's dirty worktree):

- RED: `python3 -m unittest -v test_frozen_credit_view.py` failed import of
  the required new projection, as expected; `FROZEN_CREDIT_VIEW_RED.log`.
  Measured **0.04 s wall / 0.04 s user CPU / 23,424 KiB max RSS**.
- GREEN: `python3 -m unittest discover -s . -p 'test*.py' -v`:
  **55/55 PASS**, `FROZEN_CREDIT_VIEW_GREEN.log`.
  Measured **0.04 s wall / 0.03 s user CPU / 22,968 KiB max RSS**.
- New regression coverage includes 32 deterministic future-only feedback
  suffix mutations, observed-zero vs absent, four credit ablations, type
  guard/frozen dataclass, and exact omission of the dangerous audit fields.
- No training, GPU compute, independent evaluator, production Owner,
  real ACT/CTRL effect, adoption, or cold restart was run. Local times
  are small Python test costs only; CI times may differ.

The prospective experiment still needs original Owner-attested causal
receipts, an independent future evaluator, real sparse/dense feedback and
full costs; the A→B→NoUpdate/Adopt→different C→cold recovery and Core×NDU
2×2 effectiveness gates remain **HOLD**.

# P0 physical-study CI owner: single dispatcher

The production-independent Granite 97M / mmBERT-small pretrained study
is executed by **one** PR-scoped caller:

- `.github/workflows/hepta-p0-compact-pr-trigger.yml` listens only to
  P0 study source and CI changes, and calls
  `.github/workflows/hepta-p0-compact-physical.yml`.
- `hepta-p0-compact-physical.yml` is a read-only reusable/manual
  workflow with one exact fixed model/data profile.
- `hepta-ndu-tree-fbsde-gates.yml` runs P3/P4/P6 synthetic/numerical
  studies only. It must not also invoke the expensive real P0 study.

**Reason:** The former two parallel callers scheduled the same reusable
P0 workflow with a cancellation concurrency group. On 2026-10-14,
run `38569348185` reported its P0 subjob cancelled while
`38569348410` was separately queued. This is a CI orchestration defect,
not a model inference failure, and not evidence of a model quality result.

`test_p0_single_ci_owner.py` prevents reintroducing a duplicate PR
invocation, while preserving `contents: read`, `actions: read`, complete
raw pre-score seals and `if: always()` failure evidence uploads.

**Qualification posture:** Draft, shadow, DENY_ALL; no model selection
or production permission. A queued/in-progress job is not a pretrained
result. Only an exact-run completed job, saved model receipts,
independently recomputed labels/scores and separately validated
`blocking-ci`/security status are eligible for review. PR #1775's
historical Laya/Gemma scores do not establish a fair four-model winner.

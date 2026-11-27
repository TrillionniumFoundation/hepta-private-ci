# P0 original-case replay for Hepta 2×2 × 6 Group research

Date: 2026-10-15. **RESEARCH / DRAFT / SHADOW / DENY_ALL.**

**Frozen physical source**: `research/group-feedback-factorial-20261015@d16fb15ef9d15a83dffa0886438d3e9432f97b66` (PR #2367).
**Frozen six-summary parent**: `research/group-feedback-six-cohort-audit-20261015@f1cc3b12733df16d6fbb9bbf60c4eecd09cef13e` (PR #2369).
**Original physical workflow run**: [#38738835065](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38738835065).

## Verified defect in the evidence boundary

The prior `group_feedback_factorial_aggregate.py` validates exactly six
**already summarized** `external-recheck.json` records. It does not itself
re-open the four original `protocol/report/observations/teacher/encoder/System2`
records and all five original Head/initial checkpoint archives per original
factorial run. Thus a passed aggregate is only as strong as its prior archived
summary and the provenance of those original single-run reviews.

This child adds a complete fail-closed *source and raw receipt replay* layer;
it does not change any trained model weights, original tasks, research model
runners, native NDU, or production authority.

## Added

- `group_feedback_factorial_raw_replay.py` requires exactly six original
  same-`run_id` GitHub artifact directories for 3 fixed seeds × 2 frozen
  optimizer profiles. Mixed or missing run names are rejected.
- Each block requires **four** complete raw arms with source protocol,
  original training report, original predictions, TRAIN teacher, frozen
  Encoder and raw System2 traces, plus all five original Group
  `safetensors` files. **276 original files** (6 × [4 × 11 + 2]) are
  SHA-256 enumerated, bounded and read before and after independent audit.
- The original `review_factorial` runs again over all four original arms
  in each of the six blocks. That invokes the existing stdlib single-run
  model-checkpoint / source / trace / public-label / work reviewer **24 times**.
  Independently recomputed result must equal *both* original archived
  `factorial-independent-review.json` and `external-recheck.json`.
- The existing `audit_six` then independently recomputes all six
  cross-factor summary/cost conditions. No source-run artifact is silently
  substituted with a synthetic one.
- A separate `hepta-group-feedback-raw-replay.yml` executes PR-path
  source-only negative tests **and an original-run replay job on the Draft
  PR**. Before fetching artifacts, the replay job authenticates the original
  GitHub run metadata as the frozen push SHA/branch/workflow with
  **status completed AND conclusion success**. While the original run is
  queued/failed/cancelled, the replay job explicitly fails (this is an
  intended scientific blocker, not a successful skipped physical review).
  The failed PR job can be retried against the same source SHA once that
  original run really succeeds, without changing the protected main branch.
  A manual dispatch remains separately described by the workflow, but it
  is not the only executable entrypoint.
- Only sanitized raw-file SHA inventory and independent replay receipts are
  uploaded. No original publisher weights, media or original private labels.

## Local mechanism test result

A local isolated Python 3.13 mirror exercised **7 adversarial original
archive replay tests in ordinary Python and 7 in `python -O`**, including
missing original checkpoints, absent/mixed run IDs, symlinks, conflicting
archived audit results, malformed JSON and a forced original-review failure.

The broader isolated mirror executed terminal-evidence, independent
sampler/feedback, four-arm, six-block, and raw-replay suites: **30/30
ordinary and 30/30 optimized tests**. Original source modules not present
in the mirror were replaced with explicit read-only stubs; Torch used the
installed CPU distribution. These tests establish *control-flow and
structural denial mechanics* only, not an exact-full-repository test or
physical pretrained outcome. The exact new GitHub source HEAD and
prospective-merge CI must be separately checked.

## Reproduction when the physical run completes

From a fully checked-out copy of this child research branch, with a
read-only GitHub CLI token:

```sh
gh api repos/TrillionniumFoundation/hepta-private-ci/actions/runs/38738835065
# Verify actual completed SUCCESS, event=push, name, and exact source SHA.

gh run download 38738835065 \
  --repo TrillionniumFoundation/hepta-private-ci \
  --dir /sealed/original-run-38738835065

python -S qualification/stem-cell-v1/group_feedback_factorial_raw_replay.py \
  --artifacts-root /sealed/original-run-38738835065 \
  --run-id 38738835065 \
  --source-commit d16fb15ef9d15a83dffa0886438d3e9432f97b66 \
  --output /sealed/independent-original-raw-replay.json
```

Passing this audit would establish internal archive and source consistency,
not independent model execution attestation, future task generalization,
equal full-resource comparison or NDU causal superiority. True future
source-disjoint natural tasks and independent outcome owners are still
needed before selecting any Cell, Stem or learning policy.

**NO MAIN MERGE · NO MODEL PROMOTION · NO CELL EFFECT AUTHORITY · DENY_ALL.**

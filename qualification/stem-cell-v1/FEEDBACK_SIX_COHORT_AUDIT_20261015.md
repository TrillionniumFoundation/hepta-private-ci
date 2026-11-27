# P0: Independent six-block evidence gate for Hepta Group 2×2

Date: 2026-10-15. **DRAFT · SHADOW_ONLY · DENY_ALL · NOT A PRODUCTION SELECTION.**

Exact parent: `research/group-feedback-factorial-20261015@d16fb15ef9d15a83dffa0886438d3e9432f97b66` (PR #2367).
The original *paid* physical workflow run triggered by this parent is [#38738835065](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38738835065). Its results must be checked by exact source SHA and actual jobs; a queued or unexecuted job is not physical evidence.

## Motivation

The physical research matrix executes four TRAIN conditions for each of seeds
`41/47/53` and optimizer regimes `sgd_v1/adam_v1`. Each individual four-arm
receipt is validated by the existing independent, model-free single-run replay.

Do not combine six summaries naively into a larger independent sample:
the task generator, repeated seeds, source families and original checkpoint
are *not* an independently sampled future natural-task population. Only a
descriptive matched within-(seed, optimizer, source-cohort) comparison is justified.

## This child

- `group_feedback_factorial_aggregate.py` requires **exactly six** separately
  reviewed `external-recheck.json` files and correct original (seed, regime)
  binding. No missing, duplicate or substituted experimental slot is allowed.
- Each report must carry four distinct protocol digests; `DENY_ALL`, no
  production selection, no externally verified future efficacy, and no equal
  total-compute claim.
- Independently recompute the integer paired rescued/harmed identity for
  every text/direct, fixed System2 and native NDU evaluation mode, and
  report the 2×2 interaction as an *exact integer count*:
  `(guarded_no_verifier - legacy_no_verifier) - (guarded_oracle - legacy_oracle)`.
  This is a descriptive difference-in-differences, **not** a causal effect
  estimate without justified counterfactual assumptions.
- Require actual lifecycle/Encoder/teacher/critic/train accounting on all 24
  experiment arms. Sum **actual lifecycle CPU once per original arm**; online
  CPU nested in lifecycle is not added a second time. Reject unknown or
  mismatched training oracle counts and terminal-withholding evidence.
- Output explicitly encodes `winner_selected=false`,
  `future_natural_task_efficacy_proven=false`,
  `equal_compute_demonstrated=false` and
  `repeated_seed_measurements_not_independent_future_tasks=true`.
  No model load, NDU authority, Cell promotion or executable effect is added.

## Replay from six successfully finished exact-run artifacts

Only after the parent run's full job results and independent original
receipts are available, download **one same-commit run's** six named artifacts
without mixing canceled, different-commit or partial attempts:

```bash
# Download artifacts from the exact completed original research run.
gh run download 38738835065 --repo TrillionniumFoundation/hepta-private-ci \
  --dir /sealed/factorial-original-artifacts

python -S qualification/stem-cell-v1/group_feedback_factorial_aggregate.py \
  --root /sealed/factorial-original-artifacts \
  --output /sealed/six-block-independent-review.json
```

If source-run artifacts are missing, model jobs failed or were canceled,
or the original checkpoints/source cannot be reviewed, **do not** transform
this into a green result. Validate the original run/commit provenance
separately; naming/digest checks do not independently authenticate a host.

## Real local verification (independent from hosted model execution)

Actual local Python test run using exact uploaded Git object bytes:

- `group_feedback_factorial_aggregate.py`: Git blob
  `02b8365fc53df07ba4e58f2397cf19a6653690b5`.
- `test_group_feedback_factorial_aggregate.py`: Git blob
  `416a29e5050c034c5428e6b9efbe1b384a92fe0b`.
- **6/6** tests in normal Python and **6/6** with `python -O`; both
  source files compile with `py_compile`.
- Local original strict-JSON read contract was exercised by a source
  compatible read-only shim (the full-repository independent reader must
  still pass exact-head verification). The tests are synthetic positive
  and tampered-row cases; they are **not real pretrained Group measurements**.

The parent workflow's local mechanism suite and original full pretrained
24-candidate job statuses are separate and must never inherit green from
this child's six-block reviewer tests.

**NO_MAIN_MERGE · NO_PRODUCTION_GRANT · NO_10T_100T_EQUIVALENCE.**

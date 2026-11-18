# Current-policy recovery readout

The current-policy runner already saves actual per-attempt model requests, outputs and business verifier observations. Its aggregate scores do not distinguish recovery after an executed failure from a retry after an invalid action. This readout adds that distinction without running another model or verifier.

`scripts/cell_experiments/onpolicy_readout_v4.py` exposes `summarize_collection(collection, records, expected_model_digest, maximum=2)`. Pass the exact prepared records in their retained order and the model digest selected for that collection. For shadow collection use `maximum=1`; its outcomes stay unmeasured. For authored-teacher collection, zero student calls remain zero observed student tasks. The final `post-update-A/COLLECTION.json` is measured separately from both training rounds.

The returned denominators cover all first failures, executed first failures, and first actions rejected before execution. Each contains the number recovered, failed tasks, tasks with a retry, and a rate that is null when the cohort is empty. Actual model calls, verifier calls and input/output tokens are reconciled against every retained step. A measured failure ending before the supplied attempt cap is rejected. Candidate, task, request/feedback, step receipts and summary bindings are checked before any result is reported.

## Scope

This utility verifies consistency of supplied records. It does not authenticate their producer, establish independent sources or new tasks, match full system cost, certify native owner adoption, or confer FinalUse or reward eligibility. Repeated attempts are not independent tasks. Existing old A/B development panels remain exposed. The readout deliberately lives outside `online_v4` so the frozen runner's source inventory is unchanged.

## Validation

Four regression tests passed with no failures, errors or skips. They use scripted model outputs and actual repository business verification: executed failure versus invalid action, unmeasured shadow and empty denominators, changed identities/counts/receipts, and missing required retries. See `TEST_OUTPUT.txt` and `VALIDATION.json`.

`just fmt` passed from `codex-rs` using the exact upstream justfile, formatter, scripts project and frozen Ruff lock in an isolated formatting snapshot. The default macOS Python was too old on the first invocation; the retained successful invocation selected installed Python 3.14.3 through PATH. Formatting preserved the tested AST. Source base: `eb56c51e4e73b0d466795b257a547ab93a0baa63`.

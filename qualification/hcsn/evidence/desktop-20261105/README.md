# HCSN desktop CUDA follow-up — current snapshot, 2026-11-05

**The corrected v2 controller is running and waiting for its pinned runtime. Qualification remains open: 0/170 completed CUDA training runs and 0/20 full-budget B audits.** The actual progress is dated **18:01:19 UTC**, with `stages=[]`; the separate process observation at **18:02:27 UTC** confirms the job is running. The executable source is `f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b`. [Current status](campaign-v2/STATUS.json), [campaign explanation](campaign-v2/README.md) and [actual launch/progress chain](campaign-v2/campaign-runtime-launch.json) keep these scopes separate.

This snapshot appends to the independent `research/hcsn-desktop-evidence-20261105` branch based on `716b7d6354bead8517527a25d66871e9ddaf4056`. The source branch `research/hcsn-hx-20261105` retains its own commit and [PR #4873](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4873) CI identity. The earlier desktop [STATUS.json](STATUS.json) and [campaign-v1 snapshot](campaign-v1/STATUS.json) remain dated historical evidence.

## Corrected executable identity; v1 retained as history

A concrete admission defect was found before v1 entered any research stage. Official PyTorch 2.8 stringifies its CUDA UUID without a `GPU-` prefix, while the previous code compared that string directly with the prefixed physical identity. The old fixture failed to represent the actual API. The [review correction](campaign-v2/v1-review-correction.json) names the missed defect and preserves the earlier reviews.

The corrected source changes only device/NVML identity handling and focused tests in three package files. It uses strict full-UUID parsing, retains raw and canonical evidence, checks same-device readback, and refuses malformed/MIG/ordinal identities. Original numerical functions, thresholds and training budgets are unchanged. The [source publication](campaign-v2/candidate-source-publication.json) binds commit `f355cfe…`; the [actual NVML comparison](campaign-v2/nvml-uuid-lookup.json) resolved both bare and canonical forms successfully on this host. The observed physical-energy limitation remains independent of that correction.

v1 was [cancelled](campaign-v2/campaign-v1-cancellation.json) at **17:36:26 UTC**, with durable exit 2, zero stages and zero completed CUDA runs. Its [terminal record](campaign-v2/campaign-v1-terminal.json), source, bundle and prior 28-payload snapshot remain unchanged. Its former waiting state and static approvals are historical; the v1 runtime bundle must not be used for new qualification.

## What the observed v2 deployment establishes

| Item | Evidence at the recorded time |
| --- | --- |
| Actual device | Previously observed RTX 4060, physical UUID `GPU-a33875b7-7eb7-679e-df08-19227d3decee`; finding this host does not upgrade the original zero-device cloud result. |
| v2 staging | [Successful durable receipt](campaign-v2/campaign-runtime-staging.json): 39 runtime files, 10 existing task dependencies, original 23-file and candidate 26-file Python sources verified. |
| Controller | Job `1a1acdd69f2-fc05-5757`; running process observed at 18:02:27 UTC, waiting progress at 18:01:19 UTC; no research stages started. |
| Numeric base | [Raw READY](campaign-v1/numeric-runtime-ready.json) verifies the six pinned numeric packages and records no model computation. |
| Mamba wheels | [Raw READY](campaign-v2/mamba-wheels-ready.json) and [safe verification summary](campaign-v2/mamba-wheel-verification-summary.json): 17 complete wheels, 706,688,727 compressed bytes, finished at 17:29:27 UTC. Installation/import readiness is pending. |
| Torch download | [Safe dated handoff](campaign-v2/runtime-environment-handoff.json): 1,938,178,509 / 3,918,339,031 bytes completed at 17:55:42 UTC; no pinned runtime READY or model test. |
| Current-source CI | [17:54:19 UTC observation](campaign-v2/ci-candidate-latest.json): run [42078258351](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42078258351), job `127424159520`, queued with runner ID 0 and no steps. The previous source's CI was cancelled. |
| Physical power/energy | [Actual NVML and FieldValues queries](campaign-v1/nvml-field-values.json) returned `NOT_SUPPORTED`. No GPU joule result exists; missing readings are never zero-filled. |

The [frozen v2 tool guide](../../../../tools/hcsn/gated-campaign-v2/README.md) and [archive inventory](campaign-v2/archive-inventory.json) identify the exact deployed ZIP and manifest. Task campaign ownership and shared installation locks serialize this task's work; they do not reserve all host resources. The declared allocator fraction is .5. The controller waits up to 24 hours for dependency readiness, verifies source/config/profile identity, and stops on a failed gate without automatically retrying training or reducing budgets.

## Fixed experiment and unresolved scientific claims

The [predeclared plan](campaign-v2/campaign-runtime-plan.json) retains **17 models × 5 seeds × 2 tasks = 170 runs**, including **20 B runs**, each with 400 updates, batch 64, length 64, hidden width 64 and the original data splits. Policy 0 is uniform original B after a successful actual full-shape CUDA probe. Policy 1 is uniform segment-1 rematerialization only after actual original-B graph OOM, complete fixed CPU/CUDA parity and candidate full-shape probes. No task quality selects this policy. None of these execution gates has passed in the captured waiting snapshot.

Available local preparation checks are **52 passed / 57 skipped of 109 methods**; strict Torch checks are unavailable in that local environment. Eleven controller controls and 25 external-audit admission controls passed. Their [receipts and independent reviews](campaign-v2/README.md#actual-preparation-checks-and-remaining-blockers) concern source/identity/ownership contracts, not CUDA numerical, memory or performance eligibility. The [full-B audit protocol](campaign-v2/full-b-audit-protocol.md) preserves exact factor-1 replay, fixed factor-2/4 inference microbatches, all 1024 inputs and all 20 identities; it adds no convergence pass threshold or training credit.

Original B evidence remains unfavorable for the unresolved claims: mass error was at most approximately `3.5763e-7` on the trained grid and `6.5566e-7` across refinements, with zero observed escape, but filtered hidden-trace RMS differences were **0.1660–0.1977**. This metric is not final readout-prediction RMS. Mean test MSE **0.3702743** exceeded the constant predictor's **0.36800548**. The [original trained-weight audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/28a61d14ea7d4c3b3c515ab57b29c98de22e5673/qualification/hcsn/evidence/cloud-20261105/attempt-safe/population-audit.json) supports mass conservation and replay; resolution independence and task advantage remain unestablished.

Actual full-shape A/B/Mamba-2 CUDA execution, full-budget timing and memory, the 170-run matrix, all 20 B audits, physical energy and final-source GitHub CI still require their own completed evidence. Later partial, failed or successful receipts are appended without rewriting these dated observations.

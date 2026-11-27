# HCSN corrected campaign v2 — dated execution evidence

**Qualification remains open: 0/170 completed CUDA training runs and 0/20 full-budget B audits.** The corrected v2 controller started at 17:59:19 UTC on 2026-11-05. Its progress at **18:01:19 UTC** is `waiting_for_pinned_runtime`, with no research stages. The separate process observation at **18:02:27 UTC** records the durable job as running. This is an active wait for dependencies; it does not establish a Torch, CUDA or training pass. See [STATUS.json](STATUS.json), [raw progress](campaign-runtime-progress-initial.json) and [launch observation](campaign-runtime-launch.json).

This snapshot appends to the independent `research/hcsn-desktop-evidence-20261105` evidence branch based on `716b7d6354bead8517527a25d66871e9ddaf4056`. The executable source remains independently identified at `f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b` on `research/hcsn-hx-20261105`, [PR #4873](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4873). Publishing this evidence does not change that source identity.

## The v1 UUID defect and its correction

The pinned [PyTorch 2.8 implementation](https://github.com/pytorch/pytorch/blob/v2.8.0/torch/csrc/cuda/Module.cpp), Git blob `b44ce311ecd9245a97ee52513d04d187fb77ff80`, stringifies its CUDA UUID as bare grouped hexadecimal. v1 compared that value directly with the `GPU-`-prefixed physical identity. The earlier synthetic fixture did not represent this actual API value. The [independent correction](v1-review-correction.json) explicitly records the defect and the limitation of the earlier static reviews.

Only three research-package files changed from source `fe1def4…`: device identity handling in `execution.py`, NVML identity handling in `benchmark.py`, and focused tests. The new shared parser accepts a complete bare or `GPU-`-prefixed UUID, canonicalizes lowercase hexadecimal, preserves the raw value, and rejects malformed, partial, ordinal, MIG and multiple-device identities. SMI and NVML readback must name the same physical device. Numerical functions, original configuration bytes, budgets and tolerances remain unchanged. The [publication receipt](candidate-source-publication.json), [candidate manifest](execution-candidate-manifest.json) and [fix notes](candidate-uuid-fix.md) bind the source and scope. The candidate manifest retains its original preparation-time fields; the later publication receipt establishes the actual commit.

The real [NVML lookup comparison](nvml-uuid-lookup.json), with [durable-job provenance](nvml-uuid-lookup-provenance.json), resolved **both bare and prefixed UUIDs** to the same canonical string on this device. It performed no Torch or GPU model computation. Thus the measured energy-counter limitation remains independent of the UUID spelling correction.

The old v1 controller was [cancelled](campaign-v1-cancellation.json) before any model stage. Its [terminal receipt](campaign-v1-terminal.json) records interruption at **17:36:26 UTC**, durable exit 2, `stages=[]`, and 0/170 completed runs. All 28 payload files from the earlier v3 publication packet are retained unchanged under [campaign-v1](../campaign-v1/README.md) and the v1 tool path. Their earlier waiting state is a dated historical observation. The v1 bundle and prior static approvals must not be used as current executable qualification; the correction is explicit rather than overwriting the earlier evidence.

## Actual v2 deployment and runtime state

| Evidence | Recorded state |
| --- | --- |
| Remote staging | Job `1a1acdb5dc1-fc05-5750`, exit 0, complete and durable output; 39 runtime files, 10 task dependencies, 23 original and 26 candidate Python files verified. |
| Controller | Job `1a1acdd69f2-fc05-5757`, unique key `hcsn-cuda-r1-gated-full170-campaign-v2`; running at the separate 18:02:27 UTC observation. |
| Research progress | 18:01:19 UTC: waiting for pinned runtime, zero stages, 0/170 runs. |
| Numeric environment | The [unchanged raw READY](../campaign-v1/numeric-runtime-ready.json) verifies the six numeric package versions on the new task volume. It contains no model computation. |
| Mamba artifacts | [Raw wheel READY](mamba-wheels-ready.json): all 17 wheels verified by 17:29:27 UTC, 706,688,727 compressed bytes. Installation and import testing remain pending. |
| Torch artifacts | [Safe handoff](runtime-environment-handoff.json): 1,938,178,509 / 3,918,339,031 bytes completed at 17:55:42 UTC; verified-range download still in progress. No pinned Torch runtime READY is claimed. |
| Free space | Controller's 18:01:19 UTC progress: task data 32,389,644,288 bytes; control filesystem 3,549,204,480 bytes. These are dated observations, not reservations. |

The [staging receipt](campaign-runtime-staging.json), [staging terminal job](campaign-staging-job.json), [claim](campaign-runtime-claim.json) and [predeclared plan](campaign-runtime-plan.json) preserve the actual deployment chain. The v2 ZIP is 139,193 bytes, SHA-256 `a9d5d39155b0d93a89c246c69cb82960b5b9308b6150dd1809486e10791791f5`; its manifest is `dafb594b4d6af2ade6915b7767369f1c5c69c7b4a06232cae75855cf6be6f531`. See [archive inventory](archive-inventory.json) and the [frozen runtime files](../../../../../tools/hcsn/gated-campaign-v2/README.md).

The [safe whole-wheel summary](mamba-wheel-verification-summary.json) retains each of the 17 artifact hashes and metadata hashes and identifies the complete 83,556-byte verification report by SHA-256. The large report and raw installation logs are outside this publication set. The [frozen handoff](runtime-environment-handoff.json) records separate observation times and source hashes while omitting installer owner home paths and signed download URLs. Its `TORCH_READY` and `MAMBA_READY` contract fields describe future requirements; they do not override the explicit pending state.

## Fixed research budget and gate chain

The [actual predeclared plan](campaign-runtime-plan.json) retains **17 models × 5 seeds × 2 tasks = 170 identities**, including all 20 B identities. Each completed run uses 400 Adam updates, batch 64, sequence length 64 and hidden width 64: 25,600 examples and 1,638,400 tokens. Data seed 271828, train/validation/test counts 4096/512/1024, learning rate .001 and dt .1 remain fixed. Original full-config SHA-256 is `7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a`.

The controller first verifies immutable source/config/runtime identities and waits at most 24 hours for pinned dependency readiness. It holds this task's exclusive campaign lock and the environment's shared installation lock during experiments. These locks do not reserve the entire host or GPU. The declared CUDA allocator fraction is .5; caches and temporary files are on the task data volume. No failed training stage is retried automatically, and no budget is reduced.

After strict baseline 95/95 and candidate 109/109 CPU checks with zero skips, the ordered gates require full-shape original A/B probes. Policy 0 uses original B if that probe succeeds. Policy 1 requires an actual original-B graph OOM, both fixed complete 16-case CPU/CUDA parity results, and both segment-1 candidate B probes. The selected policy applies uniformly to all 20 B identities without using task quality. The original Mamba-2 probe follows. The separate historical smoke diagnostic precedes the immutable full matrix, and the full-B audit follows that matrix. This is a declared chain; **none of these stages has run in the captured v2 progress**.

The [full-B protocol](full-b-audit-protocol.md) and [package](full-b-audit-package.json) retain same-device exact factor-1 replay at batch 64. Factors 2 and 4 use fixed inference batch 8, reconstruct the original blocks of 64 for MSE, and preserve every one of the 1024 inputs and all 20 requested identities. Hidden-trace RMS, final-prediction RMS, mass/escape, costs and failure/unavailability remain explicit. There is no added convergence threshold and no audit credit toward the 170 training runs.

## Actual preparation checks and remaining blockers

[Local candidate checks](candidate-available-controls.json) discovered 109 methods: **52 passed, 57 skipped, zero failures/errors**. The [strict local receipt](candidate-strict-unavailable.json) is unavailable with zero tests run because Torch is absent in that preparation environment. [Controller controls](controller-synthetic-controls.json) passed 11 groups; [external-audit admission controls](audit-synthetic-controls.json) passed 25 cases. The [source-faithful UUID regression](bare-uuid-regression.json) reproduces v1 rejection and v2 correction without real Torch/CUDA. [Core](uuid-independent-review.json), [audit](audit-independent-delta-review.json) and [bundle](bundle-independent-review.json) reviews bind these exact sources. These are preparation results and do not establish numerical parity or CUDA eligibility.

At **17:54:19 UTC**, [HCSN CI run 42078258351](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42078258351), job `127424159520`, remains queued with runner ID 0 and no steps. The [transition](ci-source-transition.json) records cancellation of the preceding `fe1def4…` CI run; the [dated current observation](ci-candidate-latest.json) does not show a pass.

The actual [NVML power/energy and field probes](../campaign-v1/nvml-field-values.json) returned `NOT_SUPPORTED`. Physical GPU energy remains missing, never zero or an estimate. No full-shape CUDA peak-memory, runtime, full-budget or physical-energy result is added by this snapshot.

The original [trained B smoke audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/28a61d14ea7d4c3b3c515ab57b29c98de22e5673/qualification/hcsn/evidence/cloud-20261105/attempt-safe/population-audit.json) remains adverse: maximum trained-grid mass error `3.5763e-7`, maximum across refinements `6.5566e-7`, zero observed escape, but filtered hidden-trace RMS differences were **0.1660–0.1977**. This metric is not final readout-prediction RMS. Mean test MSE **0.3702743** exceeds the constant predictor's **0.36800548**. Conservation and replay are supported; trained-weight resolution independence and task advantage remain unestablished. The 170-run and 20-B denominators are unchanged.

The [publication privacy scan](privacy-scan.json) covers selected text and all members of both preserved runtime ZIPs. Later actual execution receipts must be appended independently, including partial or failed outcomes; this dated waiting snapshot remains intact.

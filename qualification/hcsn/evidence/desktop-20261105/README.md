# HCSN desktop CUDA follow-up — 2026-11-05

**Overall qualification remains OPEN.** A reachable project host has a physical NVIDIA RTX 4060, so the earlier cloud instance's zero-device result no longer exhausts the available hardware paths. The compatible tensor runtime is still being prepared. This snapshot contains no completed CUDA preflight, full 170-run experiment, GPU peak-memory measurement or physical GPU energy result.

The current work also identified and locally fixed a concrete CI artifact-retention defect: the workflow uploaded aggregate JSON files but omitted the sibling directory containing validation-selected weights and immutable attempt journals. Publication and final-candidate CI execution are still pending.

This evidence snapshot accompanies [PR #4873](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4873). It records completed observations and explicitly pending execution. [STATUS.json](STATUS.json) contains the source identities and acceptance state; [ci-original-observation.json](ci-original-observation.json) preserves the last observed original CI job state. The result branch allows additional immutable observations to be saved while the research source branch retains its own CI identity.

## Fixed research identity and unchanged budget

| Item | Identity or budget |
| --- | --- |
| Research branch | `research/hcsn-hx-20261105` |
| Existing evidence commit | `28a61d14ea7d4c3b3c515ab57b29c98de22e5673` |
| Existing executable-source commit | `06052c42c6075f888d953397546b75b4ddf247f3` |
| Full configuration SHA-256 | `7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a` |
| Full matrix | 2 tasks × 17 encoders × seeds 0–4 = **170 runs** |
| Data | Seed 271828; train / validation / test counts 4096 / 512 / 1024 |
| Full input and model sizes | Batch 64, sequence length 64, 2 input channels, hidden width 64; B retains 32 bins |
| Training budget | 400 Adam updates; 25,600 examples and 1,638,400 tokens per run; learning rate .001; dt .1 |

The previous [full CUDA accounting](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/28a61d14ea7d4c3b3c515ab57b29c98de22e5673/qualification/hcsn/evidence/cloud-20261105/attempt-safe/full.json) remains historical evidence: **0 completed, 0 failed, 170 unavailable** on the original cloud instance. Finding another host does not convert those unavailable attempts into completed experiments. No fresh desktop matrix result is claimed here.

## Actual GPU and counter observations

The configured operator reached the project host `desktop` and obtained these physical-device observations:

| Observation | Recorded result |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4060 |
| UUID | `GPU-a33875b7-7eb7-679e-df08-19227d3decee` |
| Driver | `580.178.04` |
| Reported total VRAM | 8188 MiB |
| Reported free VRAM at the availability snapshot | 6093 MiB; this is neither a reservation nor a benchmark peak |
| NVML initialization and device-handle lookup | Succeeded; one GPU enumerated |
| NVML power usage | Return code **3: NOT_SUPPORTED** |
| NVML cumulative energy | Return code **3: NOT_SUPPORTED** |
| `nvidia-smi` power draw | `N/A` |
| CPU RAPL | Counter paths observed, reads denied; those package counters would not measure GPU energy |

The numeric zero fields returned alongside NVML errors are invalid outputs, **not zero-watt or zero-joule samples**. The reported 115 W power limit is a configuration value and is not used to estimate energy. Physical GPU energy qualification therefore remains open on this observed driver/device combination. A second [FieldValues probe](nvml-field-values.json) queried instantaneous power, average power and both energy fields twice. All eight individual field results were `3 / NOT_SUPPORTED`, despite the aggregate API returning zero. Each failed field retains `value=null`. No task GPU computation was performed by that probe.

The cloud executor still has no exposed NVIDIA device. The default desktop interpreter and the two specifically inspected existing environments did not contain PyTorch. These checks are bounded observations; they do not establish the absence of every possible environment on that machine.

## Runtime and CUDA work remain pending

The isolated numeric base is installed and its exact versions were checked: NumPy 2.3.5, SciPy 1.17.0, ncps 1.0.1 and NVIDIA `nvidia-ml-py` 13.610.43. The official Torch/CUDA dependency set is pinned to 25 wheel artifacts totaling 3,918,339,031 bytes; the independent Mamba dependency set has 17 artifacts totaling 706,688,727 bytes. Target versions are Torch 2.8.0+cu128, Triton 3.4.0, official Mamba 2.3.1, causal-conv1d 1.5.4 and Transformers 4.57.1. Downloads have encountered premature EOF and slow responses. Durable range checkpoints, whole-file hashes and wheel metadata gates preserve identity across recovery. No Torch-ready, Mamba-ready, forward/backward or full-matrix result exists at this snapshot. Downloaded ranges do not constitute installation or CUDA validation.

The standalone preflight is prepared to run A (`hx_dual`), B (`population_flux`) and official `mamba2` in separate processes. It uses the original training-data generator, seed 0 and the original `seed + 1729` first-batch sampler, with the full `(64,64,2)` input and hidden width 64. Its scope is one forward / loss / backward / gradient clip / Adam step. It does not evaluate validation or held-out data and does not count toward the 170 registered runs.

The prepared admission code has four independently executed controls for source drift, configuration drift, existing receipts and concurrent receipt claims. They passed without PyTorch or CUDA and qualify only those rejection paths. They provide no CUDA numerical, memory or performance evidence. The current reviewed probe SHA-256 is `70331f392c9695e0522da52817b3511b544304a6f4e23a169a016a07ea9f1285`.

Any allocator-fraction cap used for the preflight must remain in its receipt. Such a cap limits the process's PyTorch allocator; it does not reserve the GPU or account for all external CUDA allocations. A one-step peak also omits the full benchmark's validation/test residency and best-state copies, so it cannot close full-budget memory eligibility by itself.

## CI and the existing runner path

The original [HCSN run 42043926869](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42043926869), job `127301677224`, remains queued at the latest captured observation, with `runner_id=0` and no executed steps. It has no passing result or failure log. Its `ubuntu-24.04` job is the focused CPU research workflow; it is not a CUDA experiment.

The trusted [desktop availability probe](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39526325715) remains separate. Its fixed policy selects group `trillionnium-android-gpu` and checks runner name `desktop`, `workflow_dispatch` and `refs/heads/main`; it performs no checkout. Those trust conditions were preserved.

Within the checked local scope, no reusable runner registration file, running runner process or installed runner service was found. The current desktop operator CLI's repository-runner listing returned HTTP **403**, with the service message **“Sorry. Your account was suspended.”** Consequently, the remote registration count is **unknown**, not zero. This is a scoped observation about that configured CLI authentication path; it does not establish that every GitHub connection is unavailable, and it does not establish the cause of the hosted HCSN queue. The connected GitHub plugin continues to support its exposed repository operations.

## Concrete artifact-retention repair

`benchmark.main` writes the aggregate report and a sibling `hcsn-training-smoke.runs/` directory. The directory contains per-request indexes, immutable attempt start and terminal records, and the saved validation-selected weights. The old artifact pattern selected only top-level `hcsn-*.json` files. Downloading that artifact alone could not reproduce checkpoint-based auditing or preserve the complete attempt history after an interrupted benchmark.

The local workflow change preserves the JSON pattern and adds the exact sibling directory:

```yaml
path: |
  ${{ runner.temp }}/hcsn-*.json
  ${{ runner.temp }}/hcsn-training-smoke.runs/
```

The common artifact root preserves the report-relative checkpoint layout. The research algorithms, model list, seeds, data and budgets are unchanged. This fixes the retention configuration; actual final-candidate upload and download verification still require a completed CI execution.

## Isolated implementation candidate, still gated

The [candidate manifest](execution-candidate-manifest.json), [implementation notes](execution-candidate.md) and [patch](../../../../tools/hcsn/execution-candidate.patch) describe an unactivated source revision. It adds explicit population checkpointing policy 0/1, a declared CUDA allocator fraction, actual device/driver identity, allocated and reserved peaks, missing/nonfinite-gradient guards, and separate complete/incomplete/unknown energy accounting. The original population encoder, CPU exact-MSE check, CUDA-receipt comparison, and original full configuration remain unchanged. Derived execution policy does not reduce the 170 identities or training budget.

Actual preparation checks found 104 methods: **47 passed, 57 skipped, zero failed/errors**. Strict `--require-torch` actually exited 2 with zero tensor tests run because the preparation executor lacks Torch. These results do not establish tensor correctness. Activation still requires the original full-shape resource observation, the fixed CPU and CUDA parity checks, candidate full-shape validation and strict integration tests. The [resource review](full170-resource-review.md) records the additional recomputation and grid-audit costs without deriving a wall-clock estimate from hardware FLOPS.

## B's original adverse results are retained

The [trained smoke-weight audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/28a61d14ea7d4c3b3c515ab57b29c98de22e5673/qualification/hcsn/evidence/cloud-20261105/attempt-safe/population-audit.json) established exact original-grid replay and small mass error. It did not establish resolution independence or task advantage:

| Historical B observation | Result |
| --- | ---: |
| Maximum trained-grid mass error | Approximately `3.5763e-7` |
| Maximum mass error across refinements | Approximately `6.5566e-7` |
| Observed escape | 0 |
| Filtered hidden-output RMS changes under refinement | **0.1660–0.1977** |
| Mean trained-grid test MSE | **0.3702743** |
| Constant-predictor test MSE | **0.36800548** |
| Full-budget B audits | **0 of 20** requested runs |

The trained B mean MSE is worse than the constant predictor. Conservation and replay remain useful correctness evidence, but neither removes the output-resolution error or proves a learning advantage.

A fresh, untrained NumPy FP64 diagnostic separated spatial and temporal refinement while keeping effective refractory time .3. For one constant-drive case, the spatial-only trace difference was approximately .01249, while changing dt on the fixed coarse spatial grid produced approximately .15120. Successive joint refinements decreased from approximately .08357 to .04214 to .02187, with mass error below `5.6e-15`. These observations support further numerical diagnosis of discretization effects in that case. They do not qualify trained-weight resolution independence, a CUDA implementation or the full research budget.

The three original B smoke checkpoints were restored and their byte hashes verified. The new separable trained-checkpoint audit is prepared but has not produced fresh tensor-runtime results. No full-budget result, improved task score or reduced-memory benefit is inferred from preparing these tools.

## Remaining acceptance work

| Gate | Status at this snapshot |
| --- | --- |
| Reachable physical NVIDIA project GPU | Observed |
| Compatible pinned Torch / CUDA / official Mamba-2 runtime | Installation or compatibility validation pending |
| Actual full-shape A/B/Mamba-2 forward and backward | Pending; no completed receipt |
| Full 170-run CUDA matrix and 20 B audits | Pending; zero completed CUDA runs |
| Original-budget peak GPU memory and full cost | Pending |
| Physical GPU energy | Unavailable through the tested NVML calls; remains open |
| Final-candidate GitHub HCSN CI | Pending runner execution |
| Existing trusted runner execution path | Blocked on the observed configuration/authentication path |
| B trained-weight numerical convergence and task advantage | Not established; original adverse results retained |


## Reproduction inputs

The prepared standalone tools are outside `qualification/hcsn` so that they do not alter its recursive source hash. Original-baseline probes require the exact package at commit `28a61d14ea7d4c3b3c515ab57b29c98de22e5673`. The [tool guide](../../../../tools/hcsn/README.md) gives the pinned paths and execution scope. The [checkpoint origin](smoke-checkpoint-origin.json) binds the complete original 48-record smoke receipt and three B checkpoints to their repository paths and byte hashes.

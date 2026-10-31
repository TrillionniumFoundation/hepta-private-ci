# Round 7 training audit

This output audits the frozen checkpoints and training logs only. It does not inspect confirmation trajectories or estimate task-level superiority. Detailed per-fit evidence is in [TRAINING_AUDIT.json](evidence/TRAINING_AUDIT.json).

## Integrity and freezing

All 60 registered checkpoint hashes and all 108 sealed input hashes were checked. A fresh seeded initialization was reconstructed from the frozen model code, and every saved named parameter was compared independently. All registered frozen raw parameters had exactly zero elementwise movement. Reported final-versus-initial L2 values agree with those recomputed differences.

| Model | Frozen group | Fits | Stored / optimizer-eligible | Mean soft return before control | Mean after 30 control epochs | Mean change |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| clocked | boundary | 5 | 823 / 822 | 0.595511 | 0.618545 | +0.023035 |
| clocked | none | 5 | 823 / 823 | 0.596162 | 0.618614 | +0.022452 |
| continuous | none | 5 | 823 / 823 | 0.595550 | 0.618123 | +0.022574 |
| direct | none | 5 | 823 / 808 | 0.595050 | 0.617528 | +0.022478 |
| first_passage | boundary | 5 | 823 / 822 | 0.595142 | 0.618049 | +0.022907 |
| first_passage | content | 5 | 823 / 491 | 0.595173 | 0.615432 | +0.020259 |
| first_passage | dynamics | 5 | 823 / 812 | 0.594831 | 0.617902 | +0.023071 |
| first_passage | noise | 5 | 823 / 822 | 0.594974 | 0.618021 | +0.023048 |
| first_passage | none | 5 | 823 / 823 | 0.595292 | 0.618138 | +0.022846 |
| first_passage | recovery | 5 | 823 / 822 | 0.595352 | 0.618075 | +0.022723 |
| first_passage | reset | 5 | 823 / 821 | 0.595301 | 0.618087 | +0.022786 |
| first_passage_temperature | none | 5 | 824 / 823 | 0.595207 | 0.617945 | +0.022739 |

The recorded exact finite-graph soft return increased between control epochs 0 and 30 in 60/60 fits. 41/60 curves contain a decrease between recorded checkpoints: the optimized loss also includes both auxiliary regressions, and the registered final checkpoint is the final epoch, not the largest observed return.

## Gradient and capacity interpretation

Clocked and base first-passage cells expose gradients through their encoder, drive/leak/diffusion, boundary, reset, recovery, and readouts. The JSON retains separate maximum norms from regression and joint-control stages and independently measured parameter changes. A reported gradient is instrumented training evidence; this audit did not rerun all optimizer steps.

Continuous reset is a useful caution: it has zero pretraining gradient but can move under the joint auxiliary critic through unreachable refractory-state features. Recovery remains unchanged. The direct control stores 823 scalars and marks 808 optimizer-eligible, while its zero latent-feature columns remain unchanged; nominal parameter count is not effective function dimension. The temperature control stores 824 scalars but freezes diffusion, leaving 823 optimizer-eligible.

Freeze interventions refer to raw parameter groups. Freezing reset-center parameters does not fix their physical location if the boundary scale changes. Freezing drive weights does not freeze the upstream learned content. Noise overlaps the dynamics group. These controls test parameter-group contribution, not an isolated physical pathway.

## Training cost coverage

Five formal batch receipts account for 65 successful attempts and zero formal process failures, including the five rejected temperature fits. They record 2126.195325 CPU seconds and 3622.733616 summed wall job-seconds. The latter is not elapsed makespan because jobs overlapped.

The 60 registered fits account for 1867.691767 CPU seconds in per-fit training-component timers; rejected temperature fits add 246.765054 CPU seconds in the same narrower timer scope. Those components are already included in batch totals and must not be added again.

Six earlier smoke fits preserve 115.915722 seconds of training-component wall time, but have no complete process CPU/setup/serialization timers. An initial task-step failure before fitting also lacks timing. Interpreter startup/imports precede formal timers. These omissions remain unknown, not zero; complete end-to-end research cost is not closed by this audit.

Confirmation, statistics, conditional/native/broker/profile audits, packaging, and historical Rust build are outside this training-only ledger. Their costs belong in the separate experiment-wide accounting. Repeated copies of rejected checkpoint files are evidence copies, not new training attempts.

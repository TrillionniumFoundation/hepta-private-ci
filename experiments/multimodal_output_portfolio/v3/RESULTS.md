# v3 confirmation: executed feedback control and its limits

The registered primary comparison passes in the finite synthetic restoration benchmark. This is evidence for an executed, state-dependent generation controller under the declared disturbances. It does not establish a natural-data all-modal foundation model, general superiority of recursive or robust control, a global neural-training optimum, or production HEPTA deployment.

## Frozen experiment and independent review

Preregistration: `6ab6aa4107b33917580cc041bc36b6603dad8aaa`.
Implementation used for the only formal run: `9653b066563df803b6f18c0045c49b9f73312c50`.
Protocol SHA256: `5751624d7c55f0c50756979985682cbff652faea8534dc6422427043027c3afc`.
Formal directory: `hepta-v3-confirmation-001`. Seeds: 17, 29, 43.

The formal execution completed in 139.684 seconds wall time and 461.627 seconds parent process CPU time. Every recorded source byte was committed and remained unchanged. There were 6,144 distinct feedback worlds with eight arms (49,152 arm-world records), and 9,216 distinct source-evidence worlds with four arms (36,864 records). Paired arms reuse worlds; arm-world counts are not counts of independent observations. The bootstrap resamples seeds and paired worlds, with 1,000 replicates. Three training seeds remain a small sample of training variability.

The independent auditor reads saved tensors and executes the Linear/GELU/Sigmoid arithmetic directly. It does not import the neural implementation, controller, reporting or metrics modules for its neural replay and statistics. It verifies 41 artifact hashes, 31 frozen source hashes, the final native build receipt and binary, 49 unchanged historical experiment files, 12 Bellman trees / 11,520 states, all feedback/source outputs and all native exchanges. The source renderer is reused to reconstruct the benchmark's input and target data. Training gradients are verified from records and source, rather than by independently repeating optimization. See [review_confirmation.json](evidence/review_confirmation.json) and [audit_confirmation.py](evidence/audit_confirmation.py).

## Primary result

The contrast is `ndu_feedback - ndu_static` under nominal noise. Both arms use the same NDU-trained weights. The static depth is chosen before heldout execution using the same finite distribution, entropic objective and refinement penalty.

| Registered quantity | Result | Gate |
| --- | ---: | --- |
| Mean external loss difference | -0.27833614794504397 | Reduction at least 0.01: pass |
| Paired 95% CI | [-0.3506952419043328, -0.2263499531490681] | Upper bound below zero: pass |
| Online Linear MAC ratio | 0.9769562829189122 | At most 1.10: pass |
| Four outputs and feasible budgets | All checked records pass | Pass |
| Training seeds | 3 | Pass |

Across seeds, static mean loss is 0.3816903107 and feedback mean loss is 0.1033541627. The relative mean reduction is approximately 72.92%. This is the registered synthetic external loss, not a percentage gain in human-perceived quality. The MAC ratio excludes policy compilation, backward/optimizer arithmetic, nonlinear operations and IPC; it is not an end-to-end speedup claim.

## Executed mechanism

The initial map constructs a source-conditioned anchor. External finite-support noise corrupts the initial latent and each subsequent refinement. A learned conditional refiner contracts the residual toward the anchor. After each executed operation, the controller receives the current latent feedback and decides STOP or REFINE. Its information is the known-anchor residual, not a learned semantic confidence estimate. The source condition remains fixed during a generation trajectory.

Nominal NDU depth counts are 1,523 / 838 / 684 / 27 at depths 0 / 1 / 2 / 3. Thus 50.4232% of worlds refine at least once. There are 54 observed condition/depth groups with both STOP and REFINE on different current latents. All 90 NDU update steps record finite, nonzero gradients from the selected utility alone to the refiner, without an auxiliary anchor loss. Encoders, initial map and four decoders are frozen during this stage. The matched supervised arm starts from the same warmup weights and performs matching forward work.

The native Rust process executes 24,576 sessions and 126,322 requests. It owns action selection, exact budget charging, version checks, feedback acknowledgements and terminal output sealing. Python supplies the finite Bellman values and executes Torch operators. All actual latent/output digests bind to the native transcript. The combined Python/IPC/native request round trips total 6.9535 seconds; native process lifetime includes time waiting for Python and must not be interpreted as active CPU cost.

Native binary SHA256: `f3ae369208da0bc029c5e5b829b46a92867f7a69cc1d7fbfb35a212460d05eb3`.
Native transcript SHA256: `3d93717b138f9c747943577223aa65e961c14e6e4b09405420cd269c5101725e`.
These are local execution-integrity bindings. They are not authenticated production kernel attestations.

## Negative and secondary results

All comparisons below are descriptive secondary analyses, without multiplicity adjustment. Lower external loss is better.

| Nominal contrast | Mean loss difference | Paired 95% CI | Interpretation |
| --- | ---: | --- | --- |
| NDU feedback - matched supervised feedback | -0.0052347 | [-0.0107383, -0.0016783] | Small mean-loss advantage; tail and discrete quality advantages are not established |
| Recursive NDU feedback - myopic | -0.1205336 | [-0.3613265, 0] | Strict superiority gate not met |
| Robust NDU - nominal NDU feedback | +0.0454762 | [0, +0.1308527] | No mean-loss advantage |
| NDU feedback - no refinement | -0.4140118 | [-0.4617375, -0.3648731] | Restoration helps under the mandatory disturbance |
| NDU feedback - clean direct reference | +0.1029387 | [+0.0689252, +0.1459887] | Clean direct generation is better |

Seeds 17 and 29 produce identical recursive and myopic loss/depth arrays. Seed 43 contributes the continuation difference. Reporting the aggregate point estimate as a general recursive-control advantage would be unsupported. Under noise shift, robust minus nominal mean loss is +0.0076120, CI [0, +0.0238448]. The robust CVaR difference is -0.1073622, CI [-0.3169533, 0], which also fails a strict negative-upper-bound criterion.

The clean direct reference has nominal mean loss 0.0004154970. It bypasses the artificial corruption mechanism and is reported explicitly. The experiment therefore supports restoration after externally imposed disturbances, not the necessity of adding a noisy iterative process to a generator that can already emit the clean anchor.

## Shared failure and the value of new evidence

The source experiment calibrates three full joint failure regimes and compiles all 6,561 possible four-report histories. It avoids a conditional-independence assumption between corrupted sources. Direct output portfolios use a finite 331-point grid over eight semantic classes; the optional query executes a declared fixed witness fallback. These weights are not text/audio/image/video resource-allocation weights. This is a separate experiment from feedback restoration, not a demonstrated joint optimizer over source acquisition and generation trajectories.

| Source regime | Nominal quality | Robust without witness | Robust with witness | Witness alone |
| --- | ---: | ---: | ---: | ---: |
| IID | 0.8613281 | 0.1630859 | 0.9791667 | 0.9791667 |
| Correlation shift | 0.0992839 | 0.1650391 | 0.9762370 | 0.9762370 |
| All shared wrong | 0 | 0.1308594 | 0.9833984 | 0.9833984 |

The independent witness is a newly observed raw text input with a declared 2% class error channel; its encoder channel is checked over its exhaustive input support. All six stress quality thresholds (at least 0.90 per seed/scenario) pass. However, the controller chooses to query for all 6,561 histories in every seed. On all heldout worlds, robust-with-witness and witness-alone emit identical outputs and have identical losses. Reading the four original sources makes the former cost approximately 1.91-1.95 times as many online Linear MACs. This result demonstrates the value of the new evidence. It does not demonstrate a quality advantage of NDU over the simpler witness-only policy, or an efficient adaptive querying policy.

The separate source-control audit independently enumerates the finite action objective for all 3 × 6,561 histories. Nominal, robust and query decisions have zero mismatches and zero objective regret relative to its oracle; all 36,864 recorded heldout decisions match. The original full policy arrays were not saved, so this audit deterministically replays the frozen compiler and checks its decisions against the independent oracle, while checking heldout decisions against original records. Its 13.3884 wall seconds / 20.9941 CPU seconds are additional audit work. See [review_source_control.json](evidence/review_source_control.json).

Without new information, the symmetric eight-class shared-wrong construction bounds top-1 accuracy by 1/7. That bound requires its stated symmetry and conditional information assumptions. It is not a universal bound on every common-cause failure distribution. Repeated optimization cannot reconstruct information absent from the observation sigma-algebra; [THEORY.md](THEORY.md) gives the explicit model and proof.

## Preference and differential utility

Nine synthetic Gaussian-lottery preference fits have maximum absolute risk-coefficient error 0.064635, passing the declared 0.2 threshold. Utility scale and logistic temperature are fixed for identification. The fitted coefficient is actually passed into the policy; action changes occur in some profiles, but none of the three profiles changes seed 29's decisions. No real-user preference data or endogenous preference dynamics have been identified.

The entropic Brownian BSDE check has analytic initial utility -0.49 and martingale exposure Z=0.7. The discrete initial-value error decreases from 0.0187912 at 8 steps to 0.000312311 at 512 steps. This is a known decoupled analytic special case. Finite Bellman optimality, BSDE martingale exposure Z, and neural parameter gradients are different objects. None implies a general coupled FBSDE solver or global optimization of nonconvex neural parameters.

## Validation, execution scope and remaining work

The v3 Python suite passes 33 tests. The native crate passes 80 tests with zero skipped, followed by the required scoped fix/format and a final rebuild. Development parity covers 257 native sessions / 5,400 requests with no mismatch. The independent formal audit costs 60.4254 wall seconds, 80.7059 CPU seconds and 14.7196 billion Linear MACs, all reported separately from the experiment. An interpreter-cleanup TemporaryDirectory ResourceWarning is retained in the Python test log; it did not change the successful test process exit status.

Development001's JSON serialization failure and Development002's completed smoke remain in the data archive. v1/v1.1/v2 evidence and failures remain unchanged. No formal seed or threshold was changed after inspecting confirmation results.

The independent hosted recovery uses frozen v2 source and protocol through a new adapter. [Actions run 39903819841](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39903819841) actually acquired an ubuntu-slim runner and completed all workflow steps, 23 tests and the frozen v2 smoke (6,048 evaluations). Its scientific smoke primary is false because the CVaR gate fails; it is ineligible for confirmation. Execution success is not a scientific pass. The original queued run 39899251197 and its dedicated desktop requirement remain separate. The downloaded artifact digest, frozen source, runtime manifest and result files were verified. See [cloud-recovery-observation.json](evidence/cloud-recovery-observation.json).

The separate real-media ingestion verifies text/audio/image/video tensors, source identity and licensing from one recorded event. Subsequent frozen pretrained interface checks actually execute TAESD image and independent video-frame round trips, T5 text encoding/decoding and bounded generation, and DAC integer audio-code reconstruction. Image PSNR is 18.7792 dB and four-frame aggregate PSNR is 19.3917 dB, with visible detail loss. T5 emits the input description unchanged. The audio reconstruction has SNR -2.392409 dB; its first attempt failed the length check, and the final run uses a fixed right-side padding/crop plus tensor-only strict checkpoint loading. Failed and intermediate attempts are preserved. These are separate interface checks, not semantic-quality passes, a temporal video model, a shared natural generator, natural-data NDU training, or evidence of a foundation model. See [natural_io/README.md](../natural_io/README.md) and [NATURAL_DATA_PLAN.md](NATURAL_DATA_PLAN.md).

Remaining claims and executable acceptance conditions are recorded explicitly in [BLOCKER_LEDGER.json](BLOCKER_LEDGER.json). The canonical registry and production NeuronRuntime dispatch have not been promoted by this research branch.

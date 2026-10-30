# Prospective control repair v2: complete public state and feasible targets

**Execution is complete. The development approximation gate passed; the heldout superiority gate failed.** This is a new, prospectively frozen experiment after the documented v1 representation defect, not a replacement of v1 or a relabeling of its negative result. All original `../control/` source, freeze, results and reports remain unchanged.

The experiment trained all 15 planned controllers and retained all 180 candidate checkpoints. Only after both main families passed the fixed validation gate did it construct new heldout streams and execute all 800 planned owner sessions. Full task value had a positive mean utility difference from ordinary action learning, **+0.20880**, but the five-cohort paired 95% interval was **[−0.13532, +0.55292]**. That does not establish an advantage. The fitted-model DP reference also remains substantially better than every learned controller.

## What was repaired, and what this study measures

V1 used 40 features summarizing the current job's remaining schedule. It omitted the next job's entire public reliability/price schedule, even though the full FIRE value depends on that continuation. It also fit infeasible-action sentinel targets. An independent witness in `numerical_validation.json` keeps all 40 old features identical while changing next-job metadata and changes FIRE value from 0.8 to 1.669274688. This is a representation defect, not simply an optimizer failure.

V2 retains those 40 features and appends both full reliability schedules, both full charged-price schedules, and the TRAIN-calibrated observation law: **84 inputs**. Zero padding after each deadline makes the deadline recoverable; the original remaining-time feature then determines the current tick. Job, remaining budget and posterior are explicit. Together these recover all public state used by the finite Bellman reference. Future realized packet contents and hidden labels are excluded.

All three learned families use the same **84 → 32 tanh → 4** network, **2,852 trainable parameters**, initialization, feature normalization, training states, minibatch stream, optimizer budget and checkpoint-selection criterion:

| Family | Training target | Continuation |
|---|---|---|
| `full_value` | Four full finite-horizon Bellman action values | Includes reset and future job |
| `ordinary_boundary` | One-hot full-DP optimal action | Ordinary supervised action learner |
| `first_event_value` | Four Bellman values with post-FIRE continuation removed | Deliberate ablation |

Every target is divided by the same fixed scalar 2. The squared loss includes only feasible actions; changing invalid targets to 999 changes neither loss nor gradients. The ordinary learner therefore receives the same complete information and supervision opportunities, with a different target representation. It is a capacity-matched learned controller, not a fixed hand-designed threshold.

This package tests **learning task-valued action selection on top of a shared trained content decoder**. The new controller is an ordinary small MLP; this experiment does not establish a He–Xiong financial operator advantage, smooth event/reset differentiability, joint backbone training, Transformer replacement, or multimodal pretraining performance.

## Frozen protocol and task

The scientific freeze was written at `2026-10-30T12:44:24.841766+00:00`, before new development data or training. Its SHA-256 is:

`130b8655aeb96467e65071d503e1c741da03040b77867988daee781b7f8eb4c3`

The freeze binds eight scientific source/configuration files, the original v1 source/results/report/proposal identities, and the inherited content source/checkpoint. The baseline repository commit is `b1934022821f3fdafd509b43cf0c4d7d45852e6e`. Delivery documentation, archive helpers and explicitly post-run audits are separate from this frozen execution source.

There are five fresh seeds: **127, 139, 151, 163, 179**. Each has 60 TRAIN and 24 validation public schedules, with 12 sampled decision states per schedule: 720 TRAIN and 288 validation states. Two explicit prior/reset states accompany ten independently drawn job/time/budget/belief states. All families share these states. Each seed also has 128 newly generated TRAIN calibration packets. Exact metadata signatures and packet-byte hashes are checked against v1 and across new splits.

Each session contains two independent binary jobs, a common deadline of 6, 8 or 10 ticks, and a shared read budget of 2, 3 or 4. Public reliability values are 0.58, 0.74 or 0.9; public read prices are 0.02, 0.06 or 0.12, multiplied by 1.5 throughout this v2 study. Correct answers earn +1 and incorrect answers −1. Utility is total answer reward minus actual charged reads. An unanswered job earns zero.

- **READ** opens the current raw packet, prepares content features, executes the frozen learned decoder, updates the belief, advances one tick, and consumes one shared read unit.
- **SKIP** advances one tick before constructing a packet path, reading a packet or invoking content computation.
- **FIRE** submits the current decision, advances two ticks including the refractory tick, resets the posterior to 0.5, and proceeds to the next job with the remaining shared budget.
- **STOP** terminates the complete owner session. No later action is accepted and no remaining task reward is received.

Both jobs' public schedules are available from the start. Their hidden labels and future realized packets are unavailable to policies. The DP integrates possible observations under a **TRAIN-only fitted confusion law**, including Jeffreys pseudocounts, rather than assuming a perfect content decoder. It includes post-reset future rewards and shared-budget effects. “Exact DP” here means exact for that small fitted conditional model; it is not a true-world optimality guarantee.

The content adapter reuses the repository's trained `memory_full_mass_seed29.npz`, SHA-256 `4962cd6126dc5e393cf7dbe72bea5519125bfb7971a7e3665a36af908aff5fcb`. Its 6,217 parameters stay frozen. Actual READ executes the inherited FullHX recurrent content/memory implementation. Binary observations are the declared class-0/class-1 decision from its four logits. The new learning is controller training, not content-backbone retraining.

## Training, selection and the development gate

Each of the 15 trainings performed exactly 600 Adam updates with batch size 64 and learning rate 0.003. There was no adaptive hyperparameter search, added seed, replacement run or second training attempt. All 12 candidate checkpoints at updates 50–600 are retained, along with every update's loss, gradient norm and timing.

Every family selects the checkpoint with the lowest **full-DP validation action regret**, with ties resolved by earlier update. Action regret is the best feasible DP value minus the DP value of the model-selected action. This common criterion avoids comparing differently scaled regression losses. The first-event ablation uses the same selection criterion but is deliberately excluded from the development gate: its missing continuation is the ablation itself.

The fixed gate requires each main family's mean seed regret to be at most 0.05 and every seed's regret to be at most 0.08.

| Seed | Full-value validation regret | Ordinary validation regret | Selected full update | Selected ordinary update |
|---|---:|---:|---:|---:|
| 127 | 0.031483 | 0.044026 | 500 | 450 |
| 139 | 0.020640 | 0.021726 | 600 | 500 |
| 151 | 0.031097 | 0.023554 | 250 | 150 |
| 163 | 0.022370 | 0.030268 | 550 | 400 |
| 179 | 0.023906 | 0.033603 | 600 | 250 |
| Mean | **0.025899** | **0.030635** | — | — |

Both families passed. `study_v2.py` saves the completed 15-run result and gate before calling `prepare_heldout`; its failure branch generates no heldout metadata or payloads. The successful branch then created 40 new heldout streams per seed, evaluated all four policies on each, and retained all 800 traces.

## Heldout outcome: no established superiority

All policies use the same 200 streams, fitted observation laws, costs, deadlines and shared content decoder. Policy execution order rotates deterministically. Labels are opened for scoring only after the owner is terminal.

| Policy | Mean utility | Completed jobs / 2 | Correct jobs / 2 | Mean READs | Mean owner wall time |
|---|---:|---:|---:|---:|---:|
| Full task value | 0.79215 | 1.610 | 64.25% | 1.880 | 13.160 ms |
| Ordinary action learner | 0.58335 | 1.220 | 47.75% | 1.365 | 9.797 ms |
| First-event value | 0.56320 | 1.295 | 50.25% | 1.860 | 13.450 ms |
| Fitted-model DP | 1.23000 | 1.945 | 83.50% | 2.015 | 17.946 ms |

“Correct jobs / 2” counts unanswered jobs in the denominator; it is not accuracy conditional on answering. Full value completes more jobs and reads more than ordinary learning in this sample, with greater runtime. The comparison therefore concerns utility and quality–cost tradeoffs, not a claim of uniformly cheaper inference.

The five paired full-minus-ordinary utility differences are **0.23325, 0.49925, 0.44550, −0.15100, 0.01700**. The predeclared two-sided Student-t interval uses these five cohort differences, not 200 supposedly independent training replications. Mean difference is **+0.20880**, with 95% CI **[−0.135316, +0.552916]**. The success rule requires a strictly positive lower bound and a mean of at least 0.02; **it fails**.

The learned full-value mean remains 0.43785 below the fitted-model DP. Low average validation action regret over sampled states has not guaranteed small trajectory-level decision loss. A clearly labeled post-run diagnosis in `delivery_audit.json`, computed only from already-saved traces, finds accumulated fitted-model action regret per session of 0.40305 for full value, 0.58265 for ordinary learning, 0.53555 for first-event value, and 0 for DP. Initial-decision regret is 0.07119, 0.07818 and 0.07297 for the three learned families. These descriptive values indicate that errors on encountered states and their accumulation remain material; they are not new confirmation endpoints or true-law regret bounds. No training, tuning, gate or action was changed in response.

V1 and v2 use different fresh cohorts, capacities, features and selection procedures. Their raw utility means must not be treated as a controlled causal estimate of the feature repair. The defensible findings are that the missing-public-state defect is repaired, the fixed approximation gate is passed on new validation data, and the new heldout superiority test remains inconclusive.

## Measured execution cost and its limits

The entire study used one process with CPU affinity 4,5 and BLAS/OMP/MKL threads set to 1. The recorded runtime was **37.24170 wall seconds and 37.21452 CPU seconds**, plus **1.61066 seconds of source import**, for **38.85236 seconds** including import. This includes all development generation, 640 real TRAIN calibration reads, oracle targets, 15 trainings, checkpoint selection/serialization, heldout generation, 800 owner sessions, scoring and main-result serialization. These are instrumented study timers; Python process startup and final completion-receipt writing are outside them.

| Component | Measured wall seconds | Relationship to total |
|---|---:|---|
| Complete development phase | 24.95628 | Includes the next four development components |
| TRAIN calibration content calls | 4.29777 | Included in development |
| Oracle targets and state serialization | 5.07163 | Included in development |
| All 15 controller fits | 13.50726 | Included in development |
| Numerical validation | 1.36922 | Included in development |
| Fresh heldout construction | 1.18102 | After the passed gate |
| All 800 owner sessions | 10.87072 | Actual local end-to-end execution |
| Remaining runner overhead | 0.23367 | Checkpoint loading, gate/scoring/orchestration/serialization outside component timers |
| Source import | 1.61066 | Before the runner timer |

Do not add nested development components to the development total again. Individual fit totals include compilation, updates, validation and retained-checkpoint serialization; the first executed family bears most shared JAX compilation overhead. There were **1,424 heldout READs**, each paired with one real payload open and one content invocation, **2,758 SKIPs**, **1,214 FIREs**, and **56 STOPs**. Including TRAIN calibration yields **2,064 actual decoder calls**.

Per-session owner timing begins before public metadata I/O and includes controller decisions, packet I/O, feature preparation, content computation, action dispatch and trace serialization. Evaluation-label scoring is outside that owner timer but inside the complete study timer. Mean controller-only time is approximately 0.558 ms for full value, 0.567 ms for ordinary learning, 0.617 ms for first-event value, and 4.014 ms for DP; most learned-policy runtime is the content calls it chooses to make.

**Accounting correction:** the frozen `confirmation.json` contains an initial derived setup-sensitivity grid that omitted heldout data-generation time. The complete measured runner total already includes it. `cost_accounting.json` is a separate, explicit post-run correction that adds the missing generation and allocates measured residual overhead, without modifying the original file, primary endpoint or model decisions.

The corrected sensitivity grid retains the predefined runtime penalties 0, 0.1, 1 and 10 utility units per wall second and amortization counts 1, 100 and 10,000. Each family is assigned common experimental setup plus its own five controller fits. Shared allocations must not be summed to obtain total study cost. This is a conservative study-reproduction allocation: DP is charged shared oracle-label generation even though DP deployment would not need supervised labels. It is not an estimate of minimum production setup cost.

For example, at one utility unit per second, the corrected utility after runtime and 100-session setup amortization is 0.58244 for full value, 0.38588 for ordinary learning, 0.36467 for first-event value, and 1.06731 for DP. At only one session the full-value versus ordinary mean ordering reverses because its extra setup exceeds the mean utility difference. These descriptive sensitivity scenarios do not turn the failed confidence-interval gate into a positive result.

Timings are one run on a shared CPU host with ordinary OS caching. They are actual measured costs of this implementation, not controlled hardware benchmarks. No energy, GPU, event-driven silicon, asymptotic speedup or native Rust Hepta claim is made. Packaging and supplementary audits occur after the experiment and have separate receipts.

## Verification and evidence delivery

The original frozen `audit_v2.py` verifies all candidate-checkpoint identities, matched initialization/batch streams, development-file hashes, the gate, all trace identities, and selected-checkpoint validation regret with independent NumPy inference. Selected regret recomputation error is zero. The numerical checks include float64 directional finite differences, JAX/NumPy forward parity, infeasible-target gradient invariance, a one-read analytical Bellman value, complete-state reconstruction and the v1 alias witness.

The separate **`delivery_audit.py`** adds the coverage absent from that original audit: all **3,560 heldout file hashes**, all **800 trace state transitions**, independently computed Bayes updates, action feasibility, charged reads, packet hashes/bytes, rewards from evaluator labels, real READ/content/file counts, and the paired primary interval. It passed. The independent state/reward arithmetic does not reuse the owner's transition implementation. The optional descriptive trajectory-regret calculation is explicitly marked post hoc. This supplementary audit took 5.53130 wall seconds and 5.08225 CPU seconds.

V1's meaningful SKIP/STOP/fileless-access, payload-causality, reset and serialized-owner recovery tests remain applicable to the unchanged inherited owner/adapter. Their recovery fixture replaces an owner in the same process; no independent-process or native-backend recovery test is claimed here.

All raw evidence is retained locally and delivered in four lossless archives:

| Archive | Members | Bytes | SHA-256 |
|---|---:|---:|---|
| `raw_development.zip` | 1,060 | 317,107 | `07c1abd31e826ed7e9ddcef862bad97cc550df9e99e424b89d1b06fba6389e14` |
| `raw_heldout.zip` | 3,560 | 990,597 | `d518eeae58ba530d92768db6d47ffc85e58ac719dd80ab8d2acf93c8c2fe0950` |
| `raw_traces.zip` | 800 | 1,122,737 | `cf2125b919e14b7d82194d31df0e5158ef3687581e3f0cd66de768f744784ddf` |
| `raw_training.zip` | 245 | 3,508,546 | `ff6b4866621e69ce985d57ff7f087024643a2da00c4103c932496689d9e6960a` |

Closed archives were checked member by member against their per-file manifests. All **5,665 members** were then actually restored into a fresh separate temporary directory and reverified; `restoration_validation.json` records the successful receipt. Archive-manifest SHA-256 is `10889700ce79e16ab49d07f774bd3bed3fb8f37ff192841425d2f4a7255b4c1d`. The final training archive was added solely for efficient delivery after the original three data/trace archives had already been verified; their bytes and scientific results did not change. Unpacked directories are excluded from Git only after successful archive verification to avoid thousands of duplicate entries; all original files remain locally and the archives preserve exact bytes.

`raw_training.zip` restores `runs/` with all 180 checkpoints, all 9,000 update records, each model's selected-validation predictions and every run result, and `states/` with TRAIN/validation arrays and state provenance. `training_manifest.json` records each of these 245 files' SHA-256 and binds the unchanged development result. `calibration/` retains all 640 calibration observations directly. The main result identities are:

- `development_results.json`: `dde1d7093fa3bda14560e77aa877b77e24c41a046852c02f62754aa1a5becdd8`
- `confirmation.json`: `69c1e71cd55ddbf91dabbf43ecc70d36a7a1f928a79cdcd12c99e29e1cfe9f61`
- `completion.json`: `235c5e9e63876da3d8b3c381aa8cf413575df927aef1cd148158761343941093`

Restore archived raw files in a fresh repository checkout with `python -B restore_evidence.py`. It rejects conflicting existing files and verifies archive/member identities before accepting them. V1 raw files needed by freshness verification are separately restored with its unchanged `../control/restore_evidence.py`. Do not rerun training into this completed evidence directory: the runner refuses to overwrite exposed results. An exact computational replay requires an isolated sibling copy containing the byte-identical frozen sources/configuration/freeze, access to the same inherited v1/content identities, and no generated v2 outputs; replaying exposed cohorts is verification, not a new prospective test.

The remaining scientific question is whether a learned task-value controller can close the fitted-DP trajectory gap and produce a stable paired advantage under a genuinely new protocol. This run supplies a complete negative/inconclusive record for that decision; no further tuning or heldout use was performed.

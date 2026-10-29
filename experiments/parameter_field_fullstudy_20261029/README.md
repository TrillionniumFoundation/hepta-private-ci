> **Current execution status: BLOCKED.** Attempt01 ended in infrastructure loss; attempt02 has verified source freezes but no new scientific worker has passed RAM admission. Start with [EXECUTION_STATUS.md](EXECUTION_STATUS.md) and [ATTEMPT02_RUN.md](ATTEMPT02_RUN.md). Historical commands below describe their original source versions and are not an instruction to bypass the current operational registration.

# Parameter-field full study — 2026-10-29

**Status: RUNNING.** This README is the reproducibility entry point for the registered implementation. Scientific results, actual completion counts, integrity dispositions, negative findings and resource outcomes belong in the subsequent `REPORT.md`. No efficacy, sufficiency, interaction or net-benefit conclusion is asserted here.

The durable source of record is [this study directory on `research/parameter-field-fullstudy-20261029`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/research/parameter-field-fullstudy-20261029/experiments/parameter_field_fullstudy_20261029). A branch tip can move; the executable identities are the commit and file hashes in the phase-specific `registrations/*_SOURCE_FREEZE.json` records. The private RAM execution workflow is defined by [launch.py](launch.py). The original **1 GiB full-evidence storage envelope is insufficient**. A storage-only operational amendment and the separate R evidence-completion registration are being drafted and independently reviewed. No passage in this README claims that the full study passed its original storage budget. The existing A/C scientific source freezes remain unchanged.

## 1. Five questions and their executable tests

| Research question | Implemented comparison | Main sources and evidence |
|---|---|---|
| 1. Do requested actions produce distinct actual lawful successors? | Restore the same complete parent, execute the actual guarded kernel, and compare the post-guard state. Record rejected, accepted and zero-action work, first divergence and effective successor differences. | [branching.py](branching.py), [preflight.py](preflight.py), [bank.py](bank.py), [architecture_kernel.py](architecture_kernel.py); literal parent checkpoints, original branch component hashes, transaction traces, replay receipts and the separately registered R terminal reconstruction. |
| 2. Are labels aligned with the deployed ordinary baseline? | One candidate guarded transaction followed by the fixed ordinary baseline to a common terminal clock; subtract the paired baseline-first continuation. The baseline advantage is structurally zero. | [bank.py](bank.py), [heads.py](heads.py), [architecture_bank.py](architecture_bank.py); all four paired action values and advantages, fit/calibration partitions, frozen heads and thresholds. |
| 3. What information is lost by field compression or recovered by history? | A/B compare field12, the complete-current-state predictor and history6 under a common head-fitting procedure. W separately constructs a prespecified hidden-momentum-direction diagnostic. | [branching.py](branching.py), [heads.py](heads.py), [witness.py](witness.py); feature layouts, fit-only normalizers, ranks/conditioning, all prediction errors and constructed-state diagnostics. |
| 4. Does a controller improve independently held-out task/retention outcomes after its costs are counted? | B evaluates frozen A heads on new schedules and qualification source pairs; ordinary, the three learned heads and a cheap fixed taper all remain in the comparison. | [run.py](run.py), [endpoints.py](endpoints.py), [analysis.py](analysis.py); 240 complete training paths, 486 endpoint records, both observers and separate training/scoring cost ledgers. |
| 5. Does the controller interact with a trainable Hepta temporal event law? | C is a matched architecture-by-controller 2×2: ordinary/dual temporal event law × conventional baseline/field controller, with eight paired evaluation seeds. | [architecture.py](architecture.py), [architecture_training.py](architecture_training.py), [architecture_run.py](architecture_run.py), [architecture_endpoints.py](architecture_endpoints.py); all 32 final paths, 16 own warmstarts, 96 endpoint records and the prespecified interaction. |

These are empirical tests of a particular parameter-state abstraction and controller. The fitted ridge heads do not solve the full HJB, FBSDE or NDU problem. Training time and the neuron's inference-time recurrence remain distinct. A failure of this candidate is not a disproof of every parameter-field model; a favorable result would apply only to this task, implementation and registered comparison.

## 2. Source pins and immutable historical scope

| Component | Fixed identity |
|---|---|
| Existing bridge/scientific kernel base | `d8d81eab0e9b6082406193f7ff5a69bb1f7b806a` in `hepta-private-ci` |
| HCSN cell implementation | `68eb16caa9c14c7b5729585c86d9c293018a987c` in `hepta-private-ci`; `experiments/continuous_spiking_network/{cell,kernels}.py` |
| Paper | [ICLR-2027](https://github.com/TrillionniumFoundation/ICLR-2027/tree/f8df0a6075f58f3ab9431a889b773cdf8d6e771d), commit `f8df0a6075f58f3ab9431a889b773cdf8d6e771d`, `revision_2026-09-26-r45` |
| Registered algorithm and statistics | [PROTOCOL.json](PROTOCOL.json); phase freezes bind its SHA256 |
| Design history | [PROTOCOL_DRAFT.json](PROTOCOL_DRAFT.json) and [DESIGN_REVIEW.md](DESIGN_REVIEW.md) |
| New source allocation | [source_allocation/SOURCE_ALLOCATION.json](source_allocation/SOURCE_ALLOCATION.json) and its hashed `SOURCE_IDENTITIES.json.gz` |

The source freeze is external to the source commit that it registers, avoiding a self-referential commit hash. The registered scientific runners verify their allowed phase, exact source-file hashes and declared artifact hashes. Use the source tree matching the applicable freeze; copying a current branch tip over an already registered execution is not a reproduction.

Historical protocols, thresholds, rejected candidates and result files remain immutable. The V5 candidate remains rejected. Current-run capture/restore/replay checks do not change the failed or unresolved historical exact-regression disposition. Old primary, retention and audit source roles are not opened by this study. Research completion does not activate a production owner or deploy a policy.

## 3. Real models, data and lawful state

### A/B: three fixed historical generators

A and B use the original V6 MNIST-pair image-and-caption generators with seeds **17, 29 and 43**, their pinned original reward/audit observers, and the existing eight rank-eight upstream adapters. These are three fixed pretrained models, not three resampled representatives of a model population.

Each adaptation path has 288 scheduled gradient microsteps in six 48-step guarded transactions. The learning-rate multipliers are `[0, 0.25, 1, 2]`; ordinary baseline indices are `{17: 2, 29: 3, 43: 3}`. The base learning rate is 0.2 and SGD momentum is 0.9. The V3 clipping, rehearsal and teacher-anchor objective remain pinned. The clean guard always references the immutable original model, not the latest accepted state.

Rejection restores the entire transaction entry state while consuming the scheduled positions and charging attempted work. Multiplier zero still performs the declared gradient and guard computation; it does not advance parameters or momentum and is not a free early-stop operation. Parameter equality alone does not establish equivalent future control: optimizer moments, incoming gradients, RNG, clock, guard, controller history and resources must be accounted for. Costs are kept outside rollback.

The complete branch checkpoint includes names, shapes, dtypes and bytes; mutable parameters/buffers; supported CPU SGD state and parameter groups; incoming gradients with `None` distinguished from zero; declared RNG state; logical cursor; immutable context bindings; replay schedule; and controller memory. Restoration occurs between transactions with no pending autograd graph or concurrent writer. No promise is made to restore PyTorch tensor version counters for an already constructed graph.

### The task and the fresh allocation

The task is the existing controlled small multimodal MNIST experiment. Individual digits are 28×28; generated source-pair images are 28×56 with a caption. Task conditions are `heavy_noise`, `missing`, `occlusion` and `clean`, weighted equally. This is not an unrestricted LLM benchmark or a new dataset population.

A/B training uses the four already exposed `development_*` gradient, rehearsal, probe and guard roles. A endpoints use `development_task` and `development_clean`. C training uses `fit_gradient`, `fit_rehearsal`, `fit_probe` and `fit_guard`; no new endpoint data enter its model training, feature measurement, guard or head fitting.

The allocator excludes the entire recorded V2/V3/V4 pixel-identity union, including historically unopened roles. It leaves 2,648 official train images and 3,952 official test images, allocated by fixed salted SHA ordering and adjacent source pairing:

| Role | Official partition | Images | Pairs | First scientific access |
|---|---|---:|---:|---|
| `qualification_task` | train | 1,024 | 512 | After every required B path is sealed |
| `qualification_clean` | train | 1,624 | 812 | Same B barrier |
| `final_task` | test | 1,976 | 988 | After the complete C final checkpoint barrier |
| `final_clean` | test | 1,976 | 988 | Same single final barrier |

The salt is `hepta-parameter-field-fullstudy-20261029-v1`. Allocation uses metadata/identity checks and duplicate-label conflict exclusion, with zero task constructions, model calls or observer calls. [sources.py](sources.py) verifies both the historical union and the new registry. “Fresh” means disjoint from recorded prior allocations and task outcomes; it does not establish exclusion from unknown pretraining or new writers. “Sealed” means scientific task/model outcomes are unavailable, not that no corpus byte has ever been read for identity verification.

B's independence concerns withheld endpoint pairs and new schedule randomness. Its adaptation panels and three original models are not newly sampled. Once an endpoint outcome has been consumed, renaming its directory cannot make it independent again.

## 4. Labels, predictors and the W diagnostic

For a parent state `s`, candidate action `a`, fixed ordinary action `b` and common paired tape `omega`, the label is

`A_b(s,a;omega) = G_b(s,a;omega) - G_b(s,b;omega)`.

`G_b` executes the first actual guarded transaction, then uses `b` through the common terminal clock. This is a paired realized reference-tail contrast. It is not an exact expected `Q_b`, nor the value of repeatedly replanning with the fitted deployed controller.

A uses schedules 6000–6003, two predetermined prefixes and six decision states per prefix: 48 states per original model, 144 total and 576 four-action tail labels. Schedules 6000–6002 are fit-only; 6003 is calibration-only. Prefixes and all states of a schedule stay together. Step-zero duplicate states remain explicitly identified and are not counted as independent observations.

| Predictor | Input | Interpretation and cost |
|---|---|---|
| `field12` | The existing twelve named field observables, including current losses/value, displacement, momentum, progress, current weighted gradient and directional responses. | Fixed model/panels/guard/action set/head are additional declared context. No context-free 12-dimensional Markov-sufficiency claim. The implementation performs its actual richer measurement and selects H12; report that measured cost. |
| `full_current_state` | The frozen 54,740-dimensional current mutable-state inventory with masks, guard/clock/SGD coordinates and H12. | No truncation or random projection. This fitted high-dimensional linear predictor is not an optimal oracle. Replay RNG state, future minibatches/tapes, future marks/labels and withheld outcomes are excluded from its numerical inputs. |
| `history6` | Six chronological 19-coordinate slots, **114 dimensions** total. Completed slots contain H12, executed-action one-hot, observed guard acceptance, scheduled work/48 and validity. The current slot contains only H12 and validity; future fields/slots stay zero. | Adds memory of the same lawful disclosed stream. It still pays for H12 observations and is not the cheap baseline. |
| `fixed_taper` (B only) | Clock rule `[b,b,2,1,1,0]`. | No learned head and no extra field probes. It is a predetermined inexpensive comparator, not a tuned optimum or a fitted cosine scheduler. |

All three learned heads use fit-only normalization, float64 linear ridge with unpenalized intercept and fixed `lambda=1`. Full-current-state may use the algebraically identical dual solve. Equal ridge penalties do not imply equal effective capacity across input dimensions; ranks and conditioning are retained. Nine A heads are fitted; B performs zero new head fits.

For each head, `tau=max(0,max calibration overprediction)` over nonbaseline advantages. A unique best nonbaseline action must exceed `tau` strictly; ties and insufficient margins retain `b`. The baseline prediction is exactly zero. Twelve dependent A calibration states do not give a deployment-uniform, conformal or policy-optimality certificate; `certificate=false` is preserved. No threshold relaxation or outcome-driven extra bank collection is allowed.

W selects exactly the three A-bank parents `(schedule=6000, prefix=baseline, clock=48)`. It reflects momentum through the span of four prespecified current gradient directions, leaving every other state component unchanged. It records actual float32 momentum changes, H12 drift, all original/reflected four-action contrasts, ranking changes and post-guard state differences. The normalized near-field criterion is fixed at `1e-5`; SVD rank cutoff is `1e-10` relative. The 12 reflected candidate/tail continuations cost 2,880 additional scheduled microsteps. These constructed states have **no reachable-occupancy guarantee** and provide no independent efficacy result. The numerical criterion is reported even when it fails.

## 5. C: matched architecture × controller

C derives a trainable width-32 portfolio from the existing `NeuralPortfolio`, replacing its text encoder and decoder with matched projections and the pinned continuous cell. Encoder/decoder temporal widths are 16/32. Each model has **540,328 trainable parameters, including 12,064 temporal parameters**; actual nonzero gradient coverage and parameter changes are checked during warm-up.

The ordinary and dual modes share parameter/state shapes and bitwise matched initial tensors within a seed. The implemented difference is the sigmoid versus FPT/interval-reset event law. Other portfolio modules and latent MLP actions remain. The factorial measures the increment of this FPT event law under the declared training/controller setup; it is not a literal analytic Call-Put neuron, a demonstrated task-value-derived natural free boundary, or evidence that the whole generator has been replaced by Hepta.

Development seeds are 701/702; evaluation seeds are 801–808. All 20 architecture/seed warmstarts train every parameter for 400 steps with batch 32, learning rate 0.01, SGD momentum 0.9 and clip 1. Every controller arm carries its own architecture warmstart's optimizer and RNG state into adaptation. At each declared microstep boundary gradients are cleared to `None`, so the saved all-None gradient inventory is actual algorithm state.

Continuation is 96 steps in six macro16 transactions, with adaptation/rehearsal batches 32/16, rehearsal weight 0.5 and teacher anchor 0.1 to that path's immutable warmstart. Its immutable warmstart reward-clean guard has threshold zero. Both architectures use conventional baseline index 2, multiplier 1.0, without retrospective per-architecture tuning.

C fits compatible field12 heads separately for the two architectures. Each pools the two development seeds: 72 fit states from schedules 7000–7002 and 24 calibration states from 7003. There are 192 bank states and 768 action-tail labels overall. The fifth coordinate is relative full-parameter displacement from the own warmstart, with norm floor `1e-12`, replacing the old adapter effective-operator displacement. Evaluation schedule 8000 gives all 32 paths; each seed has ordinary/baseline, ordinary/field, dual/baseline and dual/field.

The primary interaction is

`(J_dual_field - J_dual_baseline) - (J_ordinary_field - J_ordinary_baseline)`.

Report it alongside both architecture-specific field increments, dual-field minus ordinary-field, each seed, all four own-warmstart retention contrasts and all costs. A positive dual/field arm alone does not establish a positive interaction. The optional GRU comparator is disabled and cannot replace a main arm after outcomes.

C persists four development warmstarts, sixteen evaluation warmstarts and thirty-two final checkpoints. Branches use complete independently restored in-memory states and retain exact hashes/traces/reconstruction recipes. They are not all archived as literal branch tensor files. Four independently reconstructed branch replays add 384 physical microsteps and must agree on deterministic state, tape, guard, output and transition identities. Literal archive restoration and reconstructive replay are separate claims.

## 6. Exact scheduled work and complete endpoint barriers

### R evidence completion: original omission and separate reconstruction

The original A bank writer persists all **144 complete parent checkpoints**, per-branch output arrays, transaction traces and **576 terminal component/dynamics/controller-history identities**. It does **not** persist the original complete terminal tensor records. The original terminal identities are hashes of the declared components, not an archive of the original serialized terminal bytes. This gap must be reported explicitly; the desired full literal-terminal evidence was not provided by the original bank writer.

[R's separate implementation](replay_terminals.py) reconstructs every one of those 576 tails from the 144 literal parents, using the original action, baseline continuation, guard, paired schedule and runtime. It checks deterministic transaction receipts, first-successor identities, terminal components and controller-history hashes against the original A evidence. It then persists each newly reconstructed complete terminal, verifies compression/decompression byte equality and restores that new artifact into a live adapter for another literal equality check.

R therefore supplies **newly reconstructed complete terminal bytes matching the original declared identities**. It cannot retroactively claim that the original terminal bytes had been archived. It does not refit heads, change labels used for fitting, select favorable branches, open new endpoint roles or add statistical samples. A mismatch is an integrity failure, not an invitation to adjust the comparison. Its 96,768 extra gradient microsteps and all observer/restore/storage work are charged separately; this is evidence completion, not a rescue of scientific effects.

R has its own protocol/source freeze, with registration in progress. It does not modify the existing A/C scientific freezes. Its draft storage ceiling and the storage-only operational amendment remain subject to independent review; they are not an assertion that the original 1 GiB gate passed.

### Required physical counts and endpoint populations

The following are required counts for a fully completed real-kernel execution, not counts of accepted updates and not evidence that all phases have already completed:

| Work package | Scheduled gradient microsteps | Breakdown |
|---|---:|---|
| A | **117,504** | 103,680 bank/prefix/branch-tail steps + 13,824 steps for 48 evaluation paths; 39,168 per original model. |
| B | **69,120** | 3 fixed models × 16 schedules × 5 methods × 288; 240 paths, 23,040 steps per model. |
| C | **57,536** | 8,000 warm-up + 46,080 bank + 3,072 evaluation + 384 independent replay; 57,152 main scientific steps plus replay. |
| W | **2,880** | 3 predetermined parents × 4 reflected tails × 240 remaining steps. |
| R evidence completion (separate registration in progress) | **96,768** | 576 reconstructed tails from 144 persisted A parents; 32,256 steps per fixed model. No new samples or fits. |
| Real-kernel engineering preflight | **432** | One 48-step setup transaction + two orders of four 48-step branch replays; separate from scientific paths. |

A+B+C+W total 247,040 scheduled physical microsteps at full completion. R adds 96,768 as a separate reconstruction ledger, giving **343,808** across those work packages; the engineering preflight adds 432 for **344,240** overall. The original A/B/C/W counts and scientific sample sizes are unchanged. Feature/directional gradients, teacher/observer forwards, head fitting, cloning, serialization and scoring are additional paid work, not hidden inside these counts. Actual receipts, including partial failures, determine the eventual report.

Endpoint consumers first validate the full expected population, literal checkpoint sizes/hashes, completed training records, runtime/source bindings and legal terminal clocks. They cannot choose a favorable subset.

| Endpoint phase | Required training/frozen evidence | Complete records |
|---|---|---:|
| A | All 48 training paths; three original frozen models; disclosed development endpoints only. | 102 = 2 × (48 + 3) |
| B | All 240 training paths and all three seed completions, plus the original frozen references. `ENDPOINT_CHECKPOINTS.json` and `QUALIFICATION_ACCESS_FREEZE.json` bind the entire set before qualification roles load. | 486 = 2 × (240 + 3) |
| C | Complete training seal with all 52 persistent checkpoints; final access manifest binds all 32 endpoints and 16 evaluation own warmstarts. `FINAL_ACCESS_FREEZE.json` permits only the two final roles. | 96 = 8 × 2 architectures × 3 methods including own frozen × 2 roles |

The original frozen outputs are reused in paired contrasts, not counted as new schedule replicas. C uses output action 0: exactly one `couple` latent action and no teacher-forced caption. Shared per-seed source/condition/noise panels are used across every architecture/controller and own warmstart. The same actual quantized uint8 pixels and UTF-8 captions go to the two original observers; the declared one-action refinement charge is 0.002.

NPZ evidence retains both observer arrays, source IDs, condition labels, pixels, captions and emitted-output digests. The writer obtains exact compressed bytes before the resource check, writes exclusively, fsyncs and verifies every array on reread. Analysis loads only a complete manifest/grid with verified NPZ sizes/hashes. Training-path costs appear once on task records; clean records carry an empty training ledger. Scoring costs remain separate. C warm-up costs are counted once through each own-warmstart reference, and full offline bank/fitting work is also retained in the stage ledger. Stage totals and their per-path breakouts are overlapping accounting views and must not be added twice.

## 7. Paired inference, costs and negative findings

[analysis.py](analysis.py) requires the frozen protocol and complete decoded records. It retains both observers, all four equally weighted task conditions, all declared contrasts and every fixed-model/seed effect.

- **B:** 8,000 draws, RNG seed 291029. Resample schedules within each of the three fixed models, shared across methods/observers. Share one task-pair resample across models/methods/conditions and use a separate shared clean-pair resample. Weight the three fixed models equally; do not resample them into a model-population claim. The ten-comparison family per observer includes four primary task contrasts, four primary retention contrasts and the two taper contrasts.
- **C:** 8,000 draws, RNG seed 291030. Resample the eight paired training seeds jointly across all four arms/observers, with shared task-pair and separate clean-pair resamples. The eight-comparison family per observer contains the four declared task effects and four own-warmstart retention effects.

Both analyses condition on the frozen design and fitted heads; C seed resampling does not repeat controller-bank construction or head fitting. Both use equal-tail percentile intervals with family alpha 0.05 divided by their predeclared family size. These are approximate resampling intervals, especially with eight C seeds; no finite-sample exact coverage or 80% power claim is made. Claims require the registered conjunction across both observers. B's field advantage requires its specified 0.001 ordinary-margin, positive history contrast, per-model signs and retention bound; C's interaction requires a positive interaction bound and the registered retention condition. Full definitions remain in `PROTOCOL.json`, and every other comparison is reported regardless of sign.

Task utility and physical costs are reported separately. Measure the one-time bank/fitting cost, deployment observations and reverses, teachers/observers, rejected and zero work, CPU/wall time, memory, raw/archive bytes, integrity checks and restoration. Equal scheduled-gradient counts are not equal total compute. A squared parameter increment is not physical energy. No cost exchange rate or amortization horizon is chosen after observing outcomes. Any conditional break-even calculation must expose its units and assumptions; an unconditional net-gain claim needs the declared task/retention gates and measured quality-cost Pareto improvement.

Zero overrides and matching baseline terminal identities identify an inactive candidate; retain that result and its observation overhead. Negative effects, failed retention, ties, integrity failures and incomplete phases stay in the evidence. No favorable-seed selection, threshold reduction, optional sample enlargement, comparator substitution or deletion of failed branches is permitted. Completing the study means giving every registered comparison a truthful disposition, not making every effect positive.

## 8. Reproduction prerequisites and resource status

Use an authorized checkout of the research branch and the exact phase registrations. Restore the original nine dataset/model/observer assets with their existing byte hashes and `RESTORATION.json`; do not regenerate models or substitute a synthetic corpus. The pinned HCSN source files must be available at `<reference-root>/experiments/continuous_spiking_network/`. Preserve both old registries and the new allocation. `sources.verify_registry(...)` checks allocation identity without opening endpoint outcomes.

The currently observed execution runtime is Python **3.12.14**, CPU PyTorch **2.8.0+cpu** and NumPy **2.3.5**. Actual bindings also record CPU/runtime/dispatch details, threads and deterministic-algorithm state. Matching package version labels alone does not establish replay equivalence. A/B/W use two intra-op threads; C uses one; inter-op threads are one. The real-kernel preflight must pass before scientific bank construction.

The original launcher contract is a private Linux user/mount namespace, task-owned empty mount point, 4 GiB tmpfs, at most four workers, global raw ceiling 1 GiB, at least 2 GiB `f_bavail` reserve and 2,000 available inodes. C's 350 MiB training-evidence ceiling excludes endpoint media; media still count toward the global ceiling. A/B per-seed and W limits are 7,200 CPU/10,800 wall seconds; C limits are 43,200 CPU/21,600 wall seconds. The outer launcher window is 12 hours.

A separate task-owned archive file must be physically preallocated to at least **1,090,519,040 bytes (1,040 MiB)** before finalization. `launch.py` builds a manifest, writes a gzip archive into that reservation, restores every persisted member into a fresh directory and checks its size/hash before issuing `ARCHIVE_VERIFICATION.json`. A sparse placeholder is not a demonstrated reservation. The archive does not claim to contain C branch tensors that were never persisted.

**The original 1 GiB envelope is insufficient for complete requested evidence.** The original limits above are documented as the original operational contract, not as a completed feasibility proof. A storage-only operational amendment is being drafted and independently reviewed, including raw evidence, partial failures, a physical archive reservation, full literal restore and the free-space/inode reserve. The R source currently declares a draft 2 GiB global raw ceiling; that prospective declaration is not approval of a revised execution arrangement. Statistical estimands, kernels, data choices, fitting rules and original scientific source freezes stay unchanged. Follow the reviewed resource plan and actual serializer/space measurements; stop and preserve progress if a gate fails. No unrelated build files are deleted, no failed scientific artifacts are discarded to make room, and no historical storage gate is waived. `launch.py` performs local preservation only; it does not authorize an external raw upload. Durable code/registrations remain in Git; RAM execution state is temporary until the required preservation succeeds.

## 9. Commands and phase ordering

The placeholders below name task-owned locations and already reviewed phase-freeze files. Each command runs from the applicable repository checkout. Set the Python environment to the pinned runtime; a local `PYTHONPATH` override is only needed if that runtime is provided outside the normal environment.

```bash
HEPTA_REPO=/absolute/path/to/hepta-private-ci
HEPTA_STUDY="$HEPTA_REPO/experiments/parameter_field_fullstudy_20261029"
HEPTA_ASSETS=/absolute/path/to/restored-original-assets
HEPTA_REFERENCE=/absolute/path/to/pinned-hcsn-source
HEPTA_RUN=/absolute/path/to/private-mount/runs
HEPTA_PROTOCOL="$HEPTA_STUDY/PROTOCOL.json"
HEPTA_SOURCE_MANIFEST="$HEPTA_STUDY/source_allocation/SOURCE_ALLOCATION.json"
HEPTA_FREEZE_A=/absolute/path/to/reviewed-A-source-freeze.json
HEPTA_FREEZE_A_ENDPOINT=/absolute/path/to/reviewed-A-endpoint-source-freeze.json
HEPTA_FREEZE_B=/absolute/path/to/reviewed-B-source-freeze.json
HEPTA_FREEZE_C=/absolute/path/to/reviewed-C-source-freeze.json
HEPTA_FREEZE_W=/absolute/path/to/reviewed-W-source-freeze.json
HEPTA_FREEZE_R=/absolute/path/to/reviewed-R-source-freeze.json
HEPTA_PROTOCOL_R=/absolute/path/to/reviewed-R-protocol.json
cd "$HEPTA_REPO"
```

A registration must explicitly allow the invoked phase and include that consumer's required dependency closure. A training-only A freeze is not automatically an endpoint/W/B authorization. C scoring verifies the same frozen C binding as its training seal. Never create a late source freeze merely to bless modified code after that phase's outcomes.

### Supported private RAM launcher

`launch.py` is the authoritative implementation of the original local execution flow. The command below documents that interface; use it only with the applicable reviewed resource arrangement. It does not establish that the full workload fits the original envelope. Its `--repository` checkout must also contain the pinned HCSN files, because that path is passed as C's reference root. The mount point must be empty and lie beneath the checkout's parent task directory. Supply the reviewed, preallocated backup and a metadata export directory outside the private mount.

```bash
HEPTA_TASK=/absolute/path/to/task-owned-directory
HEPTA_MOUNT="$HEPTA_TASK/private-mount"
HEPTA_EXPORT="$HEPTA_TASK/export"
HEPTA_QUEUE="$HEPTA_TASK/queue.json"
HEPTA_BACKUP="$HEPTA_TASK/preallocated-raw-evidence.tar.gz"
unshare --user --map-root-user --mount \
  python3 -B -m experiments.parameter_field_fullstudy_20261029.launch \
  --mount "$HEPTA_MOUNT" --export "$HEPTA_EXPORT" \
  --queue "$HEPTA_QUEUE" --backup "$HEPTA_BACKUP" \
  --assets "$HEPTA_ASSETS" --repository "$HEPTA_REPO" \
  --protocol "$HEPTA_PROTOCOL" --source-manifest "$HEPTA_SOURCE_MANIFEST"
```

Begin with a queue containing only the engineering gate:

```json
{"jobs":[{"stage":"preflight"}],"finalize":false}
```

Update the queue atomically, retaining previous entries. The launcher submits a stage once and can run up to four jobs; **it does not resolve a dependency DAG or wait for an incomplete prerequisite before starting a queued consumer.** Add stages only after the required completion/integrity review:

| Queue stage | Add only after | Required `freeze` field |
|---|---|---|
| `preflight` | Original asset/runtime/source integrity and resource setup. | None; engineering gate. |
| `A` | Successful real-kernel preflight and A registration. | A freeze; launches seeds 17/29/43. |
| `C` | Successful engineering/source checks and the complete C registration. | C freeze, including its final scorer/statistics. |
| `A_endpoint` | All 48 A paths and three seed completions. | An A-allowed freeze containing endpoint dependencies. |
| `W` | Complete A banks with the three predetermined parents/heads and W registration. | W freeze. |
| `B` | Frozen complete A heads/normalizers/taus and B registration. | B freeze; launches seeds 17/29/43. |
| `B_endpoint` | All 240 B paths, all three completions and qualification access prerequisites. | B-allowed endpoint freeze. |
| `C_endpoint` | Complete C seal, 32 endpoints, 16 own warmstarts and final access prerequisites. | The matching C freeze. |

Each registered queue entry has the form `{"stage":"A","freeze":"/absolute/path/to/the-reviewed-freeze.json"}`. The original launcher does not include an `R` queue command. R needs its separately reviewed invocation and evidence preservation workflow; do not invent a queue stage or silently change the frozen launcher. Keep `finalize:false` while planned jobs remain. Set `finalize:true` only after every declared work package has an honest completed/failed/incomplete disposition and all intended jobs have been submitted. Finalization analyzes completed B/C endpoint manifests, exports summaries, archives all existing raw evidence and performs literal member restoration. The existence of a final archive alone does not establish that all scientific phases succeeded; inspect job dispositions and the final report.

### Direct commands used by the launcher

These are alternative invocations for a correctly prepared execution environment, not additional runs to execute after the launcher has already created the same evidence paths. Output paths are exclusive and must not be overwritten. The real-kernel preflight opens only declared development training roles:

```bash
python3 -B -m experiments.parameter_field_fullstudy_20261029.preflight \
  --assets "$HEPTA_ASSETS" --out "$HEPTA_RUN/preflight"
```

A and B run each fixed model exactly once per phase. Run B only after its listed prerequisites:

```bash
for HEPTA_SEED in 17 29 43; do
  python3 -B -m experiments.parameter_field_fullstudy_20261029.run \
    --phase A --seed "$HEPTA_SEED" --assets "$HEPTA_ASSETS" \
    --root "$HEPTA_RUN" --freeze "$HEPTA_FREEZE_A"
done
python3 -B -m experiments.parameter_field_fullstudy_20261029.endpoints \
  --phase A --assets "$HEPTA_ASSETS" --root "$HEPTA_RUN" \
  --freeze "$HEPTA_FREEZE_A_ENDPOINT"
python3 -B -m experiments.parameter_field_fullstudy_20261029.witness \
  --assets "$HEPTA_ASSETS" --root "$HEPTA_RUN" \
  --freeze "$HEPTA_FREEZE_W" --protocol "$HEPTA_PROTOCOL"
for HEPTA_SEED in 17 29 43; do
  python3 -B -m experiments.parameter_field_fullstudy_20261029.run \
    --phase B --seed "$HEPTA_SEED" --assets "$HEPTA_ASSETS" \
    --root "$HEPTA_RUN" --freeze "$HEPTA_FREEZE_B"
done
python3 -B -m experiments.parameter_field_fullstudy_20261029.endpoints \
  --phase B --assets "$HEPTA_ASSETS" --root "$HEPTA_RUN" \
  --freeze "$HEPTA_FREEZE_B" --source-manifest "$HEPTA_SOURCE_MANIFEST"
```

C's training runner never opens final source roles; its separate scorer enforces the complete final checkpoint barrier:

```bash
python3 -B -m experiments.parameter_field_fullstudy_20261029.architecture_run \
  --assets "$HEPTA_ASSETS" --root "$HEPTA_RUN" \
  --reference-root "$HEPTA_REFERENCE" --freeze "$HEPTA_FREEZE_C" \
  --protocol "$HEPTA_PROTOCOL" --execute
python3 -B -m experiments.parameter_field_fullstudy_20261029.architecture_endpoints \
  --assets "$HEPTA_ASSETS" --root "$HEPTA_RUN" \
  --reference-root "$HEPTA_REFERENCE" --freeze "$HEPTA_FREEZE_C" \
  --protocol "$HEPTA_PROTOCOL" --source-manifest "$HEPTA_SOURCE_MANIFEST" --execute
```

R is an additional, separately registered evidence-replay command. After its source/protocol and storage-only operational amendment have been reviewed, it runs against the unchanged complete A bank and charges its own work:

```bash
for HEPTA_SEED in 17 29 43; do
  python3 -B -m experiments.parameter_field_fullstudy_20261029.replay_terminals \
    --assets "$HEPTA_ASSETS" --root "$HEPTA_RUN" --seed "$HEPTA_SEED" \
    --freeze "$HEPTA_FREEZE_R" --protocolR "$HEPTA_PROTOCOL_R"
done
```

Its expected outputs are `stage_R/seed-<seed>/COMPLETE.json` and 192 reconstructed terminal artifacts per model. The R protocol binds the original A protocol hash explicitly. The reconstruction files supplement the original evidence; original A bank files and their scientific summaries are not rewritten.

The tested analysis API is `analysis.summarize(records, stage, protocol)`. For B, decode `stage_B/endpoints/ENDPOINTS.json` with `endpoints.load_records(path, expected_sha256)`; for C, decode `stage_C/endpoint_evaluation/ENDPOINTS.json` with `architecture_endpoints.load_records(path, expected_sha256)`. Pass the externally recorded manifest hash and the frozen protocol. The launcher calls these APIs during finalization. They analyze the stored complete arrays; they do not refit controllers or rescore models.

Existing synthetic engineering tests can be run without scientific assets or new endpoint access:

```bash
python3 -B -m unittest \
  experiments.parameter_field_fullstudy_20261029.test_branching \
  experiments.parameter_field_fullstudy_20261029.test_heads \
  experiments.parameter_field_fullstudy_20261029.test_sources \
  experiments.parameter_field_fullstudy_20261029.test_endpoints \
  experiments.parameter_field_fullstudy_20261029.test_architecture_endpoints \
  experiments.parameter_field_fullstudy_20261029.test_analysis \
  experiments.parameter_field_fullstudy_20261029.test_witness
```

The additional `test_architecture` and `test_architecture_kernel` modules use synthetic tasks with the actual pinned cell code; their fixture expects the matching HCSN checkout in the sibling `hcsn-source` directory. Synthetic tests verify implementation behavior and never substitute for the 432-step actual-kernel gate or the registered scientific runs.

## 10. Evidence to accompany the subsequent report

The final report should link the phase source freezes, runtime/asset identities, complete source allocation, real-kernel preflight, all path/bank/endpoint manifests, integrity replays, the separate R registration/reconstruction manifests, W diagnostics, B/C paired analyses, complete cost ledgers and failure records. It should distinguish persistent literal checkpoints from reconstructible C branches and include the archive/member-restore receipt for what was actually persisted. Document the original A terminal-archival omission, the newly reconstructed nature of R terminals, the additional 96,768-step ledger, the original storage-envelope shortfall and the reviewed operational amendment rather than claiming compliance with the original full-evidence budget.

Report all model/seed and schedule-level effects, both observers, all predefined comparisons and actual work. An interrupted run receives an incomplete disposition with its preserved evidence. Successful preservation, positive development screening, independent task effects, retention and net benefit are separate findings. **Until that evidence is reviewed and `REPORT.md` is published, the study status in this README remains RUNNING.**

## Attempt 01 infrastructure interruption and recovery registration

At 2026-10-29 07:47 UTC, the exec transport reset and all four study workers plus their launcher disappeared. The private mount vanished with its process namespace. The last exported progress records 43 of 48 bank parents for each A seed, all 20 C warmstarts, and 410,254,736 logical raw bytes before the interruption. Those unarchived raw files are lost; this attempt is **INCOMPLETE / INFRASTRUCTURE FAILURE**, not a scientific success or a completed negative result. No independent qualification/final role was opened. Published source, source freezes and exported receipts survive. See [evidence/INFRASTRUCTURE_FAILURE_01.json](evidence/INFRASTRUCTURE_FAILURE_01.json).

The cgroup reported an 8 GiB limit, a peak above that limit and cumulative OOM/kill counts of 8/4. These observations support memory pressure as a likely contributor, but do not identify each terminated PID. The task-owned empty 1,472 MiB RAM archive reservation was released; it had not contained a finalized archive. The earlier original 1 GiB raw / 2 GiB physical-reserve / separate archive contract is not reported as passed.

The surviving logs establish at least **102,320 training gradient microsteps** in attempt 01, plus its 432-step engineering preflight. The earlier disk preflight adds another 432, for a known pre-retry lower bound of **103,184 scheduled microsteps**. Unlogged partial work and lost feature/scoring counters remain unknown. A fresh complete retry is additional work, not recovery of those original raw bytes.

Recovery uses a separately registered operational profile, a process-independent task-owned evidence directory, memory admission checks, lower concurrency and uniform whole-file deduplication with complete path/size/SHA identities. All scientific kernels, source allocations, seeds, schedules, actions, heads, thresholds and planned inference remain unchanged. The profile must be committed and its source freeze verified before retry execution. It does not authorize an external raw upload.

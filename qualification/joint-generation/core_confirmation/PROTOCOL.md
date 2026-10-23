# Core-c1: prospective content-control and NDU confirmation

This is prospective registration v2. At the original v1 registration, no
core-c1 split, model, calibration, validation, or test had been constructed.
Revision v2 follows the retained TRAIN-only matching failure; test remains untouched. The final reviewed source,
this document, and `plan.json` must be committed and bound before execution;
actual execution status belongs in separate retained run receipts. The existing
engine is reused through the fixed `core-c1` experiment registry; a second
training/control center is excluded.
Execution remains in the saved hepta-private-ci Codex cloud environment. No
temporary dot workspace, user computer, Actions run, quota workaround, or access
denial bypass substitutes for that environment.

## Claim and retained prior failures

The claim is incremental generation-content benefit under equal complete build
caps: additive content training improves on an equal-weight CE anchor, and NDU
training adds benefit over additive training. This experiment uses finite synthetic
text and learned RGB only. It does not qualify adaptive routing. The retained r2
dynamic gates and failures are unchanged and are not relabeled as passes.

R2 validation results, TRAIN grouped OOF diagnostics, timing probes, and implementation
repairs informed this prospective design. They do not supply independent core-c1
evidence. Cumulative research, failed attempts, and diagnostics are recorded R&D
costs; they are not equalized cumulative budgets or credits against a new build.
No earlier checkpoint, selected content weights, optimizer state, critic, or
reward table is imported. Each new base is trained only on core-c1 TRAIN.

The existing media envelope and canonical HNMF mapping remain authoritative:
`text`, `image`, `audio`, `video`, `code_ast`, `gui_state`, `tool_trajectory`,
`structured_data`, and `sensor` remain recognizable interface names. Only the
text/image backend is exercised. Recognized unsupported capabilities remain
explicitly unsupported; no AV generation or long interaction is introduced.

## Fixed data and untouched test

The public seed salt is `hepta-joint-generation-core-c1-v1`. For each literal
split name `train`, `validation`, or `test`, let

`digest = SHA256(UTF8(salt + U+0000 + split))`

`seed = 1 + (int.from_bytes(digest[0:8], 'big') mod (2^32 - 1))`.

No data or score is consulted when deriving these values:

| Split | Seed | SHA-256 digest |
| --- | ---: | --- |
| train | 304797655 | `7c80e65b95a9f17af5e04716902f80c0164f2decab17e5acc7c7b7314408409a` |
| validation | 3249316160 | `e0021162e1aa8fdc6eba46fee9551809d5533f0e31a41db86c1b256f3704e457` |
| test | 227603836 | `ae942c045efcc976c020a43b5979c77f3b58e135d0053d1e08289edc760c32bc` |

Keep `independent.data_v2` physical generation, source identity, instruction
selection, and noise equations unchanged. There are twelve scene classes,
16/6/6 sources per class in train/validation/test, eight distinct instructions per
source, and two sensor variants: 192/72/72 physical sources and 3072/1152/1152
rows. Vertical shifts are {-1,0,1}, foreground [0.75,1.0], background [0,0.04],
and sensor-noise scale [0.03,0.12], with the same uniform/normal sampling as r2.
Every instruction and sensor variant from a physical source stays in one split.
Physical-source and observed-input hashes must be disjoint across the three
splits. Failures consume the opening, rather than permitting another seed.

The experiment-wide marker is
`core_confirmation/core-c1-test-opened.json`; the selected run also receives
`test-opened.json`. Both use exclusive creation before any test constructor,
including a constructor used only for hashes or smoke inputs. The fixed registry
paths cannot be changed by output directory or CLI input. Existing r1/r2 markers
are never removed, reused, or modified. A pre-existing or partially acquired
core marker blocks another opening. Preserve both markers after an exception.

## Models, useful work, and selection

Use the same 202-input, hidden-32 shared tanh encoder, twelve-class text/image
heads, and learned 12-by-192 RGB decoder. Model seeds are 11,23,47. Shared decoder
training is 300 steps; shared supervised dense pretraining is 500 steps, with
the existing initialization, minibatch-64, LR 0.003, RNG, and NumPy Adam equations.
All arms start from the same corresponding new seed base. The shared phase is
not changed to mixed training or native Adam.

| Arm | Applied adaptation objective |
| --- | --- |
| supervised (S) | CE weight 1.0 |
| anchor (H) | CE weight 0.2 |
| additive (A) | CE weight 0.2 minus expected decoded task utility |
| ndu (N) | CE weight 0.2 minus entropic certainty equivalent, fixed rho=1.5 |

All four arms use the current `folded-mixed-encoder-v1` adaptation kernel and
`native-adam-v1` optimizer, only for candidate/residual updates. Preserve the
existing index draws, independent 50/50 full-view masks, and expanded `np.where`
inputs. Low blocks are checked and the current encoder is folded each step;
content encoder and both heads receive gradients. Decoder adaptation remains
disabled. Native Adam retains the original clipping, parameter clocks, and
element expressions; contraction is disabled and fast-math is absent. Preserve
the already declared numerical equivalence checks. Do not weaken their tolerance
or substitute a score increase for proof that parameters and gradients train.

Search all three learning rates {0.001,0.003,0.01} for all three seeds: nine real
candidates per arm, 36 overall. Freeze one global LR per arm using the mean
three-seed validation always-full task utility minus the TRAIN-calibrated CPU
price. Full is the only mode; there is no view/router/threshold/critic search.
Retain every candidate, including a worse candidate. Selected residual updates
reuse the chosen optimizer/RNG states in rotated complete three-seed rounds,
without validation stopping, LR reselection, or new seed draws to obtain cheaper
masks. The componentwise worst step is a pre-draw reservation only; actual mask
work is charged. CPU/unit forecasts use actual objective-step ledger deltas.

## Complete budgets and observation boundaries

Each arm has the unchanged caps of 12,000,000,000 declared operator units and
10.0 CPU seconds. Attribute the entire common preparation to every arm, including
data preparation, decoder/base training, common validation, native compilation
(parent plus compiler-child CPU), and numerical metadata. Add all arm setup,
native-optimizer scans/binding, nine-candidate training/search/validation/export,
selection, selected residual updates/revalidation/export, and selected validation.
No quarter-share common cost, padding, unused critic, or unused objective runs.
Serialization/allocation/interpreter cost remains in actual CPU even where the
operator profile does not claim hardware FLOPs or memory/PNG/JSON arithmetic.

Common calibration is TRAIN-only: 72 distinct physical sources, exactly six
of each source class and six of each target class. Revision v2 uses a salted,
deterministic global integer flow through source class, physical source and
available target class. Source classes use numeric order. Physical sources use
(SHA256(salt + U+0000 + source_id), source_id) order; target neighbors use
(SHA256(salt + U+0000 + "target:" + decimal_target), target) order. Residual
breadth-first augmenting paths use that fixed edge insertion order. Each selected
source/target pair uses its smallest input SHA. Decompose the balanced class
multigraph with scene-numeric, salted-target-order augmenting matchings into six
rounds. Within each class-pair cell, consume physical sources in the same salted
rank; output each round in numeric target-class order. Every round covers all
source and target classes.
No exact cyclic joint-cell pattern is required; no margin or uniqueness constraint
is relaxed. Infeasible global flow still raises a real failure, with no salt or
data-seed fallback. Graph selection is metadata preprocessing inside full common
CPU; declared model-kernel work retains its stated scope. Use three repeats, full
mode only, and three seeds: nine measures and 648 real outputs. Keep every sample,
including timing outliers. Fix the common full-service CPU reference as the
median per-row full-service CPU from the first shared base's calibration, before
candidate search. Full is the only candidate/revalidation observer mode. Normal
and actually corrupted decoder observations are independent local preparations;
there is no global observation or output cache.

Stop immediately on an actual cap breach, or if common preparation leaves no
admissible initial candidate update. Retain the original nonzero status and
partial receipts; do not continue other phases to obtain a favorable timing
sample. Normal exhaustion of an allocated candidate budget or refusal of a
later complete residual round ends that allocation without inventing work.
The existing shared-wave
slowdown remains unexplained; there is no invented numerical anomaly cutoff,
deleted outlier, automatic identical-source retry, or best-of-waves selection.
Do not open test after shared/build failure. Any later repair requires a new
prospectively frozen source revision and preservation of the prior failure.

## Fixed service and cost-valued endpoint

Each arm/seed executes exactly one always-full generation pass per test request,
in fixed batches of at most 64. Rotate the four-arm measurement order by seed
index. There is one measurement of each arm/seed bundle: no extra repetitions
or choice of a faster sample. Sampling seed is the corresponding model seed for every arm. Keep actual
caption, learned decoder, PNG, hashing, base64, JSON, and ledger work in service
CPU. There is no low/ensemble/continuation/random policy comparison. A single
request smoke cannot substitute for the frozen batch-throughput evaluation.

Let U be the existing expected raw utility of actual decoded outputs, c the
measured full batch CPU divided by its row count, p one-time runtime preparation
CPU, B the arm's complete build CPU including full common attribution, R the
frozen common reference CPU, H=100000, and S=3 selected model seeds. Define

`complete_cpu_net = U - 0.02 * (c + p/H + B/(S*H)) / R`.

Use the same horizon, price, units, reference, and attribution for every arm.
Report runtime-only CPU-net, operator-net, complete build costs, and batch
latency separately. These do not replace the complete CPU-net endpoint. Formal
observer/bootstrap/result-persistence CPU is retained as evaluation/R&D cost
outside service timers; TRAIN/validation observers and required model exports
remain build costs. Complete build claims do not assert hardware/energy equality
or matched lifetime research cost.

## Readiness, inference, and the sole global confirmation claim

Before opening, require positive corresponding validation mean contrasts for
both A-H and N-A on all three endpoints below, greedy retention, strictly
positive actual decoder-corruption score drops for every selected arm/seed,
and zero complete build/service budget violations. This is a readiness screen,
not independent evidence. A failed screen exits nonzero and leaves test shut.
It cannot be replaced by a positive endpoint from r2 or TRAIN OOF.

The sole confirmatory claim is an intersection-union: all six predeclared paired
contrasts must have a two-sided 95% percentile bootstrap lower bound strictly
greater than zero:

| Contrast, always-full | Required endpoints |
| --- | --- |
| A minus H | raw task utility; joint success; complete CPU-net utility |
| N minus A | raw task utility; joint success; complete CPU-net utility |

The added CPU-net requirements implement the user's complete-cost benefit
claim; they are fixed before new validation/test evidence. No single endpoint,
contrast, seed, favorable wave, or alternative interval can establish the claim.
The global conjunction needs no Bonferroni selection correction; the six marginal
intervals are not advertised as having simultaneous 95% coverage.

Reuse the r2 crossed paired bootstrap exactly: form a mean paired difference
for each seed and cluster; independently resample three seeds and all clusters
with replacement; average their Cartesian product. Use 2000 replicates and RNG
seed 77431, reporting 2.5/97.5 percentiles. Raw task/joint endpoints cluster by the
72 physical sources, keeping all sixteen rows together. CPU-net endpoints
cluster by the 18 fixed index//64 service cohorts. This CPU inference is
conditional on the frozen batching/execution wave; it does not turn a shared
wave shock into independent physical-source timing evidence. No extra resampling
until significance, changed cluster definition, or per-seed exclusion is allowed.

Additionally require zero budget violations, maximum per-seed greedy joint
drop <=0.02 for H-to-A and A-to-N, and strictly positive corruption score drops
for all twelve arm/seed bundles. S remains a strong fully costed baseline:
report every metric, cost, and all-seed paired N-minus-S intervals using the same
methods, but do not add an unmotivated N-versus-S qualification gate. Predeclare
absolute means/95% intervals for all four arms and A-H, N-A, N-S paired intervals
for `task_utility`, `joint_success`, `greedy_joint_success`, `consistency`,
`pixel_mse`, `net_utility`, `runtime_net_utility`, `runtime_cpu_net_utility`, and
`cpu_net_utility`. Only the six table endpoints above affect confirmation;
the two CPU-named metrics use batch cohorts and the other metrics use physical
sources. Absolute intervals reuse the same bootstrap against an all-zero array.
Passing
this protocol would establish the declared incremental contributions, not
superiority to S, general multimodal optimality, AV, device, or production fitness.

## Binding, retention, and one-shot failure

Before training, freeze and commit the complete root/independent Python+C source
inventory, native source/compiler policy, protocol SHA, full plan SHA/meaning,
and required environment/thread configuration. Verify the actual protocol bytes
against their recorded hash at both training preflight and test preflight.
Commit the implementation and frozen receipt before training.

During the billed build, create and lock the native binary/compiler argv and
version, actual numerical/environment metadata, TRAIN/validation manifests,
training/update receipts, selected model hashes/digests, complete cost ledgers,
measured reference, and readiness. These generated artifacts bind the pre-build
freeze and are verified before acquiring either opening marker. Optimizer
identity means the frozen `native-adam-v1` source/profile and its setup/update
receipts; final inference NPZ files do not export Adam moments or RNG state and
make no optimizer-resume claim. The selected in-process optimizer/RNG objects
are reused through residual training. Use the fixed core marker, never a
caller-provided path, and retain the same frozen provenance in every selection.

Retain all test input bytes or an exactly reconstructible frozen tensor artifact,
physical source/row identities and hashes, all three model/sampling seeds,
per-row endpoint/cost arrays, complete batch cohorts, negative controls, all
bootstrap settings/results, and the original exit status. Necessary model
exports belong in build cost; administrative lossless archival is separately
reported and never a hidden budget credit. A failed, partial, or interrupted
test opening stays consumed. Preserve every failure and do not tune against,
rerun, replace, or recycle core-c1 held-out results. New findings require a new
scientific protocol and independent evidence, not a changed passing label.

## Pre-test implementation revision history

Registration v1 was committed before the first core-c1 split construction. The
first actual build, source 893a13fd16/freeze a80b6b6e23, exited 1 at calibration
matching before compilation or model updates. Its original error and full cost
are retained in runs/codex-cloud-core-c1-t1/REPORT.md. No validation score or
formal test was produced.

The existing class-wise matcher imposes extra source/target cyclic joint cells
beyond the two balanced margins; the frozen fresh TRAIN metadata cannot satisfy
that pattern. Revision v2 prospectively replaces only this subset-selection
algorithm with global balanced flow. It preserves the same TRAIN/validation/test
seeds, physical generator, 72/6 margin counts, model/objectives, complete budgets,
all six statistical requirements and experiment-wide one-shot test rule. The
legacy r2 cyclic selection and all prior failures remain unchanged. Hand-array
matching proofs and a new source/protocol freeze precede another actual build.
This revision is based on TRAIN construction failure, not test outcomes.

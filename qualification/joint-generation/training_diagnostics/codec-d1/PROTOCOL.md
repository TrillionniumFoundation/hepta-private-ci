# Codec-d1: one prospective complete TRAIN-only execution control

This is a preregistration draft for review, not an execution or a new
confirmation. Only this new document is authored here. The reviewed protocol,
plan, diagnostic driver, shared-engine changes, codec source, numerical backend,
and complete cost inventories must be committed and frozen before START.
Execution remains in the saved hepta-private-ci Codex cloud environment, without
changing permissions, merging, deployment, alternative environments, or quota
workarounds. Existing protocols, failed results, and opening markers are intact.

## Question and fixed comparison

Does instance-local reuse of the finite learned twelve-image PNG codebook save
complete preparation-plus-serving CPU/operator work after its real preparation
and storage costs, and do the released build budgets support useful content
updates and more stable development results across seeds? Unit equivalence,
faster isolated PNG calls, and a higher update count cannot alone answer this.
The optimization applies only to this fixed twelve-code RGB8 prototype. It
does not establish open-vocabulary/image generation, AV, device, production,
general multimodal optimality, or a passed scientific benefit gate.

Run exactly four fresh-process builds, in this order, without choosing timing:

| Slot | Pair | Codec profile |
| --- | --- | --- |
| 1 | AB, A | `rowwise-png-v1` (uncached) |
| 2 | AB, B | `local-png-codebook-v1` (cached) |
| 3 | BA, B | `local-png-codebook-v1` (cached) |
| 4 | BA, A | `rowwise-png-v1` (uncached) |

Pairs are slots (1,2) and (3,4); report B-minus-A for both, in the same direction.
Retain every wave, outlier, and terminal state. No pilot on this partition,
warm-up build, fifth build, replacement wave, faster-sample selection, or
timing-conditioned repetition is authorized. New processes are not permission
to preload model/data/codec artifacts outside their charged build phases.

## Allowed sample and deterministic internal partition

The sole source pool is the existing core TRAIN profile: seed **304797655**,
twelve source classes, sixteen physical sources per class, eight instructions,
and two sensor variants: **192 sources and 3072 rows**. Its brightness,
background, noise, shift, renderer, instruction, and source-identity equations
remain those of `independent.data_v2`. Do not use core validation, core test,
r2 validation/test, a new formal split, or any opened formal scores to tune this
diagnostic. Previous core formal failure remains a failure.

The public partition salt is `hepta-codec-d1-train-source-partition-v1`.
For every physical source in source class c, rank the byte digest

`SHA256(UTF8(salt + U+0000 + decimal(c) + U+0000 + source_id))`.

Use lowercase decimal class numbers 0..11, ascending digest bytes, and source ID
as the deterministic tie breaker. Of each class's sixteen sources, the first
twelve are **fit**, the last four **internal monitor**. Thus fit has **144 sources,
2304 rows**; monitor has **48 sources, 768 rows**. Keep all sixteen instruction/
variant rows of each source together and retain the original parent-pool row
order within each subset. The split formula is frozen before data construction;
matching failure does not authorize another salt or source permutation.

Each build's diagnostic-only provider must call `dataset('train', original_profile)`
and no other split constructor. The original profile keeps its three inert
train/validation/test metadata keys for schema validation; these keys grant no
construction capability. No unmodified entrypoint that constructs official
validation is allowed. Both subsets carry explicit parent-TRAIN provenance,
pool/role/source hashes, row identities, and counts. Engine use of the word
"validation" for the internal monitor must not mislabel it as an untouched
official validation fold.

Decoder/base pretraining, adaptation, objective kernels, and the existing
deterministic 72-row source/target-balanced calibration use **fit only**.
The monitor supplies the fixed LR selection and development observations only,
never gradients or a source for fitted normalizers. Constructing the pool,
partitioning, manifests, required exact NPZ/data exports and their compression
belong inside each build's charged common phase. Do not construct once outside
the timer and attribute only a cheap reload to later slots. Preserve disjoint
fit/monitor physical-source and input hashes without constructing other splits.

## Shared methods and genuine budget opportunity

Every slot runs all four static methods: supervised CE weight 1.0 (S), anchor
CE weight 0.2 (H), additive utility plus CE 0.2 (A), and NDU plus CE 0.2 (N),
with fixed rho=1.5. Each uses seeds **11,23,47**, hidden dimension 32, learned
decoder300, dense supervised base pretraining500, minibatch64, learning rates
{0.001,0.003,0.01}, the same content equations and initialization, the existing
index/view-mask RNG stream, `folded-mixed-encoder-v1` adaptation, and
`native-adam-v1` adaptation optimizer. Shared base training keeps its dense
NumPy path. All adaptation decoders remain fixed. No earlier core checkpoint,
optimizer state, selected LR, critic, or cached output table is imported.

All three LRs and seeds are genuinely searched: nine candidates per method,
36 per build. The selected full-view LR rule is unchanged except for the
TRAIN-derived monitor and common reference below. Selected residual updates
reuse optimizer/RNG objects, retain frozen LR, and admit complete three-seed
rounds. Reserve worst work before drawing examples/masks, charge only actual
executed mask work, and use actual update-unit deltas in forecasts. There is
no unused critic, objective gradient, padding, budget increase, or deliberate
training slowdown to manufacture an apparent codec benefit.

Every method in every slot keeps **12,000,000,000 declared units and 10.0 CPU
seconds**. Each method is charged the whole common build, not a quarter share,
and all its setup, actual nine-candidate training, monitoring, selection,
serialization, selected residual updates/revalidation, and service preparation/
measurement. Parent and compiler-child CPU, allocation, numerical discovery,
binding, runtime output, hash/base64/JSON and bookkeeping remain real costs.
Required fit/monitor and model artifact writes stay inside their build phases.
Static methods run always-full service, with fixed batches up to 64 and the
unchanged request cap and horizon H=100000. Shared full calibration remains
three seeds times three repeats times 72 requests: nine measures/648 outputs.

The chosen codec must be used consistently by every applicable actual service
in its slot, including common calibration and selected monitor service. Pure
probability/observer-only candidate monitoring must not fabricate PNG work.
Cached preparation is per immutable generator/measurement: actually decode all
twelve codes, quantize, encode PNG, hash and base64 them, bind exact decoder
bytes, and charge the preparation before service. No shared/global/cross-model
codebook and no cache surviving into another fresh build is allowed. Requests
retain the same two draws, CDF edges, sampled choices, caption/JSON and byte
accounting. Rowwise default remains unchanged. Codec-aware request/preparation
inventories and residual forecasts must be reviewed before running; a rowwise
forecast is not automatically an accurate cached forecast.

## One net-cost reference, with cost dimensions kept separate

Freeze **R** from the first planned uncached slot's seed11 fit-TRAIN full-service
calibration: the existing median over the three repeats' per-row raw service
CPU. Bind R to that first slot, source/inputs, model, costs, and sampling seeds.
Use this one R for net pricing in all four builds. Later slots retain their own
observed medians but cannot replace R, borrow a formal-fold reference, select
a faster repeat, or run extra rowwise calibration inside a cached slot.
Failure before the registered reference is obtained is a hard stop.

The primary efficiency evidence is absolute common/build/preparation/service
CPU and declared units, with all actual preparation and samples retained.
Also report the fixed workload's `prepareCPU + sum(batchServiceCPU)` and its
per-request value. Do not add this amount to build CPU again if it is already
included there. Keep the complete horizon-priced CPU-net decomposition visible
with price0.02, H100000, full common attribution, and the one bound R; no
normalizer change may conceal a larger real cost.

Report storage as a separate vector: cache prepare count, temporary decoded and
quantized array payload bytes, prepared PNG bytes, hash/base64 bytes processed,
retained encoded ASCII payload bytes, transmitted output bytes, and retained
artifact/archive bytes. The codebook holds twelve entries bounded by 65536
encoded ASCII payload bytes per instance. These counters are not Python heap,
RSS/peak memory, memory rental, hardware FLOPs, energy, or a combined CPU-plus-RAM
price. A storage/CPU tradeoff must be stated, not collapsed into an invented
scalar improvement.

## Byte/RNG/content-prefix evidence and retention

Retain canonical source/profile/plan/code/compiler/library identities and all
pool/fit/monitor bytes or exactly reconstructible frozen NPZ artifacts. Shared
base model bytes, input manifests, numerical backend and library bytes must
match across slots; a mismatch is not explained away as timing variance.
Retain real calibration and selected-service per-batch costs, actual PNG and
canonical JSON bytes, sampled choices, decoder/codebook fingerprints, and
pre/post sampling RNG states. Keep all row identities and seeds. Do not retain
only the best sample, only a hash when the required payload was discarded, or
an output reconstructed with a renderer instead of the learned decoder.
The same-base calibration has identical inputs and sampling states across
slots, so its sampled PNG/JSON/choices and final RNG states must match exactly.
Selected terminal models may legitimately have different numbers of updates;
their outputs are retained, not falsely required to match different content laws.

Capture **actual candidate checkpoints at steps [1,32]**, for all 36 candidates
in every build. After each registered step retain the model/content digests,
optimizer moment/clock digests, the completed step's loss, the training
index/view-mask RNG state, current index/full-mask lists, and the cumulative
canonical draw SHA through that step. The cumulative hash
includes every prior index/mask draw through32, not only the last mask. Input
manifests and row bytes make those draws exactly interpretable. Compare the
registered per-method/LR/seed checkpoints across all four slots, with the same
base bytes and frozen content/optimizer implementation. No extra optimizer
updates, replayed models, or surrogate checkpoints are used as prefix proof.
This training RNG is distinct from the service categorical-sampling RNG recorded
with generated outputs. Hash/capture/persistence CPU stays inside the billed
candidate interval and retains byte counters; it is not an uncharged proof added
after a budgeted build. These are live parameter/state witnesses, not an
independent gradient-byte witness. The fixed objective/native-Adam equations
and existing hand-authored gradient/equivalence tests remain supporting evidence;
no additional gradient hook or learning execution is required by this protocol.

This proves the registered live checkpoints and draw prefix, not identical
terminal weights after unequal training lengths or an optimizer-resume artifact.
If a valid candidate never reaches32, retain its terminal state and report the
diagnostic inconclusive/failed, without a replacement build or larger cap. A
complete build without a hard fault may still continue the remaining scheduled
slots as a soft outcome; a byte/identity mismatch is a hard stop. Report original
terminal updates, selected LRs, weights and decoder-fixed checks separately.

Raw retained artifacts are bounded at **32 MiB per build**, including failed and
partial builds, logs, data/model/receipt/output evidence. A verified lossless
archive may replace redundant loose copies: retain its inventory and per-file
hashes and reopen/verify all entries before removing duplicate copies. No state,
slow sample, failing receipt, or output may be dropped to fit the bound. Preserve
all terminal states; archive/retention failure is a hard diagnostic fault.
Required data/model serialization and live prefix capture remain charged build
work. Subsequent read-only proof comparison, descriptive analysis, lossless
retention verification and final
administrative persistence have separately recorded actual CPU/work/bytes,
including failures, and are not credits against the ten-second builds or
evidence of equal cumulative research budgets.

## Entry, stop rules and descriptive analysis

The fixed diagnostic identity is `codec-train-d1`, with its new plan under
`training_diagnostics/codec-d1/`. It is not an evaluable experiment: its registry
capability must reject formal evaluation before any data constructor or marker
operation. Do not invoke a core/r2 evaluate entrypoint, construct official
validation/test, read formal scores for tuning, or alter any old opening marker.

Commit the complete implementation, plan and this protocol, then the immutable
freeze, before the sole control. Exclusively create the experiment-wide
`START.json` once guard before the first pool/build; bind the four slot names,
variant order, paths, source/protocol/plan hashes and environment. Fresh-process
slot directories also use exclusive creation. A completed or partial once guard
blocks a second output directory or run. Persist one terminal `COMPLETED.json`
or `PARTIAL.json`, retaining START and every completed/partial slot forever.

On an actual hard budget breach, zero completed updates in any candidate,
source/model/input/RNG identity fault, codec
byte/equation equivalence fault, data-capability violation, or storage/retention
failure, stop remaining planned slots and preserve the original nonzero status,
exception, partial costs, and explicit unexecuted slots. A complete valid build
with negative/unstable diagnostic means or `selection_ready=false` is a soft
development outcome: retain its status2 where returned and continue the remaining
planned ABBA slots. Status2 is soft only with valid complete receipts and no
hard fault; it does not authorize a formal opening. Do not retry a slow build.

Report every pair, seed, method and slot: common/build/preparation/service costs,
operator units, candidate/selected/residual updates and consumed units, complete
storage payload vector, selected LR, and internal-monitor raw utility, joint
success, fixed-rho risk utility, greedy behavior and actual corrupted-decoder
score drop. Record any additional post-build observer/analysis cost separately
and never use it to reselect or stop content training. Use only development
point summaries: per-seed/pair differences, positive/zero/negative fractions,
range and dispersion, with all values visible. The two timing pairs and repeated
model seeds are not a large independent performance sample. There is no
performance CI, new qualification/significance threshold, or test-like gate.

Predeclare the engineering directions for both pairs and all four methods:
lower complete attributed CPU per actually applied adaptation update; more
selected-model content updates/examples within the unchanged caps; and lower
same-base calibration preparation-plus-service CPU per request. The first ratio
uses the entire attributed build CPU divided by all actual search plus selected
residual adaptation updates, with common pretraining reported separately rather
than silently added to its denominator. Report selected per-seed update counts
separately so discarded search steps cannot stand in for trained retained models.
Units and storage remain separate coordinates. Report every direction even if
adverse, not whichever component happens to favor caching. Lower CPU with larger
retained payload is a measured tradeoff, not an all-cost dominance claim.

More updates are an opportunity-cost mechanism, not proof of useful generation.
Relate them to the monitor's raw/risk/greedy outcomes and consistency across both
pairs and all seeds. If complete measured costs do not improve, or content gains
are absent/inconsistent, report no demonstrated improvement or failure plainly.
Keep uncertainty and adverse results; do not increase budgets, drop a seed, choose
the faster pair, or relabel unit equivalence as generation benefit. Any next
repair must have source evidence and a new prospective development plan.

## Pointer for a future independent-confirmation draft only

After this diagnostic, a separate review draft may inventory every prior formal
study, opened fold, failed/partial result, development/OOF diagnostic, and model/
hyperparameter selection history. It must specify expected effects and their
uncertainty, genuinely independent samples, endpoints/selection, and an explicit
review of error control across repeated confirmations. Existing nominal 95%
intervals cannot retroactively share an alpha budget that was never registered.
No alpha allocation, new confirmation identifier, data seed, test opening, or
execution is authorized by codec-d1. R1/r2/core failures remain unchanged, and
this TRAIN-only control can inform only a future prospectively reviewed design.

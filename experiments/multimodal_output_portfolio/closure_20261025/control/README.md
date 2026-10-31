# Paired public control, a distilled actor, and a conservative cost gate

This study implements and executes an additional control candidate on the frozen
five-seed actual-output generators. It does not establish global NDU optimality,
train an all-modality foundation model, or install parameters into the native
runtime. Its first completed result is negative for cheap replacement: **all
five selected gates retained the existing cached strong feedback controller**.
The full prospective run and a bounded capacity repair with a second new-source
confirmation are complete. Neither qualified a cheap replacement. All
**136,192 actual requests completed without failure**, with results retained.

## Decision problem and implementation

`features.py` exposes 481 coordinates: the four current public latent blocks
(384), 32 mean-pooled values from the current actual binary image, 64 fixed
Gaussian projections of the eight current actual token IDs, and the remaining
horizon. This fits the 512-coordinate native input limit. It avoids an
additional learned image encoder in the cheap controller; the underlying
generator still executes its original image encoder and actual emitters.
The projection seed is fixed before training. Private targets, owner RNGs,
source identities and experiment labels do not enter the policy port.

At H1 the critic estimates the signed difference

\[
D(h,a)=\mathbb E[\exp\{-2(U^{a}-.002\,1_{a\ne stop})\}
                         -\exp\{-2U^{stop}\}\mid H=h].
\]

The stop difference is exactly zero. Lower predicted differences are preferred.
The terminal semantic-only action is masked because it changes no emitted
media and incurs cost. H2 targets use an H1 decision fitted on the other source
fold, followed by the held source's actual selected terminal result. They do
not use the best realized grandchild outcome. All views, generation scenarios
and public nodes from one source pair stay in the same fold. This is one
approximate policy backup, not an exact Bellman solution or a uniform
conditional-error certificate.

`models.py` also trains an actor by distilling the original strong feedback
controller. The gate accepts a cheap action only when the actor and paired
critic agree and actor confidence meets the frozen threshold. Every reached
fallback executes the original cached teacher. A distinct `None` candidate
omits the entire cheap precheck. Thresholds are selected using historical
development point estimates: no decrease in raw CE or exact success, followed
by maximum quoted net CE. The quote measures historical feature/head kernels,
including overlap when a cheap check falls back; it is not a full request or
energy measurement.

## Frozen development result

`development-001` uses only the previously executed `forecast_fit[480,736)`
and `forecast_calibration[448,576)` sources. Every original data tensor and
actual-media archive is checked against its stored hash before use. The new
critic, actor and threshold are frozen before prospective source access.

| Seed | Paired difference MSE | Zero-difference MSE | Actor/teacher H1 action agreement | Selected gate |
| --- | ---: | ---: | ---: | --- |
| 17 | 0.224638 | 0.224927 | 52.3438% | cached teacher |
| 29 | 0.206090 | 0.206496 | 56.6016% | cached teacher |
| 43 | 0.225924 | 0.219483 | 51.4551% | cached teacher |
| 59 | 0.232657 | 0.228232 | 55.9863% | cached teacher |
| 71 | 0.216095 | 0.207065 | 57.9297% | cached teacher |

High-confidence thresholds that retained development quality accepted too few
cheap decisions to repay the precheck. Lower thresholds often improved CE
while losing exact success, and were rejected. All threshold candidates,
including their unsuccessful quality and quoted-cost outcomes, remain in the
development evidence. Selected-action predicted moment differences were
overoptimistic by about 0.048 to 0.089 on the historical selection table.
Realized H1 hindsight moment regret was 0.169 to 0.181. That hindsight optimum
uses privately scored potential outcomes; it is not an attainable online
oracle. Sampled MSE includes outcome noise and does not bound conditional
estimation error.

## Historical sources with new futures

The conditional evaluation executed all **10,240** registered requests:
32 already-used source pairs × 8 views × 2 new future draws × 5 generator seeds
× 4 policies. There were no failed requests. This supplies new generation
futures, **not new independent sources**.

| Executed policy | Raw CE | Exact joint success | Mean request wall ms |
| --- | ---: | ---: | ---: |
| Cached strong teacher | 0.216272 | 58.6719% | 10.5211 |
| Paired critic | 0.196308 | 57.5000% | 8.3869 |
| Distilled actor | 0.203625 | 57.4219% | 7.3208 |
| Selected gate | 0.216272 | 58.6719% | 10.7037 |

All 2,560 selected-gate/teacher pairs have identical action paths and actual
terminal outputs. **Zero of 4,288 gate decisions used the cheap candidate.**
The measured +0.1826 ms gate-minus-teacher difference has a nominal 97.5%
source/seed bootstrap interval of [-0.1395, +0.7187] ms. Both rows execute the
same fallback algorithm; even a future clock interval excluding zero would
not demonstrate an actor-gate improvement or a dynamic-information benefit.
All four-price simultaneous bands for this contrast include zero.

An independent review reproduced the raw CE and actual-cost curves, checked
literal source/seed bootstrap replicates, and inspected every saved media
hash. Among 3,616 H1 selected-action calibration observations, all 715 stop
decisions preserve the current draft byte for byte and have zero realized and
predicted stop difference. The other 2,901 observations are actual final-step
continuations. Shared initial drafts and shared action paths are identical
across the paired policies and future streams.

## Prospective result: 256 new source pairs

`FRESH_PROTOCOL.json` binds the trained candidates, selected thresholds,
generator/teacher/sensor/observer bytes, allocator, runner, analysis and shared
source files before the new role is loaded. The registered primary census is
**81,920 requests** on the 256 source pairs assigned to `closure_control`.
The allocator checked available prior source/use records; unknown external
experiments and MNIST writer clusters are not certified absent.

| Executed policy | Raw CE | Exact joint success | Mean request wall ms |
| --- | ---: | ---: | ---: |
| Cached strong teacher | 0.163550 | 54.1211% | 12.9716 |
| Paired critic | 0.162466 | 53.0127% | 10.4049 |
| Distilled actor | 0.167432 | 53.3740% | 9.2467 |
| Selected gate | 0.163550 | 54.1211% | 13.1473 |

The paired critic saves 2.5668 ms on average but loses 1.1084 percentage points
of exact success (nominal 97.5% interval [-1.9825, -0.2637] pp). The distilled
actor saves 3.7249 ms while losing 0.7471 pp ([-1.4551, -0.0048] pp). Its raw
CE point difference is +0.003881, with interval [-0.005728, +0.013858]. These
are a quality/cost tradeoff, not qualified replacements under the registered
joint noninferiority and cost gate.

All **20,480** selected-gate/teacher pairs have identical paths and terminal
outputs. **Zero of 34,472** gate decisions use the cheap alternative. The
gate-minus-teacher wall difference is +0.175690 ms, interval
[-0.069894, +0.496843] ms. This remains the same fallback implementation,
not an actor-gate benefit. Every registered gate wall/CPU price band crosses
zero. The shared host produced retained wall-time maxima from 456 to 746 ms;
these tails materially widen high-price exponential cost bands. No timing
outliers were removed, and CPU and wall sensitivities remain separate.

On new selected H1 actions, paired-critic predictions have mean error -0.078104
over 16,946 samples. The four-policy realized hindsight CE is 0.244338,
0.080787 above the teacher; that private, realized-future selection is neither
an online conditional oracle nor a global action optimum.

## Exploratory fixed/nonfeedback baselines

The additional `supplemental/PROTOCOL.json` was registered **after primary
collection had started**. It remains exploratory and never replaces the
primary comparison. It adds 40,960 actual requests from the same 256 pairs:
the previously frozen best nonfeedback reference per seed (fixed, static or
initial-only route), and fixed allocation `(refine_image, refine_text)`.
Every reached decision really extracts the same cached full public draft
features; committed fixed/initial-only plans ignore subsequent features.
These reads and all generation/storage work are charged. The initial and
action-path future RNGs match the primary study, permitting paired quality
comparisons. These baselines run in separate blocks from the primary policies;
their measured clocks are descriptive and do not support a randomized
interleaved cost-superiority claim. They add zero independent source pairs.

| Teacher minus baseline | Raw CE difference and nominal 97.5% interval | Exact success difference and interval |
| --- | --- | --- |
| Frozen strong nonfeedback | +0.012322 [-0.000272, +0.025082] | +0.5908 pp [-0.0977, +1.2550] |
| Fixed allocation | +0.019399 [+0.004625, +0.034722] | +1.0791 pp [+0.4492, +1.8165] |

The fixed-allocation comparison is favorable on this exploratory panel. The
strong-reference intervals still include zero. Neither result supplies a
global-optimality certificate, and neither can convert the separately timed
baseline blocks into an interleaved cost experiment. All 40,960 baseline
requests start from the paired primary public state; all 1,667 matching
teacher/baseline paths also match terminal media exactly.

## Bounded capacity repair and independent confirmation

The repair reused only the original historical fit/selection tables. It kept
the paired critic, features, teacher, threshold grid and zero-quality-loss
development admission unchanged. It compared the existing actor with two
fixed larger actors, without searching fresh outcomes or stopping early.

| Actor | Mean fit action fidelity | Mean selection action fidelity |
| --- | ---: | ---: |
| 32 hidden, 600 steps | 68.6230% | 51.2598% |
| 128 hidden, 2,000 steps | 83.7949% | 53.0508% |
| 256 hidden, 2,000 steps | 86.1416% | 54.2090% |

These are actual root-H2 plus child-H1 nodes. The earlier H1-only diagnostic
also included a counterfactual root-H1 node and has a different denominator.
Wider models reduce training underfit substantially; the much smaller
selection gains leave a large generalization gap. This does not prove an
information-theoretic impossibility of the public feature representation.

Only seed 17 / 128 hidden / 2,000 steps / threshold .5 selected a nonfallback
gate under the unchanged development rule. Its historical selection CE gain
was +0.007890, exact success difference zero, and cheap acceptance 20.81%.
The other nine newly trained candidates retained the fallback. All candidates,
threshold results, training traces and checkpoint bytes are preserved.

That single seed-17 candidate was then frozen before accessing **96 further
source pairs**, disjoint from all primary and development pairs. Its 3,072
actual requests randomly interleaved the candidate and cached teacher within
each paired source/view/future. The other four training seeds did not
contribute observations to this confirmation.

| Candidate minus cached teacher | Estimate | Nominal 97.5% source-cluster interval | Registered condition |
| --- | ---: | ---: | --- |
| Raw CE | +0.001786 | [-0.009143, +0.013000] | Lower endpoint >= -0.005: **fail** |
| Exact success | -0.2604 pp | [-1.1068, +0.5868] pp | Lower endpoint >= -0.5 pp: **fail** |
| Mean request wall time | +0.186023 ms | [-0.075161, +0.486676] ms | Upper endpoint < 0: **fail** |

The candidate used 564 cheap decisions out of 2,584 (21.83%). Thus the negative
confirmation concerns an actually exercised gate, not an inactive fallback.
Both policies saw the same initial draft and paired path RNGs; the random
first-policy counts were 789 teacher and 747 candidate. All price bands cross
zero. The larger actor remains an unqualified research candidate, and the
conclusion is conditional on this single generator seed. No further sampling
or candidate search followed this registered confirmation.

## Evidence and measurement contract

The deployed port receives only `PublicFrame`. Every action is flushed and
fsynced before constructing its future RNG. Actual outputs are stored as 204
lossless bytes (1,568 binary pixels and eight token IDs), fsynced and read back
exactly. The closed media is independently re-read and scored afterward.
For each cheap-evaluated H1 action, its current stop draft is separately
preserved, then scored privately after the run to assess selected-action
calibration. This evidence never enters online decisions.

Request clocks include initialization, all executed public features, both
small diagnostic heads for either standalone candidate, actual fallback work,
generation, durable action commitments and durable terminal-media readback.
Resident loading, source setup, diagnostic draft archival, offline scoring and
analysis are separately recorded and remain in the full child-process cost.
No failures or timing outliers are removed. Raw wall/CPU price curves evaluate
`CE(U - price * actual_ms)` before aggregation, rather than subtracting a mean
cost from CE. Development action proxy cost and measured request time are
different quantities.

Bootstrap weights are crossed over source pairs and the five trained seeds,
keeping views and future draws together and policies paired. Component
intervals and finite-grid price bands are nominal; they are not finite-sample
coverage guarantees. Price bands apply separately to each contrast and each
clock. Neither a predicted maximum nor a realized four-policy hindsight
maximum is a feasible conditional oracle.

The complete local evidence is under `ndu-runs/control/`: process registrations,
exact-child receipts, full logs, trained bundles, every selection candidate,
actual media, action commitments, requests, scores and analyses. Repository
result files retain the small aggregates and hashes. Raw artifacts are not
copied into the repository.

`ARTIFACTS.json` lists all 83,549,791 bytes of new evidence and their hashes.
`ARTIFACT_INPUTS.json` enumerates the exact older weights, source archives,
manifest and historical fit/selection media required for restoration or
retraining. `PROCESS_EVIDENCE.json` retains twelve successful exact-child
receipts, totaling 1,940.41 recorded child CPU seconds. Summed child wall
durations are not elapsed end-to-end time because some processes overlapped.
Source/protocol/report files belong in Git; the complete run and model evidence
are separately preserved by the coordinating workflow.

## Reproduction entrypoints

Use the repository root, the pinned Torch environment, CPU thread count one,
and fresh output directories. Run `control.control_tests`, then
`control.development`, `control.registry`, `control.rollout` and
`control.analysis` under the common Python module prefix
`experiments.multimodal_output_portfolio.closure_20261025`.
`control.process` wraps a child module and retains its exact command, versions,
PID, exit code, complete wall/CPU cost, peak RSS and log hashes. The
supplemental entrypoints are `control.supplemental.tests`, `.register`, `.run`
and `.analysis`. Frozen protocols and completed runs must never be overwritten.
Capacity repair uses `control.repair.run`; its separate single-candidate source
confirmation uses `.confirmation_registry`, `.confirmation_run`, and
`.confirmation_analysis`.

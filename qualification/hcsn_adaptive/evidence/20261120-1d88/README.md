# HCSN next-stage implementation and sealed results

Date: 2026-11-20 America/New_York. Some immutable experiment IDs use the following UTC date.
Baseline: `0cee57ca617e0324e2df8e9447a2c075a6c76952` on
`integration/hepta-single-main-20261113-ab5b`.

## Decision

The research backend, complete-state contracts, six readout learners, real-time sensor adapter,
task-loss boundary experiment and small encoder-pretraining matrix are implemented and exercised.
All **169 formal train/dev and final configurations** completed, plus six separate smoke configurations.
Selections across every campaign were sealed before any real final holdout claim.
The global seal SHA256 is `c3df4394b899f9ace09ae42b03f7606ab2ae1d714c459236e30dee4187ea3c14`.
There are no missing formal final results or unsettled formal training-cost records.

The mechanism works as a finite-grid, piecewise differentiable research prototype, with AD/FD
checks at the inspected points away from remapping/upwind knots. The performance hypotheses are mostly
unconfirmed: input-driven dynamics did not reliably beat fixed dynamics; the actual task-loss
boundary search selected no update; full HX equity did not add reliable value over simpler features;
and this HCSN CPU implementation was substantially slower than the GRU comparator.
These results do not justify replacing Transformer/SNN backbones or replacing whole-network BP.
All changes remain Draft research proposals. No production adoption, merge or deployment occurred.

## What was implemented

| Workstream | Concrete implementation | Current evidence boundary |
|---|---|---|
| P1 batched input-driven flow | Independent sample density/content, learned input drift, conservative moving-boundary transfer, continuous expected events | Mechanism and gradients pass; task benefit is inconsistent |
| P1 continuation boundary | Auxiliary observed-input MDP and a separate actual task-loss paired-counterfactual teacher | Auxiliary objective is not task MSE; TaskADV accepted no update |
| P1 feature ablations | Risk, margin, occupation, finite-policy Call masks; separate fixed-parameter full-HX adapter | Masks/substitution still pay the original Call solve |
| P1 bounded history | Erlang refractory phases and fixed-size complete streaming state | No strict minimum delay; fixed storage does not imply persistent useful memory |
| P2 learners | Frozen, ridge, BP, zeroth order, programmatic coordinate edit, edit-then-BP | Same 19-parameter readout mask; encoder frozen; no actual WSP program-discovery reproduction |
| P2 state/receipts | Python full checkpoints; Rust V2 method evidence, cost and complete-state custody/codec contracts | Rust production backend codec and live adoption are not installed by this study |
| P3 real timestamps | UCI 864, 15 numeric sensor channels, physical inter-observation intervals, chronological purged split | One small multisensor dataset; no raw audio/image/text benchmark |
| P4 capacity/pretraining | HCSN/GRU widths 4/8/16, three seeds, SSL checkpoints 0/8/24, one raw ridge baseline | Small capacity pilot; unequal parameters; no foundation-scale or Transformer/SNN benchmark |

The finite-policy value solves `(rho I - G) U = running_reward - event_cost * intensity`.
It may be negative and is not He--Xiong equity. Full HX uses the existing nine-parameter equity
implementation as `sum_active p_i E_HX(x_i) / b_HX`, with phase/escape contributions zero.
Neither formulation proves a network-wide Bellman/QVI optimum or smooth-pasting task boundary.
Finite-cell overlap projection is piecewise differentiable and has grid-contact kinks. The auxiliary
MDP lookup and development selection are discrete. Successful AD checks do not establish a globally
smooth exact free-boundary operator or erase every discrete operation in the pipeline.

## Sealed matrix and statistical scope

| Campaign | Formal final configurations |
|---|---:|
| P1 future return / delayed recall | 36 + 36 |
| P2 future return / delayed recall | 18 + 18 |
| P3 real sensor variants | 12 |
| P4 encoders and raw baseline | 19 |
| Actual task-advantage boundary | 12 |
| Full-equity feature quality | 18 |
| Total | **169** |

The three seeds are model randomness on the same fixed data split, not three independent datasets.
Reported SD is sample standard deviation across those seeds, not a confidence interval.
Budget ceilings are common within each comparison; actual sample work, FLOPs and parameter counts
are not all matched. All alternatives, NoUpdate outcomes and costs are retained.
No source, hyperparameter or selection was changed after the global finalization seal.

## P1: input-dependent flow and ablations

Test MSE, three-seed mean:

| Variant | Future return | Delayed recall |
|---|---:|---:|
| Fixed dynamics | 0.26697058 | **0.00252313** |
| Input drift | 0.33651999 | 0.00925963 |
| Free scalar boundary | 0.37316651 | 0.00355058 |
| Input boundary | 0.35416840 | 0.00355058 |
| Auxiliary continuation | **0.25982362** | 0.00384453 |
| Drop Call feature | 0.30678377 | 0.00905354 |
| Drop risk feature | 0.33570002 | 0.00928219 |
| Drop risk and Call | 0.30634152 | 0.00908707 |
| Drop margin | 0.33184302 | 0.00946723 |
| Drop occupation | 0.34246417 | 0.00924694 |
| One refractory phase | 0.33461327 | 0.00911100 |
| Four refractory phases | 0.33833306 | 0.00936143 |

The auxiliary continuation mean improvement on future return is about 2.7%, driven by one seed;
the other two are worse than fixed dynamics. On recall, the selected input-boundary gain is zero
for all seeds, so its boundary is the same constant 0.25 as the scalar control. The auxiliary
continuation boundary is also constant (0.1875) on that task. Those outcomes do not demonstrate
input-adaptive boundary benefit. Last+mean pooling itself preserves early cue information;
recall accuracy is not a standalone measure of internal neuronal memory capacity.

## Actual task-loss continuation advantage

The independent TaskADV pilot uses the full causal prefix state, current input and a causal summary.
A paired low/high boundary pulse is evaluated with the same future training suffix and training label.
Its teacher is `A = loss_low - loss_high - 0.01 * (events_high - events_low)`.
Deployment uses a smooth predicted-advantage gate without future inputs or labels.
This is one-decision finite policy improvement, not a solved global stopping problem;
the endpoint teacher does not prove that sigmoid interpolation is optimal.

All four arms across three seeds selected the zero-pulse NoUpdate control:

- Test task MSE: **0.62633735 ± 0.33899872**.
- Test MSE plus event cost: **0.63061407**; expected events: **0.42767198**.
- 81 nonbaseline candidates were computed without numerical failure; 84 dev queries including references were paid.
- The best task candidates' dev objectives were 0.52864 / 5.67631 / 0.85812,
  versus zero-control objectives 0.45272 / 0.49532 / 0.52558.
- FD/AD checks passed, maximum absolute error about `2.81e-9`.

Differentiability passed; task improvement did not. These absolute MSE values are not comparable
to P1/P2 because the readout split, state width and decision protocol differ.

## Full HX equity: task value and cost

Three arms share exactly one encoder trajectory per task/seed/split, the same non-Call columns,
the same readout mask and normalization rule. Test MSE, three-seed mean:

| Call arm | Future return | Delayed recall |
|---|---:|---:|
| Finite-policy Call | 0.29736667 | **0.01956249** |
| Drop Call | **0.29205828** | 0.02121811 |
| Full HX equity, fixed financial parameters | 0.29225269 | 0.02098063 |

Dev preselected full HX on future return and finite-policy Call on recall; all arms are still reported.
Full HX is nearly indistinguishable from dropping Call on future return and worse than finite Call
on recall. This does not establish that its additional economic structure earns a task benefit.
This experiment has three phases and a stronger ridge scaling than P1/P2; compare its arms internally.

The independent component benchmark (12 repeats, two warmups, one CPU thread) measured median times:

| Component | Median |
|---|---:|
| Finite Call solve, generator already available | 44.99 microseconds |
| Direct full-HX curve and application | 4.081 milliseconds |
| Full-HX frozen curve setup | 4.716 milliseconds |
| Frozen curve application | 5.260 microseconds |
| Finite Call fresh forward/backward | 0.4454 milliseconds |
| Full HX fresh forward/backward | 20.732 milliseconds |

Different objectives are being timed. Cached application is valid only for fixed financial parameters,
nodes, dtype and device; it does not train those cached quantities. Original finite Call computation
is retained in the functional substitution, so cached HX timing is not an end-to-end speedup.
The direct public API also duplicates parameter preparation relative to the prepared API.
Direct/prepared derivative agreement was within `7.99e-15`. A separate SciPy oracle supplement
matched normalized `E_HX/b_HX` at six default nodes within `6.66e-16`; the original Torch-only run's
"oracle unavailable" record remains unchanged. Extreme-domain certification is not claimed.

## Bounded state and numerical precision

For B=4, K=4, N=6 and 1/2/4/8 phases, complete streaming tensor payloads are
**1,312 / 1,472 / 1,792 / 2,432 bytes** at 32, 128 and 512 steps.
The phase waiting-time variance is `h^2/R`; with h=0.2 it is 0.04/0.02/0.01/0.005.
Finite R has no strict refractory minimum. BPTT tapes, retained outputs, matrices and runtime memory
are separate costs. By 512 steps the early intervention was almost forgotten in the inspected case.

The native-FP32 predecessor failed mass conservation at step 217, reaching about `3.00165e-5` error.
Its failed result and source are retained. The selected backend uses FP64 transport/state with
optional FP32 trainable layers and outputs. This is mixed precision, not a native-FP32 success.
No mass renormalization or relaxed tolerance was used. The eight-phase mixed profile's maximum
mass error at 512 steps was about `1.46e-13`.

## P2: learners on the same frozen features

Each method has the same 19 eligible affine-readout parameters and objective
`MSE + lambda/(N*O) * ||W||^2`, with an unpenalized bias. Test MSE and mean learner ledger seconds:

| Learner | Future MSE | Recall MSE | Future seconds | Recall seconds |
|---|---:|---:|---:|---:|
| Frozen | 1.87875808 | 0.78029032 | 0.03693 | 0.03486 |
| Ridge | 0.33651999 | **0.00925963** | **0.05474** | **0.03561** |
| BP | 0.27502402 | 0.06202456 | 1.35088 | 1.38933 |
| Zeroth order | 0.41004167 | 0.16595417 | 1.05096 | 1.22330 |
| Programmatic coordinate edit | 0.29273355 | 0.05623131 | 0.98448 | 0.99326 |
| Edit then BP | **0.27215155** | 0.06154737 | 1.27690 | 0.94952 |

Shared feature generation costs an additional 0.09148/0.10753 seconds per seed for the two tasks,
counted once across methods. Most learner wall time is per-step durable checkpoint work:
BP about 1.081/1.077 seconds; editing about 0.782/0.780 seconds.
Algorithm-operation intervals were BP 0.2214/0.2350 seconds versus editing 0.1629/0.1689 seconds,
still including nearby bookkeeping. These are not universal kernel speed ratios.
BP consumed 2,048 training examples per seed; editing consumed 6,144; ridge consumed 96.
The programmatic editor is residual-based coordinate optimization, not an LLM-discovered WSP replication.
Its discovery cost cannot be inferred as zero for a future real WSP implementation.

## P3/P4: real sensor quality and capacity

UCI Room Occupancy Estimation (DOI `10.24432/C5P605`, CC BY 4.0) provides 15 numeric channels:
temperature, light, sound amplitude, CO2 and PIR. The ambiguous CO2Slope field is excluded.
The 16-observation windows are chronologically split, purged and nonoverlapping; normalization is
train-only. There are 355/117/118 train/dev/test windows. Actual time intervals are preserved.
At the query arrival, its timestamp is known but its sensor values and occupancy label are withheld.
This is a multisensor task, not raw audio/video/text multimodal training.

P3 test MSE mean: fixed 0.03705936, input drift 0.03822938, no Call 0.03819372,
auxiliary continuation 0.03978136. The Call difference is small and inconsistent across seeds.
P3's 14.9040 seconds of settled operations include 14.5422 seconds of feature preparation
and 0.36185 seconds of readout fitting. Readout-only timing omits most cost.

P4's formal choices were made by dev MSE before opening test:

| Presealed choice | Width / seed / SSL step | Test MSE | Accuracy | Macro F1 |
|---|---|---:|---:|---:|
| Raw ridge | n/a | 0.06835536 | 104/118 | 0.277498 |
| HCSN | 16 / 47 / 8 | 0.06514946 | 105/118 | 0.358583 |
| GRU | 16 / 29 / 24 | **0.05113290** | **106/118** | 0.358533 |

True test class counts are `[103, 0, 5, 10]`; constant class 0 gives 87.2881% accuracy.
This diagnostic is arithmetic from the existing confusion matrices, not a newly selected trial.
Four-class macro F1 includes the absent class with zero contribution. The HCSN/raw improvement
amounts to one additional correct example; GRU/raw amounts to two.

All declared width groups, mean ± seed SD:

| Encoder | Width | SSL parameters | Test MSE | Selected SSL steps (11/29/47) |
|---|---:|---:|---:|---|
| HCSN | 4 | 246 | 0.04147913 ± 0.01013331 | 24 / 0 / 0 |
| HCSN | 8 | 370 | 0.04441711 ± 0.00680899 | 0 / 0 / 0 |
| HCSN | 16 | 618 | 0.06363900 ± 0.00682993 | 0 / 0 / 8 |
| GRU | 4 | 339 | 0.03657021 ± 0.00525847 | 0 / 0 / 0 |
| GRU | 8 | 759 | 0.05632589 ± 0.00884412 | 24 / 24 / 0 |
| GRU | 16 | 1,887 | 0.05130458 ± 0.01313875 | 24 / 24 / 24 |

These test values do not authorize changing the presealed choice to width 4.
HCSN selected the initial encoder on 7/9 tracks; GRU on 4/9. Their ridge probes were still fitted
with training labels. All training costs were paid, including tracks whose updates were discarded.
Selected-final results alone do not identify causal SSL gain without a predeclared same-track
step-0 final comparison. Increasing HCSN capacity did not show monotonic improvement.

Nine-track training-plus-probe ledger totals were **159.8554 seconds HCSN versus 9.1426 seconds GRU**,
about **17.48x**. Final evaluations added 9.2242 versus 0.3796 seconds.
Both used 24 updates and 720 backward examples per track, with unequal parameter/FLOP costs.
Peak RSS includes Python/Torch startup. Current evidence supports no HCSN training-time advantage.

## Validation, registry repair and remaining CI

- Exact final Python suites: 32 adaptive + 6 scale + 3 task-advantage + 2 equity = **43 passed**.
- `just test -p codex-hepta-learning-artifacts`: **165 passed, 1 skipped**.
- `just test -p codex-hepta-neuron`: **416 passed**.
- Scoped `just fix` and `just fmt` completed afterward; no Rust tests were rerun after formatting.
- The neuron test run used the repository's existing standalone replay helper after the full
  Cargo helper build hit a baseline app-server import error. Its BUILD/source/compiler hashes are archived;
  this is not a claim that the full Cargo/Bazel helper build passed.
- Old V1 candidate/clock/sparse-Q24 artifacts were not reinterpreted as density/delay snapshots.

The module registry repair changes metadata only. Full recheck found six byte/SHA rows and eight
word-count fields requiring correction, across nine modules (20 derived fields). All 40 technical
document bodies remain unchanged; afterward 40/40 derived metadata records agree with their blobs.
This includes the user-reported inference.control drift and is not a runtime-failure diagnosis.
The broader canonical docs verifier still fails identically on base and repair, with log SHA256
`68bcd4d398c5aef2033bf7f2f61037b7daca0b72d9f0f02c5ae890f3bb3d559d`.

CI is not represented as green. Inspected architecture failures are baseline Clippy findings;
learning qualification fails at baseline `thread_summary.rs:190` because `MultiAgentMode` is imported
only under test configuration. The implicated file blobs match the fixed baseline.
See [architecture source job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44862642406/job/136719240695)
and [learning source job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44861238681/job/136714871049).
The full root-cause evidence is in the audit supplement. A skipped identical-tree lane is not a substitute
for the failing source check. These unrelated baseline issues were not silently included in this research change.
The later [fixed-head CI follow-up](CI_FOLLOWUP.md) records additional unchanged-source failures:
Timestamp/SystemTime conversion, missing helper metadata and workflow triggers, daemon source closure,
stale references, toolchain mismatches, and three substantive NDU holdout error-contract assertions.
All five new receipt tests and all five new recovery tests passed in the inspected real CI jobs.
The NDU assertions remain failures; source equality is not a new successful baseline rerun.

## Review entry points

| Scope | Draft PRs |
|---|---|
| Registry repair | [6832](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6832) |
| Batched flow, continuation, learners, timed data, campaigns | [6835](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6835), [6837](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6837), [6838](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6838), [6839](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6839), [6840](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6840) |
| History/Call and encoder scaling | [6841](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6841), [6842](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6842), [6843](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6843) |
| Rust method receipts and complete-state custody | [6844](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6844), [6845](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6845) |
| Task-loss boundary and equity ablation | [6846](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6846), [6847](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6847), [6850](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6850) |
| Semantics and frozen configurations | [6851](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6851), [6852](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6852) |

Python PRs are stacked. Registry and the two Rust proposals independently target the fixed integration
baseline; merging the Python stack alone would not include them. This evidence PR is the review index.

## Reproduce the evidence, not the consumed holdouts

Run `python verify_evidence.py` in this directory after obtaining every committed binary part.
It assembles the split archives, checks each part and all archive hashes, and verifies every
listed member. It does not train, select, or reopen test labels. Use a new experiment identity for
any future scientific run; do not resume a consumed final holdout to obtain a new result.

`runtime-evidence-v1.tar.gz` contains **1,543 hashed files** plus its member manifest: frozen manifests,
data, selected/checkpoint tensors, all training/final receipts, costs, tests, source dependencies and
aggregation/finalization scripts. Its SHA256 is
`5951274b3565a7a77bdc18df22bbadeb18800214d0abb05971544356c77c8d4b`.
`audit-supplement-v1.tar.gz` contains **28 hashed files** plus its manifest, including CI logs,
independent result analysis, native-FP32 negative-control sources, registry and V1 preservation evidence.
Its SHA256 is `7b0e548695bb2ad687ce6800ca4df3355f32a13d251ff271cd6b11718901bbec`.
The additional `ci-followup-v1.tar.gz` preserves 35 hashed CI evidence files; its SHA256 is
`ea5882e80e579351f21b2d1541f72efbbe30236d4209bbb8503fa763a5f9991a`.
`ARTIFACTS.json` binds part bytes, hashes, Git blob identities and publication metadata.
`RESULTS.json` provides compact machine-readable outcome tables; detailed per-seed aggregates are
under `analysis/final-evidence-v1/` in the runtime archive. Source/runtime identity in the ROG-frozen
manifests is authoritative; historical pre-format manifests are not substituted for that identity.

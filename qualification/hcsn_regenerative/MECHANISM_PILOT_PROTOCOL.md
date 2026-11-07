# Prospective finite-volume regenerative mechanism pilot

Study: `hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-v1`.
This protocol is written before any task fit in this study. It is a new
exploratory study, with zero completion credit in the original 170-run
campaign or the separate NDU study. The source, operator bundle, qualification
receipts and ordered fit roster must be bound in the final frozen plan before
training starts. A template or this document alone is not that plan.

## Scientific scope

The numerical parent is a fixed-boundary log diffusion with deterministic
physical refractory time and fixed reset target. The implemented recurrent
state is a finite-dimensional `Q P_dt R` approximation: it lifts the full
current density, evolves it under the selected generator, and projects it
back to the declared basis. The approximation, including its projections,
is the actual model evaluated here. Repeated time refinement on a fixed
spatial grid is not assumed to converge to the continuum process.

This pilot evaluates task learning with a recurrent distribution, analytic
constant-payoff and risk features, and a learned observation/readout network.
It does not implement or test the historical complete financial HX payoff
model. It cannot establish external-task benefit, superiority to every
deployable architecture, old-capability retention or production readiness.
These limitations are not removed by low MSE or a small p-value.

## Frozen physical and representational choices

The base has `mu=-.1`, `sigma=.3`, `q=.15`, absolute log reset `.25`, initial
absolute log state `.35`, log boundary zero and physical refractory `.1`.
There are 81 FP32 probability coefficients. The base represents 64 uniform
active cells over `[0,2)`, an explicit exponential tail of rate 1, and 16
uniform remaining-time cells over `(0,.1]`. The tail may return or hit.
Exact interval durations are drawn from `.025,.05,.075,.1`; each is at most
the refractory duration. A complete 64-observation episode lasts at most
6.4 physical time units. Generator and boundary remain fixed within it.

Fixed kernels are constructed and checked in FP64, then explicitly cast to
FP32. The model's state, learned parameters and training computation use FP32.
No generator/grid/term-count gradient is claimed. The selected matrices must
pass the constructor's independent order/conservation checks, and the actual
RNN graph must pass CPU and CUDA state-carry and finite-difference checks.
Ordinary A/B gradients and point-kernel V4 gradients cannot replace these.

## Ten treatments

| Arm | Intervention |
| --- | --- |
| regenerative_dual | Base generator, real intervals, margin/call/first-hit features |
| smooth_dual | Ordinary smooth reflecting finite-state CTMC; its own value, prospective entry risk and state all use the same generator |
| margin_only | Base kernel; three fixed functions of the margin channel |
| call_only | Base kernel; three fixed functions of the constant-payoff value channel |
| risk_only | Base kernel; three fixed functions of the first-hit channel |
| endpoint | Base kernel and value; replace the risk feature with the unabsorbed endpoint probability |
| no_reset | Permanently absorbing boundary, explicit absorbing coefficient, no reinjection |
| no_refractory | True zero-delay reset, with a bounded infinite renewal series; no small-tick substitute |
| uniform_tick | Replace each propagation/lookahead duration by `.0625`; observations still include the same actual intervals |
| conditional_boundary | Log boundary `-.025` or `+.025` selected by the first known interval, then fixed for the entire episode |

The condition for the last arm is `first_dt_index >= 2`. It uses no label or
future observation. The absolute log reset and initial log state stay `.25`
and `.35`, so relative reset/initial distances are `.275/.375` or `.225/.325`.
This is a legal fixed-episode contextual rule, not a QVI solution or a learned
optimal boundary. All arms receive identical observations and two available
cohort routes; the noncontextual tables are identical across those routes.

All treatments have 81 probability coefficients, but their declared bases
follow their processes. No-reset uses 79 active cells, a tail and an absorbing
coefficient; zero-delay uses 80 active cells and a tail. The smooth control
uses 81 finite locations and reflecting endpoints. Its last location is not
an exact infinite-tail density. This matches coefficient capacity, not basis
resolution or continuum discretization error. The bundle records each basis,
construction discrepancies, state-tail omissions and FP32 conservation error.
The zero-delay series is kept as a subprobability; omitted mass is not hidden
by row normalization. Relative accuracy of underflowed tails remains unknown.

## Numerical resolution selection before task training

The numerical-only probe registered three candidate active/phase grids,
`16/8`, `64/16`, and `128/32`, before reading any formal task data or running
any formal fit. Both 64-step physical schedules end at `T=4`: alternating
`.025,.05,.075,.1` repeated 16 times and uniform `.0625` repeated 64 times.
For each grid both FP32 and FP64 must have common-bin state L1 error at most
`.02` and cumulative first-passage count relative error at most `.03` against
a direct renewal reference. Selection takes the smallest passing grid.

The `16/8` grid failed (maximum state L1 `.20530385943`, count relative error
`.17668811113`). The `64/16` grid passed (maximum `.01584776136` and
`.01186598755`); `128/32` also passed (`.004218357676` and `.002984456786`).
Therefore all arms use 81 coefficients and 2,890 trainable parameters.
All 12 numerical rows, including the failed coarse grid, remain evidence.
These checks apply to the unconditioned base law and the recorded schedules.
They are not an arbitrary posterior, boundary-cohort, or global continuum
error guarantee. The original 160-fit, 400-update budget is unchanged.

## Identical learned architecture and actual state consumption

The observer is `Linear(3,32) -> Tanh -> Linear(32,81)`. A `Linear(6,1)` gate
uses three observed inputs and three mechanism features. A `Linear(81,1)`
readout predicts the task target. There are exactly 2,890 trainable scalars in
every arm. Runtime records also disclose observed nonzero-gradient counts;
the static parameter count must not be confused with every parameter being
equally used on every example.

The first step uses the declared initial-state transition; every later step
uses the previous posterior times the selected transition matrix. The full
measure therefore reaches the next observation. After physical propagation,
lookahead features are computed from that predicted measure for the currently
known interval. The call feature is the value with active reward `.4`, hit
reward 1 and active terminal reward `.2`, under the arm's own generator.
Margin and call are transformed by `z/(1+z)`; risk is a probability. The dual
features are those three channels. Each single-channel arm uses `[z,z^2,z^3]`
so that it retains the same learned parameter structure and all gate inputs
remain dynamic.

The likelihood is `exp(sigmoid(gate)*tanh(observer(observation)))`.
The posterior is predicted mass times this likelihood divided by its explicit
evidence. This is an observation update, not a repair of a bad transition:
the unconditional preconditioning conservation defect is independently
recorded and must stay below `5e-5`. All examples may have different interval
sequences; each example retains its fixed cohort/generator throughout.

## Data, independent repeats and complete training denominator

The two synthetic tasks are delayed recall and adding. They use the existing
task definitions: a marked first value must survive distractors, or two
marked values must be added. The third input is the real interval. Interval
indices are independently sampled per example and carry no target information.
The tasks test controlled memory behavior; they are not external datasets.

There are 2048 training, 512 validation and 1024 test examples per test episode
seed, each of length 64. The split seed is 20261107, with separate deterministic
task/split/episode-seed derivations. The exact generated byte hashes are
recorded. All arms and learning-rate trials share the same data, and the
same training seed uses the same minibatch order across those trials.

Independent training seeds are `1103,2207,3301,4409`. The learning rates are
`.001,.003`; every trial starts from its registered initialization and runs
exactly 400 updates of 64 examples. Each completed fit therefore submits
25,600 examples and 1,638,400 sequence positions. There are
`10 arms * 2 tasks * 4 seeds * 2 learning rates = 160` full training trials,
or 64,000 updates and 262,144,000 submitted sequence positions. These are
four independent seed repeats per arm/task after validation selection, not
160 independent replications of one treatment.

Test episode seeds `4703,5801` are separate from training seeds and are
aggregated within one fitted model. They do not increase the number of
independent training repeats. A seed/task block contains all 20 arm/LR fits.
The arm order is a prospective deterministic permutation with schedule seed
78137; both rates for one arm are consecutive. The complete ordered roster
and its hash belong to the frozen plan.

Each fit has a 480-second hard wall deadline and no automatic retry. Finite
runtime blocks cover 20 previously unstarted fits. Existing completed,
failed, unknown or claimed attempts are never overwritten or silently replayed.
The 20-fit group is a statistical selection group, not a cloud-job boundary.
A provider job may run one fit, with bootstrap/export headroom inside its
600-second limit; selection and evaluation use separate jobs after every
training terminal in the group is present. No test can run before that lock.
Block segmentation does not reduce any fit budget or change the 160-fit
denominator. A unique runtime owner and stable block identities are required;
local file claims do not establish global mutual exclusion against unrelated
noncooperating launchers.

## Selection, comparisons and interpretation

After all training/validation terminals in one task/seed block, lock each
arm's learning rate using validation MSE. Also lock the strongest registered
other arm using validation only, with deterministic arm/rate tie breaking.
Write this selection before any test evaluation in that block. Failed or
incomplete LR pairs remain in the denominator. Other complete pairs may be
evaluated, but missing pairs invalidate complete-family and strongest-full-set
claims. No choice may be revised after test inspection.

The primary contrasts are `smooth_loss - full_loss` and
`strongest_registered_other_loss - full_loss`. Seven additional removals
(margin/call/risk-only, endpoint, no reset, no refractory, uniform tick) use
`ablation_loss - full_loss`. The contextual boundary comparison is
`fixed_loss - contextual_loss`. There are 10 contrasts per task, 20 total.
Report every sign and failure. The minimum useful difference for this
synthetic pilot is an absolute MSE reduction of `.01`; it is not a deployment
utility threshold. Four training seeds, with episode seeds first averaged
within fit, are the units for paired uncertainty estimates. Report 95% paired
Student-t intervals and Holm correction over the 20 planned contrasts as
exploratory summaries. The four-repeat design is not a prospective power
certificate or confirmatory study.

Retention margin and old-capability retention are **unmeasured**, represented
by null. The strongest registered other arm is not asserted to be the world's
strongest deployable model. Even favorable pilot estimates cannot authorize
expansion without the separate external-task, retention, full-budget and
complete-cost gates.

## Cost and artifacts

Save immutable start and terminal records, exact source/plan/bundle/data
identities, all failure reasons, checkpoints and selection locks. Track both
learning rates and all unsuccessful trials. Separate training, validation,
selection and test/performance work; nested wall intervals must not be summed
twice. Record encoder/core/readout parameters and storage, live probability
state, constant tables, peak GPU/host memory, and actual software/hardware.

Deployment timing uses batch 1, 10 warmups and 100 measured repetitions with
GPU synchronization, reporting p50/p95/p99. Throughput uses batch 64 and 20
measured repetitions. These are recorded sample quantiles, not tail-latency
guarantees. Actual GPU device energy counters may be reported for their
intervals, while full-machine physical energy, provider charges and unmetered
preparation remain null. Do not replace those fields with TDP or arithmetic
operation estimates. New study costs, the original campaign and NDU costs
remain separate ledgers.

## Frozen statistical decision details

The numerical implementation in `mechanism_analysis.py` fixes the inferential
unit as the four independent training seeds. Each selected model first
aggregates squared-error sums and episode counts across both evaluation seeds.
For every contrast, positive effects favor the named mechanism (the boundary
contrast is fixed minus conditional MSE). The null is mean MSE reduction at
most `.01`; use a one-sided paired Student-t test against that useful-difference
threshold. Also report pointwise two-sided 95% t intervals. Holm adjustment
uses the entire fixed 20-contrast family; an incomplete four-seed comparison
receives p=1 for multiplicity and cannot pass. A reported exploratory effect
gate requires all four seeds, adjusted p<=.05 and lower pointwise CI>.01.
These pointwise intervals are not simultaneous coverage claims, and a passing
synthetic effect gate does not remove the external retention and full-cost
HOLD. No missing training outcome is imputed as a successful model.

## Provider and runtime identity

Before any formal fit, the actual S81 graph must complete a 400-update,
batch-64, sequence-64 random non-task timing probe plus its validation and
checkpoint in less than 450 seconds. This predeclared feasibility gate leaves
at least 30 seconds inside the 480-second fit deadline and 120 seconds between
that deadline and the provider's 600-second request bound. It is an empirical
feasibility check, not a guarantee that every fit will finish. A failure stays
visible and prevents freezing this execution configuration.

The plan binds the qualified Python, NumPy, Torch, CUDA build, device type,
thread count, deterministic-algorithm setting, GPU model/memory/compute
capability, and the bundle-construction software versions. Each worker checks
these fields before reading task data. The explicit GPU policy permits a new
lease of the same qualified model and software; it records the actual UUID.
A different backend software stack requires its own qualifications and a new
prospective plan identity. An unknown previous fit is never replayed as a new
success under the same fit ID.

A zero-variance sample across the four fitted models has no usable Student-t
standard-error estimate. Preserve its observed mean and mark its inferential
result unavailable; it cannot obtain p=0 or pass the effect gate. Confidence
intervals describe training randomness conditional on these frozen task data
and this validation-selection procedure. They do not cover uncertainty across
new tasks or newly sampled datasets. The strongest registered comparator is
that per-seed selection procedure and may choose different arms across seeds.

# Task-value factorial experiment

This is a bounded research experiment on top of commit
`8fc9bfcf5fc21a95facf36790e2d7f1463c7d04b`. It does not activate or replace
the native Hepta neuron. The inherited frozen content model and its four
dependencies are byte-pinned in `UPSTREAM_FILES.json`.

## Question and fixed objective

Two consecutive jobs require recovering a marked symbol from actual packet
files using the inherited 6,217-parameter FullHX content decoder. READ opens a
file and runs that model. SKIP advances without accessing the packet. FIRE
submits the current answer, consumes a two-tick interval and starts the next
job with reset belief. STOP terminates. The full public state contains both
jobs' reliability and price schedules, irregular durations, deadline, budget,
current posterior, calibrated observation law and resource weights.

The task objective is correct answers minus incorrect answers, minus priced
queries and declared task elapsed time. Measured CPU and wall time are separate
resource measurements. CPU-adjusted admission also charges training amortization;
hardware time is not silently substituted for the declared task clock. The
Bellman teacher does not directly optimize measured hardware CPU.

The execution owner and finite Bellman teacher share feasibility, observation
updates, prices, durations, reset and continuation. Decoder confusion is estimated
only on TRAIN. Bellman recursion is exact for this fitted finite law, not for the
unknown actual decoder distribution. Task packets are synthetic; file operations
and model inference are real. This is not a natural-document reasoning benchmark.

## Factorial comparison

| Cell | Per-job value teacher | Continuing task-value teacher |
| --- | --- | --- |
| Two ordinary elapsed-time gates | A: ordinary_myopic | B: ordinary_value |
| Finite regenerative analytic CTMC | C: analytic_myopic | D: analytic_value |

Each family has six physical parameters and a five-parameter observation readout.
The analytic cell has three active states and two Erlang refractory states; its
flow is a matrix exponential and its first-event probability uses the killed
generator of that same process. Ordinary cells have two recurrent gate states.
Both families replay the complete causal history for every fitting candidate.
The driver for an elapsed interval is frozen before the action and observation.

Cell parameters are fit by TRAIN next-observation likelihood, then frozen. All
four critics have the same 67-input, 24-hidden-unit, four-output architecture,
initial weights, minibatches, update count and masked Q-regression objective.
Only the teacher's post-FIRE continuation differs between columns. Validation
selects among four predeclared checkpoints; all candidate weights are retained.
This is staged fitting, not a claim of end-to-end differentiable event training.

Both controllers receive the full task state plus causal cell-derived features.
Consequently this experiment measures finite-budget approximation and inductive
bias. It does not prove an intrinsic neural stopping problem was solved. The
myopic baseline is a research baseline, not the existing production controller,
and the continuing critic is not a complete production NDU implementation.

## Additional references and scope

Exact fitted-law full and myopic DP policies expose approximation gaps. Fixed
and TRAIN-selected posterior-confidence thresholds are **task boundaries**;
they cannot establish an independent benefit from the cell's intrinsic free
boundary. That further attribution remains a separate experiment.

`analytic_value_sampled` deploys the unchanged distribution-trained critic on
a Gillespie path of the same CTMC. Its latent state, refractory transitions,
multiple fires and task resets are recorded. This is a direct migration stress
test, not an assertion that nonlinear policy decisions commute with expectation.
Latent cell fires and task FIRE submissions are different events.

The numerical qualification includes independent uniformization and Gillespie
comparisons, moving geometry, resets, irregular intervals, whole-history
derivatives, long streams, and coupled two-cell dynamics. Exact finite-state
propagation is not a continuous-diffusion convergence proof. The factorized
approximation reports its joint-state and count errors explicitly. The two-cell
tensor state space still grows exponentially; these checks do not solve scaling.

## Frozen experiment and evidence

`PROTOCOL.json` declares all seeds, budgets, shifts, checkpoints, contrasts and
admission thresholds. `run prepare` creates only TRAIN/development data. The
selected models, all training candidates, source manifest and protocol are
published in an immutable Git commit before `run confirm` creates heldout bytes.
`FREEZE.json` binds those files. `CONFIRMATION.json` records the publication commit.

Five independently fitted seeds are the inference units. Each IID and OOD cohort
has 64 paired sessions per seed, with identical packet files available to each
policy and randomized execution order. Five main contrasts use Bonferroni-adjusted
Student t intervals separately within each split. The sampled-policy diagnostic
is exploratory and is not folded into that family of tests.

Artifacts are gzip JSON and tar archives. All actual packet bytes, public state,
terminal labels, executed action receipts, costs, selected models and discarded
checkpoints are preserved. The archives are verified before generated working
copies are retired. A partial gzip JSON-lines journal preserves completed rows
if a later policy raises. Per-rollout errors remain failures, not excluded data.
Uncaught failures stop the campaign; they do not trigger replacement seeds.

Standalone training timers charge common setup once plus the relevant cell fit
and critic. Physical campaign totals use enclosing timers, not sums of four
overlapping standalone costs. Teacher/content/controller subtimers are nested.
Auxiliary threshold selection, generation, loading and evidence serialization
are also retained. CPU time and event counts are not energy measurements.

## Reproduce

Use Python 3.12, NumPy 2.3.5 and SciPy 1.17.0. From the repository root:

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m unittest tools.hcsn.task_value_factorial_20261030.task_tests \
  tools.hcsn.task_value_factorial_20261030.dataset_tests \
  tools.hcsn.task_value_factorial_20261030.controller_tests \
  tools.hcsn.task_value_factorial_20261030.execution_tests \
  tools.hcsn.task_value_factorial_20261030.test_propagation
python -m tools.hcsn.task_value_factorial_20261030.run prepare --out NEW_RUN
# Publish and independently verify NEW_RUN plus sources at an immutable commit.
python -m tools.hcsn.task_value_factorial_20261030.run confirm \
  --out NEW_RUN --freeze-commit VERIFIED_COMMIT_SHA
python -m tools.hcsn.task_value_factorial_20261030.run analyze --out NEW_RUN
```

A typed commit argument is not proof of publication. Repository API verification
and chronological provenance must accompany the local manifest. Re-running uses
a fresh output directory; evidence writes refuse to overwrite earlier attempts.

## Admission

The predeclared gate requires positive D−B lower bounds on both IID and OOD,
quality noninferiority, positive CPU-adjusted gain at the declared price and
amortization, complete failure-free evidence, and separately qualified native
integration. Native integration is false in this experiment. Even a positive
research result cannot by itself activate the production neuron.

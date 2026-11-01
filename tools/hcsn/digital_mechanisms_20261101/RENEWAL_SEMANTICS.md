# Reset-aware forecast and continuous-time finite renewal

This subsystem supplies a **new 17-state continuous-time Markov chain**. It does
not change or reinterpret the frozen `digital_read_before_20261031` experiment.
It is not an exact continuous Brownian or production neuron implementation.

## One process for all queries

There are 15 interior voltage nodes, spacing `h = 2B/16`, and lower/upper
refractory states. Active downward/upward rates are respectively
`sigma²/(2h²) + max(-mu,0)/h` and `sigma²/(2h²) + max(mu,0)/h`. A boundary jump
enters the corresponding refractory state and records a signed event. Recovery
has exponential rate `recovery_rate`, with destination sampled from the folded
Gaussian reset distribution (normalized standard deviation .12). Parameters
have the same physical meaning as `FiniteCell.physical()`; grid placement and
generator are distinct from its historical image-bin approximation.

The single generator Q gives reset-aware future distributions `p exp(t Q)`,
first-hit laws with the refractory states made absorbing, and repeated event
counts through a Markov reward block matrix. Forecast categories are active
below/equal threshold, active above threshold, lower refractory, upper refractory.
They partition probability one. Refractory occupancy is not first-event
probability, and expected event count is not probability of any event.

Every forecast must state the future input. The current API uses a constant
generator on each specified interval. The caller chooses whether this means
sustained evidence drive, zero evidence drive after a one-time injection, or a
different external schedule. The CTMC itself does not decide to reuse evidence.
These functions do not yet supply a trained reset-aware head or establish
cross-horizon task calibration of a learned model.

## Events and recovery checkpoints

Both Python and standalone Rust sample exact Gillespie paths **for this finite
CTMC**. Event times are actual within-interval jump times. Evolution continues
after an event, through recovery and any further events in the remaining time.
Sampling is not restricted to one event per external interval.

Rust checkpoints contain state, logical clock, RNG state, next absolute jump
time and destination, event counters, jump counter, and model identity. Keeping
the pending jump preserves the same path when an unchanged interval is split.
The executable resumes checkpoints in a fresh process; initial refractory
states are exercised too. An explicit context switch validates the old model
and checkpoint, then discards the old pending hazard only when Q changes.
Exponential memorylessness justifies that new draw; it does not promise path
identity across different input schedules.

The FNV64 checksum detects accidental corruption for this research executable;
it is not cryptographic authentication or rollback protection. Files are
create-only and synced, but event/clock persistence is not a production
transaction. The complete NeuronRuntime/ACK owner has not been integrated.

## Executed verification entry point

```
python3.12 -m tools.hcsn.digital_mechanisms_20261101.renewal_checks --rustc /path/to/rustc
```

The check returns actual results rather than a static pass manifest. It compares
the semigroup and four-category mass, independent density and reward integrals,
a finite-difference/Frechet derivative, and a separate NumPy Gillespie sampler
against matrix-exponential forecasts at four horizons. Simultaneous Monte Carlo
probability coverage uses a Hoeffding union bound across the 76 checked
probabilities; event-count standard errors are descriptive. Twelve native
whole-versus-split paths use separate processes and byte-identical final
checkpoints. Explicit input changes and corrupt/mismatched checkpoints are
checked. Numerical qualification is for these declared cases, not all parameters.

Spatial discretization error, Brownian convergence, learned reset/refractory
parameters, learned-model calibration, energy, complete deployment cost, and
production-owner qualification remain separate obligations.

## Retained free-endpoint comparison on the same paths

`forecast_comparison.py` uses five horizons (.25, .75, 1.5, 3, 6), three thresholds
(-.5B, 0, .5B), a declared held-constant input, and 12,000 independently sampled
CTMC paths per horizon. Three thresholds define four active voltage bins; the
two refractory states give **six exhaustive outcome categories**. The original
free-endpoint formula assigns Gaussian mass to the four voltage bins and zero
mass to refractory states. Both forecasts are scored on the same outcomes.

```
python3.12 -m tools.hcsn.digital_mechanisms_20261101.forecast_comparison --samples 12000
```

The result records category probabilities, calibration discrepancies, paired
multiclass Brier differences and standard errors, refractory occupancy, first
event probabilities, and repeated event counts. A simultaneous Hoeffding bound
covers 30 category probabilities with alpha .001; a separate bound covers five
paired Brier means with alpha .001. Their combined failure probability is at
most .002 under independent path sampling. Count standard errors are descriptive.
Under the declared CTMC law, the expected excess Brier of another forecast is
its squared Euclidean distance from the CTMC category probabilities; the code
checks this identity against the sampled paired outcomes.

This is an explicit **misspecified-law contrast**. Differences include the
finite voltage grid, inclusive-threshold atoms, drift approximation, and omitted
reset/refractory dynamics. They do not isolate a causal reset effect, prove
Brownian spatial convergence, validate a learned forecast, or establish a neural
model advantage. A generic CTMC/HMM with the same generator has identical
forecasts. The separate native event/checkpoint executable retains its standalone
research scope and has no production-owner or ACK integration.

## Prospective frozen-model native execution

`native_confirmation.py` is a new experiment registered before formal fits. It
requires the complete published model freeze, verifies current source/protocol
identity, and loads each registered fit's `first_passage_bank__structured_on`
artifact through `MechanismPolicy.from_export`. It transfers only the fitted
physical parameters into the separately declared CTMC. The neural task continues
to use its own interval law; this experiment does not establish native execution
of that neural task or replace the task's confirmation results.

Eight predefined cases per fit use new deterministic seeds, active/refractory
initial states, held-constant declared inputs, and external cuts. Each case runs
three native processes: uninterrupted, prefix, and checkpoint-resumed suffix.
Acceptance requires identical final checkpoint bytes, complete event traces, and
final stdout. Raw generator files, logs, checkpoints, event times, process IDs,
binary/model/source hashes and every child CPU cost are retained. At 16 fits the
experiment has 128 trajectory cases and 384 actual native process executions.
No TRAIN/validation/IID/OOD cohort is opened or generated by this runner.

The historical numerical/restart result tested native source `d37e251...`.
Repository formatting split only its `std::fs` import; the successor source is
`64df3f...`. The old result remains bound to its original bytes and is not
relabeled as a rerun. This prospective fitted-model experiment compiles its own
current frozen source and records separate evidence. Its scope remains a
standalone CTMC runtime, without production ACK-owner or Brownian-convergence
qualification.

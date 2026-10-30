# Backward first-event vector profile

This independent numerical profile replaces only the first-event risk time
propagation used by the frozen risk feature study. It leaves that study's
sources, previous execution, and results unchanged. It is an implementation
comparison before a separately registered fresh fixed-update cohort; it is
not a new neuronal mechanism or a predictive-quality claim.

## Probability identity

Write the killed **column** generator as `Q_nohit`, the no-event boundary
remap in row convention as `R_nohit`, the fixed uniformization rate as
`lambda`, and the duration as `dt`. The only feature needed by a neuron is

```
survival_vector = R_nohit exp(Q_nohit.T * dt) ones
risk_vector = ones - survival_vector
first_event_probability = incoming_probability dot risk_vector.
```

The killed generator removes every incoming reset contribution of a newly
marked event, including an event that resets to its own finite-volume cell.
Pre-existing refractory phases still progress and release according to the
reset interpolation weights. The boundary remap removes mass crossed by the
new boundary, so a boundary-jump event also exists when the elapsed duration
is zero. No killed probability or Poisson weight is normalized or clipped.

For `c` independently chosen chunks, `h = dt / c`, the frozen matrix oracle
uses the unnormalized finite Poisson polynomial

```
P = I + Q_nohit.T / lambda
T_h = sum(j=0..K) exp(-lambda*h) * (lambda*h)^j / j! * P^j.
```

This profile starts with `u = ones` and applies that same polynomial to `u`
exactly `c` times. Each application of `P` uses active-cell neighbors and the
refractory release weighted sum. For `c <= 16`, this avoids constructing the
dense time-transition matrix and its backward graph. For larger counts the
profile selects only those tokens and calls the unchanged matrix oracle.
The fixed rate, terms, token-local chunk rule, duration resource cap, and
Poisson truncation error budget are unchanged. The physical overlap remap is
also reused unchanged. Arithmetic order differs, so bitwise agreement is
not promised for general floating-point inputs.

The risk **time propagation** is linear in the number of states for each
polynomial term and direct chunk. The overlap remap and the separate
regenerative transition still contain quadratic operations. This profile
therefore does not make the whole network linear in the number of physical
states, and it does not establish a complexity advantage over Transformers.

## Model scope

`MemoryRiskContentCell` inherits all initialization and physical/content
parameter preparation. Two copied methods change only the risk operator,
the probability expectation call, and the actual survival-vector key.
`MemoryRiskClassifier` keeps the exact constructor order and random seeds,
uses the new cell class, and adds an explicit numerical-profile identifier
to its configuration. No survival-transition matrix is fabricated. The
original matrix implementation remains an oracle and a large-duration
fallback.

`COPY_MANIFEST.json`, the executable AST check, and
`INDEPENDENT_REVIEW.json` record this scope. The latter is a read-only peer
review; training results are verified separately.

## Preflight evidence and limits

`results/kernel_preflight001` compares the profile with the frozen matrix
oracle and independent dense-generator calculations. Cases include zero
duration, changing boundaries, both zero and two refractory stages,
float32/float64 inputs, chunk boundaries, long durations, marked self-reset,
seven physical/duration derivatives, and independence from future or
unrelated tokens.

`train_equivalence.py` registers and executes a separate train-only
comparison. All seven model arms and both actual train datasets use the
same seed and three B32 Adam updates per implementation in isolated
processes. It retains all input arrays, initial states, logits, losses,
named gradients before/after clipping, full parameter/buffer states after
each update, and optimizer tensor states. Acceptance tolerances are written
before execution. No validation, test, or OOD split is loaded.

Complete `wait4` CPU and peak RSS are measured for each isolated process;
nested update CPU is also reported. For the eight risk-enabled comparisons,
the combined core-update CPU was 48.464 seconds with the matrix oracle and
26.905 seconds with the vector profile; these are nested update costs, not
complete-worker costs. Full wait4 CPU remains in the receipts. Peak RSS was
23.9%–28.9% lower in those pairs. Every one of the 7,516 tensor comparisons
across all 14 pairs was bitwise equal, including all three Adam updates.
This finite observation is not a floating-point identity proof for the
entire 128-update optimization trajectory. Memory and time do not include an
energy measurement. Three updates on one seed can demonstrate a numerical
and resource preflight, but cannot establish identical long optimization
trajectories or eliminate all possible later memory peaks.

`evaluation_memory.py` uses only `train_x` and `train_dt`, the existing
three-update train-only parameter states, and repeated training inputs. It
checks complete label-free B128/T32 validation-shaped and B128/T64
OOD-shaped forward batches. It does not read any label or heldout array.
`resource_accounting.py` tests the actual host-PID/namespace-PID mapping
with a real child that touches a 64 MiB allocation, plus a missing-child
case that must receive zero anonymous-memory credit. The older helper's
direct `/proc/Popen.pid` lookup is invalid under this namespace arrangement.
Shared concurrent allocations also contributed to the memory risk; the
mapping defect is not established as the sole cause of the previous OOM.

## Previous failure and any fresh cohort

The original `risk128_4w` cohort aborted after one worker was killed while
the shared cgroup recorded an OOM event. Its two successful jobs, one failed
job, raw logs, and complete wait4 costs remain preserved. None of those jobs
may fill a cell in a fresh memory-profile cohort. Any fresh cohort must
retain the full 112-job seed/order/data/optimizer/statistical design and be
separately registered and publicly sealed before execution. Its joint
analysis must disclose that the equal-CPU family used the original matrix
implementation and the fresh equal-update family used this profile.

Resource scheduling must budget measured worker peaks and retain at least
2 GiB of shared headroom in addition to a 1.25 GiB budget for each active or
new worker. Maximum concurrency is four, with an initial two-worker ceiling
and later increases authorized separately. Verified anonymous memory already
charged to the cgroup can reduce only that same worker's future reservation.
An unknown or ambiguous PID receives zero credit and keeps the full budget.
Reducing
concurrency is permitted; changing model/data/update/cap/heldout-selection
semantics is not. A failure stops new dispatches, drains current workers,
preserves all costs, and does not trigger automatic replacement runs.

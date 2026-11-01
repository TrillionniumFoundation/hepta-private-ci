# R12 continuous successor and numerical training contract

This additive study imports the actual `renewal.py` from the fixed repository
base `631d33ba7ee815ee48c017269033e94cb2bc107c`. It also preserves two byte-exact
R11 full He–Xiong source files from
`b426b83eb5fd27487c8dba3f90fe9af0dff615e1`. `UPSTREAM_VERIFIED.json` records each
commit, original path, Git blob identity, SHA256 and byte count. Neither original
research implementation nor its historical evidence is modified.

## The new comparison

The renewal process has distance `x>0`, constant drift `mu`, noise `sigma>0`, an
absorbing boundary at zero, a fixed positive reset distance and deterministic
positive refractory duration. A hit is counted at its actual time. The cell
then remains refractory and can restart and fire again inside the same observed
interval. A reset at the end of an interval is a different process.

`dynamics.py` reconstructs the entire physical-state law as an active density
plus a refractory-age density. The audit integrates active moments and spatial
bins, checks killed-kernel composition, and retains every completed-reset branch.
`pde.py` independently evolves a positive finite-difference forward equation,
records the absorbing flux and reinjects that flux after the actual refractory
delay. Three grids test convergence of count, live-state distribution and
refractory occupancy. Every final grid position and probability is retained.

The upper wall at distance 8 is a numerical truncation, not a reflecting neural
boundary. Its escaped mass is recorded and must pass the registered gate. The
calculation never renormalizes probabilities or clips negative transition rates.
This new finite-difference solver is a reference implementation, not a native
Hepta cell and not a replacement for the frozen R11 three-bin CTMC.

## Moving boundaries and gradients

For a deterministic boundary `b(t)`, distance `Y=X-b(t)` has drift
`mu-b'(t)`. A linear boundary is exactly the constant-drift first-passage model
with `mu-speed`. A quadratic boundary is evaluated with its time-varying drift
and three-grid refinement. Substituting its average speed into a stationary
formula is separately recorded as a heuristic, not accepted as exact.

Analytic derivatives cover initial distance, drift, noise, horizon, reset distance
and refractory duration. They are compared to independent 70-digit literal
formula derivatives. `GRADIENT_PROTOCOL.json` adds independent forward-PDE
parameter secants at two step sizes and two spatial grids. These are numerical
tests of the continuum derivatives; a finite interpolation knot is not described
as having an ordinary derivative merely because central secants can be computed.

## Full financial kernel and a bounded API

The original R11 core already evaluates financial Eq. 8/9/12/A5/A7 and its 5×10
Jacobian. It is rechecked at declared states against the original independent
80-digit literal reference. Pure FP32 remains an explicitly unqualified audit
mode. The bounded `safe_hx.evaluate` interface accepts FP64 or an FP32 interface
with an FP64 kernel, inherits the complete R11 parameter box without narrowing
it to selected successful parameters, and requires continuation distance in
`[0,2]`. It refuses unrepresentable/nonfinite results and out-of-scope states.

The historical evaluator is deliberately preserved: a finite input can overflow
its equity and Jacobian. The audit retains this exact failure and checks that
the new bounded interface refuses it. Finite outputs and selected fixtures do
not establish a uniform accuracy theorem throughout the admitted box.

## Protocol and immutable attempts

`PROTOCOL.json` was written before development execution. Its SHA256 is
`20c1504b273197166f72fe85e69260c0b4f1249a1bb5ebc42b7a2b8d4379cba9`.
The gradient supplement was written before any PDE-gradient run. No original
threshold was loosened. Each attempt creates a new directory, a source hash
freeze, exact source snapshots, JSONL checks and raw final-state files.

`development_01` preserves a NumPy-boolean serialization failure, its traceback
and executed source. Later attempts serialize explicit boolean checks before
adding a record. The failed attempt is not relabeled as a complete scientific
run. Historical nonfinite-HX and pure-FP32 failures remain separate negative
controls in every completed attempt, with their actual `passed=false` records.

Run from the repository root with NumPy, SciPy and mpmath:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B experiments/hcsn_validation_r12_20261031/numerics/audit.py \
  --out /tmp/hcsn-r12-numerics-new-attempt --stage formal \
  --frozen-commit ACTUAL_PRE_EXECUTION_SOURCE_COMMIT
```

Use the dependency path supplied by the execution environment when required.
Internal timing includes all audit phases but excludes imports; a parent process
receipt must be used for complete process CPU. The audit has no subprocesses.

## Limits retained

This is selected-case numerical verification, not interval-certified global
accuracy, a random/state-dependent moving boundary, a repeated-reset derivation
of the financial stopping model, native CTMC continuum equivalence, or evidence
of a network quality/compute/energy advantage. The full-successor integral and
PDE checks here require positive refractory time; inherited zero-refractory
renewal results are not silently expanded into a new complete-state claim.

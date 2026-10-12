# Riccati-Newton: faster correction of the same registered FBSDE

Continues #1550 at `ef312dd2dada37260b7bbeec39d2c675cacdb1eb`. This is a
solver experiment, not a new evaluator, native owner, risk certificate, model
selection, or semantic reasoning benchmark. Historical files and controls remain.

## Exact scope and derivation

The inherited model is dX=aY dt+sigma dW, dY=(lam Y-beta tanh X)dt+Z dW,
Y_T=tanh(X_T), with fixed binary-increment discretization and h=T/N.
Use the same global-map error bound r/(1-q), q=a*T*(1+beta*T), and the same
q<.98 admission, initial domain, finite input bounds and 1e-10 study tolerance.
Grid refinement cannot waive this condition. These are exact-arithmetic bounds;
ordinary double residuals do not enclose rounding or continuous-time error.

For each current tree value let

    R_i=(1+lam*h)Y_i-(Y_left+Y_right)/2-beta*h*tanh(X_i).

The Newton correction has deltaY_i=P_i*deltaX_i+r_i. At leaves,
P=sech(X)^2 and r=0, because terminal Y is eliminated by its exact tanh boundary.
With barP and barr denoting the two child averages, eliminate backward:

    D_i = 1+lam*h-a*h*barP
    P_i = (barP+beta*h*sech(X_i)^2)/D_i
    r_i = (barr-R_i)/D_i.

Recover deltaX_root=0 and deltaX_child=deltaX_i+a*h*deltaY_i forward. This solves
the affine Newton system by scalar tree Schur/Riccati elimination without a dense
Jacobian inverse. P and r are NODE-specific, not one deterministic Riccati ODE
for the nonlinear stochastic problem. Each sweep is linear in the explicit node
count, which STILL grows exponentially with depth in this scenario representation.
The paper context is Gobet and Grangereau (2022), *Newton Method for Stochastic
Control Problems*, DOI 10.1137/21M1408567. Its theorem is not claimed for this
implementation: the returned answer is checked against our inherited equation.

Armijo backtracking uses the original global error bound, not a changed terminal
condition, small update norm, or a neural self-score. A small/invalid pivot,
nonfinite iterate, exhausted iteration/line-search budget or incompatible initial
inventory rejects. No hidden fallback returns an uncertified candidate.

## A linear shortcut is a different problem unless used only as an initial guess

If BOTH tanh terms are replaced by identity, the exact discrete linear law has
P_N=1 and P_k=(P_{k+1}+beta*h)/(1+lam*h-a*h*P_{k+1}). Compile these N+1 coefficients
once and reuse across initial states ONLY with the same bound target/profile.
Rehashing edited coefficients is insufficient: recurrence is also verified.
This field does not solve the original nonlinear problem. The study records its
original nonlinear residual explicitly. The linear-seeded Newton arm must correct
the original equation and satisfy the same final tolerance as every other arm.

## Same-problem work measurement and independent checks

Four controls: original cold Picard, cold Riccati-Newton, linear-seeded Newton,
and original Picard seeded by an interpolated numerical continuation table.
Two a coefficients (.55,.75), grids (5,8,10) and four initial states produce 24
cases. Seven deterministically randomized interleaved executions per arm produce
672 timed solves. They are repeats of deterministic problems, not 672 independent
semantic observations. Every timed output hash must match its saved solution.

All initial-guess validation, solve work and final original residual checks are
inside each call's CPU/wall measurement. The linear coefficients and numerical
tables are prepared once per registered coefficient/grid combination; each cost
is separately retained and charged only to these actual calls. No imagined future
volume amortizes it. The shared preparation, independent reference, hashing and
reporting lie inside a broader CPU envelope. Per-method component sums are NOT
full deployment lifecycle, native request latency or energy measurements. No
speed threshold makes tests flaky or encourages deleting a slow control.

At the smallest grid, compare with the inherited independently implemented dense
Newton oracle. Unit checks also compare the new affine direction with that dense
Jacobian and finite differences. A separate saved-file auditor imports no solver;
it reconstructs ancestral states and the original backward map, and recomputes
case completeness, paired repetitions, randomized order, raw CPU samples, medians,
preparation attribution and total work. Rehashed bad solutions and fake speed
ratios reject. Hash consistency does not authenticate physical execution.

The same run includes a finite XOR complementary-evidence positive control:
with each read costing .1, one-step reasoning abstains (value 0), while two-step
reasoning agrees with exhaustive policies (value about .79992 under the original
smoothing). At .6 per read, both abstain. It demonstrates a functioning multi-step
mechanism when information is complementary, NOT semantic competence or superiority.

## Running and qualification boundary

```sh
PYTHONPATH=qualification/neuron-stem python -m unittest \
  test_fbsde_riccati test_fbsde_riccati_study -v
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile riccati_solver_v1 --output /new/riccati-study
```

The existing exact head/merge workflow executes the profile and retains original
solutions/timings, without replacing any acquisition/model/failure-diagnostic lane.
Local final qualification-subtree regressions: 310; inherited actual Torch tests:
52, no skips. This does not erase earlier timing failures or qualify new-head CI.
No new pretrained forward, open-ended decoder, shared production controller or
native Rust integration was executed here. Real observation-law calibration,
System2 candidate generation/verification, CPU-tail stability, actual no-change,
independent future outcomes and risk/retention gates remain separate. Keep Draft.

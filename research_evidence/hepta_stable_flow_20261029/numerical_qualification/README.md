# New stable-flow numerical qualification — 2026-10-29

This directory contains **new numerical experiments**. No previous trained
checkpoint or original source was recovered, and these experiments do not repair
or reproduce an unavailable checkpoint. The equations below were transcribed
from the recovered `Hepta_Complete_Research_Report.html`; the numerical code is a
new implementation with narrower, explicitly declared parameter bounds.

## Mathematical contract

The state is `(v,q,z)`, where `v=log(V)` and `q=log(K)`. Define

\[
\beta=\frac{\kappa}{1+\kappa},\qquad B=\beta K,\qquad
x=v-q-\log\beta.
\]

The second state is **not** the default boundary itself: `log(B)=q+log(beta)`.
The normalized Call is the equity-like residual `C/(K+C)` and the normalized Put
is `P/K`. The latter is not a calibrated default probability. The financial
analogy does not establish optimality of the learned boundary for a neural task.

For `x<=0`, `a=0` and `p=1-beta exp(x)`. For `x>0`,

\[
p=\frac{e^{-\kappa x}}{1+\kappa},\qquad
D=\kappa e^x+e^{-\kappa x},\qquad
a=\frac{D-(1+\kappa)}{D}.
\]

Both channels are C1 at zero, generally not C2. They are two deterministic
functions of one scalar margin. They should not be described as independent
information channels.

The ODE is

\[
\begin{aligned}
\tau_v\dot v&=-v+I_v,\\
\tau_q\dot q&=-q+q_*+g_C(a-a_*)+g_P(p-p_*)-(z-z_*)+I_b,\\
\tau_z\dot z&=-z+g_zp,\\
q_*&=-x_*-\log\beta,\qquad z_*=g_zp(x_*).
\end{aligned}
\]

Initial state is `(0,q*,z*)`. All dependencies of the initial state and reference
channels on learned parameters remain in the graph. The time constants influence
the ODE; the equilibrium coordinates themselves do not depend on a time
constant. The recovery time depends on the fast-boundary time through
`tau_z = tau_q+.25 + (32-tau_q-.25)*sigmoid(raw_tau_z_fraction)`.

Declared bounds are `kappa in [.25,4]`, `x* in [-.5,1.5]`, `tau_v,tau_q in
[.25,8]`, `tau_z in [tau_q+.25,32]`, and all three gains in `[0,4]`. Projected
currents are separate trainable linear maps followed by `3*tanh`.

The `analytic`, `matched_c1`, and `sigmoid` modes have identical parameter layouts.
Their operator-derived reference states can differ even with identical raw
parameter values. The matched control uses

\[
a_m=\frac{\kappa x_+^2}{2+\kappa x_+^2},\quad
p_m=\begin{cases}
1-\beta/(1-x),&x\le0,\\
1/[(1+\kappa)(1+\kappa x)],&x>0.
\end{cases}
\]

It preserves channel bounds, boundary values and first derivatives, and the
Call's right-hand second derivative. It changes global shape. The sigmoid
control is `(sigmoid(kappa*x),sigmoid(-kappa*x))` and does not preserve these
boundary values.

## Stable kernels and integration

For `|s|<=1`, production phi functions evaluate the degree-18 Taylor polynomial
in Horner form. Outside this region they use `expm1` quotients. Both inactive
branches receive finite safe inputs before `where`. Autograd differentiates the
same polynomial used in the forward computation.

\[
\phi_k(s)=\sum_{j=0}^{18}\frac{s^j}{(j+k)!},\qquad k\in\{1,2\}.
\]

The initially proposed radius `.25` was expanded to `1` before qualification
freeze: the actual Torch quotient backward at `s=.2500001` in float32 had
relative error `1.18368e-5`, exceeding the declared `1e-5` kernel gate. Degree 18
also retains sufficient accuracy at radius 1 in float64. The Call's separate
near-boundary branch still uses radius `.25` for both `x` and `kappa*x`.

The Call numerator near zero is evaluated without cancellation of linear terms:

\[
N=x^2[\kappa\phi_2(x)+\kappa^2\phi_2(-\kappa x)],\quad a=N/D.
\]

Far from the boundary it uses the algebraically equivalent scaled expression

\[
a=1-\frac{(1+\kappa)e^{-x}}{\kappa+e^{-(1+\kappa)x}},
\]

so all evaluated exponents are nonpositive. The stopped branch is exactly zero
for Call. No hidden clamp replaces its mathematical derivative.

The final CPU execution path skips the near Taylor calculation only when **no**
coordinate selects that branch. If there is a near coordinate, both phi2
arguments are stacked into one vectorized evaluation of the same polynomial.
Degree, radius, coefficients, boundary and feedback do not change. GPU execution
keeps the tensor branch to avoid a host synchronization at every substep.

ETD2 splits the diagonal linear decay from the nonlinear target. With
`s=-h/tau`, `w1=-s*phi1(s)`, and `w2=-s*phi2(s)`,

\[
y_p=e^sy+w_1T(y),\qquad
y_+=e^sy+(w_1-w_2)T(y)+w_2T(y_p).
\]

External drive is fixed during an external tick. Content memory is not updated
by these internal substeps. Each sample has its own
`n_i=max(1,ceil(dt_i/max_step))`, `h_i=dt_i/n_i`. Completed examples are masked
while other batch members continue. This avoids changing an example's discrete
map when another batch member has a larger `dt`. The integer schedule is
detached; derivatives of `dt` refer to the currently chosen discrete map.

`prepare_sequence(dt[B,T])` computes one forward pass's differentiable parameter
references and all ETD coefficient tensors in advance. `step_prepared` consumes
the appropriate tick. This object is held locally by the caller, never retained
on the module, and must be rebuilt after each optimizer update and for each new
backward graph. It retains the initial-state and parameter dependencies. It
does not change the individual meshes or update content during substeps.

For the continuous ODE and exact ETD2 arithmetic, the prescribed initial state
lies in an invariant rectangle `|v|<=3`, `|q-q*|<=15`, and `0<=z<=4`, hence
`-18.5<=x<=19.5`. Each target stays in that rectangle and the ETD2 coefficients
are nonnegative and sum to one. This is not a proof of floating-point exact
invariance, Jacobian contraction, stable equilibrium, or accurate integration.
At the boundary the fast self-feedback is `(-1+gP*beta)/tau_q`, which can be
positive. Bounded trajectories can still have poorly conditioned gradients.

## Artifacts and measured findings

`arithmetic_run001/` is a byte-preserving copy of the earlier independent
NumPy/Decimal arithmetic experiment. Its copy manifest states the new identity.
It demonstrates cancellation risks of candidate formulas and an exactly
solvable affine ODE. It is not evidence that the unavailable old code used those
formulas.

`torch_run001/` contains a protocol saved before evaluation, snapshots of the
exact source, 156 raw high-precision kernel comparisons, 60 flow comparisons,
initial parameter tensors, time/input tensors, state arrays, gradient arrays,
and artifact hashes. It uses untrained parameters and two fixed input probes.
Weights, inputs and times are created in float32 and promoted exactly for the
float64 precision comparison.

Maximum kernel relative errors, including actual Torch autograd derivatives:

| Kernel | float32 | float64 |
| --- | ---: | ---: |
| phi1 | 2.72002e-7 | 8.67362e-16 |
| phi2 | 1.07380e-6 | 1.07125e-15 |
| analytic Call/Put | 1.44962e-6 | 5.45597e-15 |

The gates were `1e-5` and `1e-11`; subnormal values have an explicitly declared
absolute floor of `16*dtype.tiny`. Tiny, normally representable boundary Call
values use relative error, so a spurious zero cannot pass by an absolute-only
tolerance. Exact boundary zeros are separately checked.

The maximum same-step float32 versus float64 gradient relative L2 difference was
`2.34643e-7` over these flow probes. This does not certify every trained state or
parameter configuration.

Discretization error remains separate. For the analytic strong-crossing probe,
relative to float64 `h=1/256`, the scaled state discrepancy at `h=.25`, `.125`,
and `.0625` is respectively `8.93064e-3`, `2.49169e-3`, and `5.67774e-4`.
Gradient relative discrepancies at `.25` and `.125` are `3.17799e-3` and
`8.54269e-4`. Eliminating floating cancellation does not make a coarse solver
accurate. These mesh curves are diagnostic; step qualification uses an
independently implemented DOP853 oracle.

### Independent continuous-time audit and step-size decision

`independent_run001/` preserves the failed first qualification. Its predeclared
candidates were `.25` and `.125`. The scaled state threshold was `1e-3`, and the
relative L2 threshold for four fixed parameter-direction derivatives was `1e-2`.
The auditor independently implemented physical-parameter transforms, channels,
initial state, projected inputs and RHS in NumPy; it did not call production
`rhs` as an allegedly independent oracle. DOP853 used `rtol=1e-11,
atol=1e-13`, checked against `3e-13,3e-15`. Central differences used `eps=1e-5`
and `5e-6`; oracle and finite-difference stability were gates of their own.

Neither first-round candidate passed every prescribed mode and probe. At
`.125`, the crossing-case scaled state errors were `1.19548e-3` for analytic
and `1.02925e-3` for matched_c1. Their direction-gradient errors passed, but
that did not override the failed state gate. No threshold was relaxed.

The separately declared numerical engineering continuation in
`independent_run002/` tested `.0625` and `.03125` with the same probes and gates,
without consulting task scores or changing the ODE. **The first passing step
was `.0625` (1/16).** At that selected step, over all prescribed modes/probes:

| Independent qualification metric | Maximum observed | Gate |
| --- | ---: | ---: |
| Scaled state error versus DOP853 | 3.07838e-4 | 1e-3 |
| Relative L2 error of four direction derivatives | 1.17374e-3 | 1e-2 |
| Same-step float32/float64 direction-gradient difference | 7.72654e-7 | Reported separately |
| Zero-time identity / batch-composition difference | 0 / 0 | Exact identity in tested cases |

The run002 receipt SHA-256 is
`8bdb7b9f9f111be3c0738570caf6a0714a0182b3b47cd7f95733f5d288aabe7c`.
The selected step belongs in the training protocol as an explicit field.

This certificate covers those initial parameters and prescribed probes.
Separate stiff and parameter-edge stress cases remained finite and inside the
tested state rectangle, but analytic and matched_c1 state errors reached about
`1.29%` and `2.37%`, respectively. Thus it is **not** a global accuracy guarantee
over the parameter domain. A trained checkpoint needs its own fixed-weight
precision and mesh checks. The four directional derivatives also do not certify
the entire continuous-time parameter Jacobian.

`independent_run003_prepared/` rechecks DOP853 qualification after the sequence
preparation optimization. Prepared and original step paths produce identical
trajectories; the largest float64 relative discrepancy of four direction
derivatives is about `8.0e-16`. Its receipt SHA-256 is
`7a2e7f9b1706d27a4ae41ef9908b9671030c35f7f9d1cf94ccc5449b15f6bdcc`.

`execution_equivalence_run001/` preserves previous and current kernel source,
the protocol, and full value/gradient arrays for the later CPU execution
optimization. Cases include all-far, all-stopped, mixed near/far coordinates,
one shared scalar kappa and per-head kappa. All ten case/dtype combinations have
bitwise-equal values. The largest full `(x,kappa)` gradient relative difference
is `1.10637e-7` in float32 and zero in float64. Small differences from a shared
kappa reflect summation order. `compare_execution_paths.py` reproduces this
comparison against retained source snapshots.

`independent_run004_execution_optimized/` is the final independent continuous
audit after both execution optimizations. DOP853 qualification and prepared-step
equivalence pass with the same numerical results as run003, and source hashes
were unchanged during the audit. Its receipt SHA-256 is
`bef0f0b32296a04cbef59f62b78408567efcf4d857366c48e47d6c03fd57a4e4`.
The receipt records Python, NumPy, SciPy and Torch versions; source snapshots
remain available for every run, including the failed first qualification.

The unit tests also check all trainable scalar coordinates of a small flow
against central finite differences of the same discrete map, learned initial
state dependencies, C1 boundary matching, finite inactive branches at extreme
inputs, zero-time identity, input/state/time gradients, parameter layout parity,
and batch-composition invariance. A finite-difference match establishes
derivative correctness for that discrete map; it does not establish ODE-gradient
accuracy.

Reproduce from the repository root using the study's pinned Python environment:

```sh
python -m unittest experiments.call_put_stable_flow.tests.test_numerics experiments.call_put_stable_flow.tests.test_flow -v
python -m research_evidence.hepta_stable_flow_20261029.numerical_qualification.run_torch_qualification --output research_evidence/hepta_stable_flow_20261029/numerical_qualification/torch_new_run
```

The output directory must be new. An experiment never overwrites a prior receipt.
Formatting changes after a snapshot produce a new source hash; the snapshot
retains the exact bytes used by the recorded experiment.

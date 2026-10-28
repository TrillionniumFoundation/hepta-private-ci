# Mathematical contract for the continuous-boundary experiment

This experiment is a known-model, finite-horizon maintenance task. It tests
boundary and continuous-signal adapters connected to the original native sparse
kernel and NDU. It does not implement the complete He--Xiong financial model,
claim a closed-form network equilibrium, or infer a universal neural advantage.
`preflight/MATH_REFERENCE.json` contains computed numerical reference checks;
these are preflight calculations, not independent confirmation samples.

## 1. Physical state, decisions, and resets

The physical state is distance from failure, `x = V - B > 0`, with the physical
failure boundary fixed at `B = 0`. Within a decision window of length `dt`,

\[
dX_t=\mu\,dt+\sigma\,dW_t,\qquad
\tau=\inf\{t\geq0:X_t\leq0\},\quad\sigma>0.
\]

The drift, noise, discount, costs, reset levels, and remaining deadline are
public task parameters shared across arms. Decisions occur only at window
boundaries. Action order is `[wait, repair, stop]`:

- **Wait:** evolve from the observed current state.
- **Repair:** pay `K = maintenance_cost` immediately, reset to
  `maintenance_reset`, and evolve for the same window. There is at most one
  active repair decision in a window.
- **Stop:** receive exactly zero, terminate immediately, and incur no subsequent
  production, failure, or repair costs. The native abstain action maps to stop.

An uncontrolled physical failure at time `tau <= dt` pays failure cost `L` at
that time and ends production for the rest of the window. At the next decision
window the state is reset to `failure_reset`; future utility remains available.
The refractory period therefore lasts until the next scheduled decision tick.
This is a distinct profile from immediate continuous-time renewal after a hit.
There is no additional terminal reward or penalty after the last window.

Changing `dt` changes the physical intervention schedule and refractory rule,
not merely a numerical solver step. OOD comparisons with a different `dt` are
robustness tests on different tasks. Grid/domain refinement holds `dt` fixed.

## 2. Exact one-window kernels and primitive reward

The implementation reuses `first_passage_cell/kernels.py`:

\[
F_t(x)=\Pr_x(\tau\leq t),\quad S_t(x)=1-F_t(x),\quad
f_t(x)=\frac{dF_t(x)}{dt},\quad
H_{q,t}(x)=\mathbb E_x[e^{-q\tau}\mathbf 1_{\tau\leq t}].
\]

`K_t(x,y)` is the killed transition density:

\[
K_t(x,y)\,dy=\Pr_x(X_t\in dy,\tau>t),\qquad
\int_0^\infty K_t(x,y)dy=S_t(x).
\]

It integrates to survival probability, not one. The model never normalizes
away the probability of failure. Define discounted productive time

\[
A_{q,t}(x)=\mathbb E_x\int_0^{\min(\tau,t)}e^{-qs}\,ds
=\frac{1-e^{-qt}S_t(x)-H_{q,t}(x)}q\quad(q>0).
\]

At `q=0`, the implementation uses its continuous limit. If production rate is
`u`, the realized within-window reward is

\[
r=u\int_0^{\min(\tau,dt)}e^{-qs}ds
-L e^{-q\tau}\mathbf 1_{\tau\leq dt}
-K\mathbf 1_{\text{repair}}.
\]

For stop it is zero. Window `k` contributes `exp(-q*k*dt) * r` to episode utility.
The event sampler draws a hit using `F`, inverts conditional `F` for its time,
and uses `K/S` for the endpoint conditional on survival. It does not use an
endpoint-only barrier test. Fixed uniform slots preserve common random numbers
across different actions, failures, and stopped paths.

## 3. Continuation value and the numerical free boundary

With `n` windows remaining, `v_0 = 0` and `gamma = exp(-q*dt)`,

\[
Q_w^{(n)}(x)=uA_{q,dt}(x)-LH_{q,dt}(x)
+\gamma\left[\int K_{dt}(x,y)v_{n-1}(y)dy
+F_{dt}(x)v_{n-1}(r_f)\right].
\]

The term containing `v(r_f)` preserves continuation after physical failure.
Repair has value `Q_r^(n) = -K + Q_w^(n)(r_m)`. Stop has value zero, so
`v_n(x) = max(Q_w^(n)(x), Q_r^(n)(x), 0)`.

The active maintenance boundary is a crossing of
`Q_r^(n)(x) - max(Q_w^(n)(x), 0)`. The code checks threshold shape, interpolates
the crossing between grid nodes, and reports value-matching residuals. It does
not report a repair/wait crossing where stop is better than both actions.

This is a **numerical Bermudan intervention boundary**. Discrete intervention
times do not imply continuous-time smooth fit. No `v'(b)=0` condition is imposed
or claimed. The physical failure boundary `B=0` and active maintenance boundary
`b_n` are separate objects.

The primary grid integrates `K` over cells by Gauss--Legendre quadrature and
assigns surviving upper-tail mass to the final cell. Reset points use linear
mass interpolation between neighboring states. The independent oracle uses a
monotone finite-difference generator, matrix exponentiation, and a separate
Bellman loop; its upper truncation is reflecting. Agreement and grid/domain
refinement are checked explicitly. These are numerical approximations to the
continuous state law, not exact solutions of the full continuous control problem.

## 4. C and P are task components

The channel definitions are

\[
C_n(x)=uA_{q,dt}(x)+\gamma\left[K_{dt}v_{n-1}(x)
+F_{dt}(x)v_{n-1}(r_f)\right],\qquad
P(x)=LH_{q,dt}(x),\quad Q_w^{(n)}=C_n-P.
\]

Here `K v(x)` denotes the killed-kernel integral. In the adapter, each channel
is divided by `1 + n*dt*u`. C is productive continuation utility and P is
discounted physical failure loss. P is not the repair/wait action gap, an
undiscounted probability, or a separately calibrated financial put price.
The names do not establish statistical independence of the channels.

## 5. Exactly what flow versus event compares

All neural arms still execute sampled physical task paths. The continuous
adapter's reset/trace input is the **previous action-conditioned failure
probability**; `event_reset` uses the **previous observed failure** for its
internal reset and trace. Both use the same current C/P, margin, risk, public
context, state dimension, candidate schedule, native encoder, and head budget.
Their development-selected coefficients and learned readouts may differ.

The common typed `flow` is `previous_action_risk / dt`, clipped at 8. It is not
current `F(x)/dt`, the hitting density `f`, or a hazard `f/S`. Current `F(x)/dt`
would reveal current risk even in a nominal risk-masked ablation.

Filtered C/P states affect subsequent typed margin and drive. The expected-event
adapter attenuates old state by `1 - previous_action_risk`; the event version
uses `1 - previous_failed`. Expectation does not generally commute with these
nonlinear recurrent dynamics. This comparison does not claim such equivalence.

Separately, `evaluate_policy` propagates probability mass exactly on the declared
finite state grid for a supplied Markov action-probability table, splitting mass
across actions instead of averaging physical states. It is a mathematical check;
it is not a substitute for the recurrent native policies' sampled executions.

## 6. Information and parameter accounting

The 11 shared raw context fields are `x/2`, `remaining_windows/16`, `mu/0.6`,
`sigma/0.6`, maintenance cost, `failure_cost/6`, `u/1.5`, `q/0.2`,
`maintenance_reset/2`, `failure_reset/2`, and `dt`. Six adapter fields complete
17 raw inputs; typed margin/risk/flow produce a 20-dimensional encoder input.
Raw inputs and margin are clipped to `[-4,4]`; current risk lies in `[0,1]`.
Margin is normalized by `sigma*sqrt(dt)` before clipping and causal feedback.
The common deadline encoding exposes absolute remaining windows under different
OOD horizons; together with `dt`, every arm can recover the remaining duration.
This replaced a per-episode remaining fraction before any confirmation outcomes
were generated; the interrupted training-only run was retained separately.

The boundary panel is `fixed_margin`, `learned_margin`, and `value_margin`.
All three mask C/P/current-risk fields and differ by boundary source. Fixed and
directly learned boundaries access no DP values or DP boundary table at execution.
The channel panel adds C (`value_call`), then P/current risk (`value_dual`).
Value-derived channels and boundaries explicitly use the known-model DP solution;
solver costs and teacher availability are disclosed rather than hidden.

Every neural arm uses the same frozen seeded encoder: width 20, top-k 4,
temporal decay 0.75, and 420 fixed weight/bias coefficients. The trained native
wait/repair head has **42 active scalar parameters**: two times 20 weights plus
two biases. The stop head is literal zero, not counted padding.

The direct boundary regressor adds **20 trained coefficients**, so its total
trained scalar count is 62. Generic controls receive the same full derived
inputs: `generic_gate` adds 42 fixed seeded mixing coefficients;
`dense_recurrent` adds 78. `native_sparse` has no additional retained adapter
memory; the other adapters have six bounded state variables in addition to the
shared native sparse state. Counts are exposed by `ActorAdapter.metadata()`.

All arms receive the same exploratory histories and public-model Q teacher.
Readout fitting uses ridge regression; 12 scheduled feedback candidates per arm
are selected using development net utility. Some ablated coefficients are
inactive, so 12 scheduled fits do not imply 12 distinct functions for every arm.
The encoder and generic mixing matrices are frozen. There is no claim of
end-to-end recurrent BPTT or learning unknown physical laws.

## 7. Differentiability and scope

The analytic first-passage kernels have classical interior derivatives for
`x>0`, `t>0`, and `sigma>0`; derivative checks compare them with finite differences.
Boundary atoms and zero-time limits are handled separately. A fixed Bellman
branch and fixed interpolation bracket can have local derivatives, but `max`,
action-region changes, and degenerate crossings are not globally smooth.

Q24 quantization, sparse top-k, native action selection, and discrete candidate
selection are not claimed differentiable. The actual training procedure fits
readouts and selects feedback candidates. Mathematical smoothness of a value
component does not prove gradient stability of the whole network, recurrent
excitability, semantic memory improvement, or a total-cost advantage.

# Fixed-boundary distributional flow repair reference

This independent addon repairs the loss of pressure variance in the frozen
neural model's scalar mean closure. It retains a probability distribution and
propagates a conservative finite-state Markov generator, including repeated
events and refractory residence. It **does not change the frozen study, inspect
its outcomes, or supply another classification result**. The boundary and all
coefficients remain fixed during each rollout.

Source: `distributional_flow.py`; tests: `distributional_flow_tests.py`.
Final measurements: `results/flow_repair001/results.json`. The earlier numerical
pilot remains in `development_pilot.json`; the final record is also preserved
under `final/results.json`. The frozen neural model SHA256 remains
`c86535bf5b37589503aada3b1d979d80b75e54eb19e6be4f3b93482066147625`.
The measured addon source SHA256 is
`f63f0ba94e6ce0aa348e33557b20d64261308d10bf832d1f7324aceec79965a3`.

## What is exact and what is approximated

The target scalar process is arithmetic Brownian pressure with constant drift
`mu`, volatility `sigma`, upper threshold `b`, reset `r < b`, and deterministic
refractory duration `tau`. Each threshold hit increments the event count;
pressure stays at `r` during refractory residence and resumes diffusion afterward.
The finite model uses active nodes `x_i = L + i*h`, `h = (b-L)/n`, for
`i = 0,...,n-1`. Its nearest-neighbor rates are

\[
u=\frac{\sigma^2}{2h^2}+\frac{\max(\mu,0)}h,\qquad
d=\frac{\sigma^2}{2h^2}+\frac{\max(-\mu,0)}h.
\]

These nonnegative rates give a monotone upwind discretization. The lower endpoint
reflects. The upper outgoing rate is `u` from the last active node. A threshold
hit injects its mass into the first refractory phase, or directly into reset
weights when `tau = 0`. Linear interpolation distributes reset mass between
neighboring active nodes and preserves its mean. Initial and reset positions
below the boundary must lie within the represented active-node range.

For positive `tau`, `k` serial exponential phases each have rate `k/tau`. Their
total residence has mean `tau` and variance `tau**2/k`. Thus deterministic delay
is approached by increasing `k`; it is not exact at finite `k`. The zero-delay
branch is instantaneous reset with no phases, allowing arbitrarily many events
within a positive interval.

The column generator `Q` has zero column sums and nonnegative off-diagonal
entries. An extra state accumulates expected events:

\[
\frac{d}{dt}\begin{bmatrix}\pi\\c\end{bmatrix}
=\begin{bmatrix}Q&0\\\lambda^\top&0\end{bmatrix}
\begin{bmatrix}\pi\\c\end{bmatrix},
\qquad \lambda_i=u\,1\{i=n-1\}.
\]

`torch.matrix_exp` propagates this finite generator, including every regenerative
cycle within the interval. It satisfies the fixed-generator semigroup identity
to floating point accuracy. This is exact **for the finite generator**, not for
unbounded Brownian motion, a deterministic delay at finite `k`, or a neural
network with changing coefficients. Spatial upwinding, lower-domain truncation,
delta interpolation, and Erlang residence are separate approximations.

An initial active pressure at or above `b` triggers one event at time zero and
enters reset/refractory state. This reference includes that atom even at zero
horizon; the neural API's zero-duration no-op convention is different. A
refractory phase is not eligible to fire again until release.

## Independent renewal comparison

For a start below the threshold, the exact time of the `j`th event has the law
of a Brownian first passage over
`b-x + (j-1)*(b-r)`, plus `(j-1)*tau`. Summing its CDF gives `C(t) = E[N_t]`.
For positive `tau` the sum is finite. For zero delay, the code stops using a
Chernoff bound on the remaining nonnegative sum, with tolerance `1e-12`.

Let `I0 = integral_0^T C(s) ds`,
`Iprev = integral_0^max(T-tau,0) C(s) ds`, and
`I1 = integral_0^T min(tau,T-s)*C(s) ds`. Then

\[
D=I_0-I_{\rm prev},\qquad
E[X_T]=x+\mu(T-D)+(r-b)C(T),
\]

\[
B=xT+\frac{\mu T^2}{2}-\mu I_1-bI_0+rI_{\rm prev},\qquad
E[X_T^2]=x^2+2\mu B+\sigma^2(T-D)+(r^2-b^2)C(T).
\]

These formulas supply the independent moment reference used here. Numerical
quadrature errors in the JSON are estimates for each **unscaled integral**,
not certified error bounds on the final moments. The generator orientation,
reset injection, phase chain, event augmentation, renewal tail bound, and
second-moment identity received an independent mathematical review.

With `L=-4`, 256 active nodes and 32 refractory phases (zero phases for `tau=0`):

| Case | Exact E[N] | Finite E[N] | Exact E[X] | Finite E[X] | Exact variance | Finite variance |
|---|---:|---:|---:|---:|---:|---:|
| Zero drift, T=1 | 0.342765 | 0.342894 | -0.342765 | -0.342880 | 0.478050 | 0.478007 |
| Positive drift, T=2 | 0.599672 | 0.603095 | -0.021960 | -0.026578 | 0.277892 | 0.280636 |
| Negative drift, T=2 | 0.274653 | 0.278502 | -0.753753 | -0.757938 | 0.587209 | 0.591667 |
| Instantaneous reset, T=2 | 0.675660 | 0.677979 | -0.310792 | -0.313552 | 0.461356 | 0.463649 |

The JSON records all parameters and grids `n=32,64,128,256`. Count errors reduce
in each case as the spatial grid refines; residual error from finite `k` and
finite `L` remains. Across these 16 configurations, maximum absolute mass error
was `1.83e-12`, and all reported probabilities were nonnegative.

Delay refinement at fixed `n=192` gave event counts `1.329692`, `1.306890`,
`1.301197`, and `1.299779` for `k=1,4,16,64`, versus the deterministic-delay
reference `1.293827`. Increasing `k` alone cannot remove the spatial error.

Lower-bound refinement at fixed `h=.05` illustrates another distinct error.
For the recorded `T=3` zero-drift case, exact mean and variance are `-0.869107`
and `1.206097`. At `L=-1,-2,-4,-6`, finite means are `-0.219941,-0.625536,
-0.856219,-0.868948`, and variances are `0.223178,0.561789,1.124064,1.203646`.
Event counts converge earlier than moments; an accurate count alone does not
certify an adequate lower domain.

## Refining time no longer destroys variance or events

The same finite generator is propagated over `T=1`, with 128 active nodes,
32 phases, `mu=0`, `sigma=1`, `b=1`, `r=0`, `tau=.2`, `x=0`, `L=-4`.

| Equal time partitions | Distribution E[N] | Distribution variance | Frozen mean-closure E[N] |
|---:|---:|---:|---:|
| 1 | 0.343061944 | 0.478080395 | 0.317310508 |
| 4 | 0.343061944 | 0.478080395 | 0.132476436 |
| 16 | 0.343061944 | 0.478080395 | 0.001003836 |
| 64 | 0.343061944 | 0.478080395 | 7.8894e-14 |
| 256 | 0.343061944 | 0.478080395 | 1.6355e-55 |

The distribution retains its variance and its event count. Count changes across
these partitions are about `3e-15`; variance changes about `7e-15`. The remaining
difference from the continuous renewal reference is spatial/domain/delay error,
which time subdivision does not remove. The mean-closure column is reproduced
from its read-only implementation in `closure_audit.py`, independently of any
classification measurements.

## Differentiation and a small inverse problem

Torch differentiates the matrix exponential, rates, reset weights, and a static
boundary-dependent grid. At a nonzero drift, positive delay, and positions away
from grid knots, centered finite differences with step `1e-5` agree with
autograd for `mu`, `sigma`, `b`, `r`, and `tau`. Maximum relative error was
`1.38e-9`. This checks local derivatives of this finite discretization. It does
not justify differentiability across grid knots, a drift-sign kink, or the
`tau=0` branch, or solve a time-varying-boundary remapping derivative.

A 200-step scalar fit uses mean, variance, and event-count targets from the
independent renewal formulas at `T=.4,1,2,4`. It learns drift, volatility, and
reset jointly on a 64-node, 16-phase grid. The first pre-update loss was
`0.194336`; evaluating the final parameters gives `1.5833e-5`. Parameters moved
to `mu=.239106`, `sigma=.640947`, and `r=-.251589`, versus exact-source values
`.25,.65,-.3`. First task gradients for drift, raw volatility, and reset were
`-.934416,.266332,-.101800`. Finite discretization bias and finite optimization
remain visible, especially for reset. This is a small differentiability and
moment-fitting demonstration, with no classification data, heldout quality,
generalization, or foundation-model claim.

## Cost and reproducibility

The final script used Torch `2.8.0+cpu`, float64, one intra-op and one inter-op
thread, on the same AMD EPYC 9V74 host as `SCALING.md`. The complete numerical
script consumed `8.5604` process CPU seconds, including `6.5893` seconds for the
inverse fit. The 16 grid-case measurements took about `1.76–35.08` ms each for
generator construction, matrix exponential, propagation, and moments. These
are single scalar measurements, not warm repeated network benchmarks. Dense
matrix exponentiation has substantial cost and storage; no energy was measured.
An active grid with 256 nodes and 32 phases retains 288 probabilities plus a
count and exponentiates a 289-by-289 augmented matrix. This is a reference for
correctness, not an efficient substitute for the current many-channel cell.

Six tests cover conservation and repeated events, semigroup composition,
renewal approximation including negative drift and zero delay, five-parameter
gradients, initial atoms, and differentiable phase-aware projection.

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime \
python -m unittest experiments.hcsn_free_boundary_v1.distributional_flow_tests

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime \
python -m experiments.hcsn_free_boundary_v1.distributional_flow --output NEW_EMPTY_DIRECTORY
```

## Concrete path to a future cell

1. Retain `pi` over each pressure grid and refractory phases between observations.
   Preserve high-dimensional content memory separately. Passing only `E[X]`
   into the next interval would reintroduce the original defect.
2. Use `moments(flow,state)` for pressure moments, phase mass and cumulative
   count. The interval's expected event count is the change in the accumulator,
   equivalently integrated upper-boundary flux. It is not a clamped probability
   and may exceed one.
3. Supply active-state `J` and `G` arrays, along with explicit phase-specific
   continuation features, to `project_values`. This permits gates to consume
   `E_pi[J]` and `E_pi[G]` with gradients. Refractory states require an action
   eligibility mask and continuation values compatible with their remaining
   delay; blindly using active values at `r` for every phase would be incorrect.
   The API therefore requires explicit refractory feature values when phases
   exist. The policy value for an Erlang approximation should be matched to that
   generator, or its mismatch to deterministic-delay values disclosed.
4. Input-dependent drift and volatility can define a piecewise-constant
   generator while retaining probability. A changing boundary requires a
   **mass-conserving remap in physical pressure coordinates**. Active mass that
   lies above a newly lowered boundary must fire immediately and enter the
   appropriate reset/refractory state, adding to the event accumulator. Merely
   relabeling old probability entries with new grid coordinates changes pressure
   without a physical transition and does not implement this contract.
5. A changing reset or refractory law also needs a specified rule for mass
   already waiting in refractory phases. A neural implementation must resolve
   that rule, moving-boundary gradients, projection semantics, batching, sparse
   or structured exponential actions, and their cost before a new frozen
   classification comparison is warranted.

Only the scalar fixed-boundary propagation, its derivatives, and generic value
projection are implemented here. Moving boundaries, full content integration,
and useful task performance remain open work. The current frozen neural model
continues to be reported as a mean-state surrogate with the limitations in
`CLOSURE.md`.

# Joint continuous latent / valuation Riccati oracle

This is layer 1 of the NDU continuous-latent mechanism experiment. It establishes
numerical correctness on a deliberately coupled, known linear-quadratic system.
It does not establish neural generation quality, a new control theorem, or large
model performance. The recorded execution tier is **local-preflight**.

## Mathematical contract

Let `x=(z_1,z_2,p_1,p_2)` and `u=(a_1,a_2,nu_1,nu_2)`. The continuous system is

`dx = (A x + B u) dt + Sigma dW`, for `0 <= t <= 2`.

The objective is fixed externally:

`J = E[ integral_0^T (x' Q x + u' R u)/2 dt + x_T' H x_T/2 ]`.

Controls are unconstrained; the full state is observed; the discount rate is
zero. `Q`, `H`, and `R` are positive definite. The two preference rows of `A`
and `Sigma` are zero: preference evolves only through the costly active control
`nu`. Thus `nu=0` exactly freezes preference. Nonzero `A_zp` and `Q_zp` create
joint dependence; the external objective cannot be redefined by changing `p`.
The exact matrices and initial state are retained in the result JSON.

With `V(t,x) = x' S(t) x/2 + c(t)`,

`-dS/dt = A' S + S A + Q - S B R^-1 B' S`, `S(T)=H`,

`u* = -R^-1 B' S x`,

`c(0) = integral_0^T tr(Sigma Sigma' S(t))/2 dt`.

The full costate is `pi=Sx`, and the BSDE noise sensitivity is `Z=Sigma' pi`.
Here `Z` cannot recover the preference costate. The `Z`-only arm is given the
exact `Z` and uses `pinv(Sigma') Z`, so it is an information-loss diagnostic,
not a deliberately poorly trained neural baseline.
The pseudoinverse restriction is essential: an architecture with access to the
full state, a value function, or additional adjoint equations can compute the
missing costate by other means. This comparison is not a lower bound on every
possible architecture trained with a `Z` representation.

These conditions are narrower than general FBSDE existence and uniqueness. The
NDU source version motivating active valuation is
[NDU main.tex, commit 85ef03e](https://github.com/TrillionniumFoundation/NDU/blob/85ef03ef3ec871edd4ba8039e400169a14ec774f/main.tex).
This benchmark uses the exact unconstrained LQ subfamily, not the manuscript's
compact-control certificate as a global unconstrained theorem.
The variable `p` is an adjustable internal valuation-state surrogate in this
engineered augmented-state model. It does not implement arbitrary nonlinear
preference weighting such as `z' Q(p) z`, which would generally destroy the
joint quadratic closure.

## Independent verification

`benchmark.py` performs all of the following:

1. SciPy DOP853 integrates the continuous Riccati differential equation.
2. SciPy `solve_bvp` independently solves the joint state / Pontryagin costate
   boundary problem from a constant-state, zero-costate initial guess. It does
   not use the Riccati solution to initialize or solve the boundary problem.
3. A condensed quadratic program eliminates all Euler-discretized states and
   solves one dense linear system. Its controls and value are compared with a
   separately implemented discrete Riccati recurrence. Mesh sizes 16, 32, 64,
   128, and 256 demonstrate convergence toward the continuous value.
4. A PyTorch RK4 solver is compared with the high-accuracy continuous solution
   over 16, 32, 64, and 128 steps.
5. Gradients through the Riccati solve, policy, and feedback rollout are compared
   with centered finite differences for three parameters. The outer objective
   differs from the inner optimized objective.
6. An independent forward second-moment ODE evaluates stochastic feedback cost.
   It agrees with the analytic value at noise scales 0, 0.5, 1, and 2. Feedback
   is unchanged under additive exogenous noise in risk-neutral, fully observed
   LQ control. This negative control prevents a false covariance-sensitive claim.

## Mechanism comparisons

All arms use the same true dynamics, external cost, initial state, and diffusion.
The fixed-preference arm is independently reoptimized over the remaining
generation controls. Other ablations remove information or structure from the
exact full selector. Low-rank arms project each dense `S(t)` onto its largest
eigenvalues; they are approximations, not closed low-rank Riccati families.

| Selector | Expected cost | Relative regret |
| --- | ---: | ---: |
| Full gradient / dense Riccati | 2.500771 | 0.000% |
| Exact `Z`, pseudoinverse costate | 5.143406 | 105.673% |
| Frozen preference; reoptimized generation | 5.096508 | 103.797% |
| Removed `S_zp`, `S_pz` | 2.734749 | 9.356% |
| Rank 1 projection | 9.511373 | 280.338% |
| Rank 2 projection | 2.587431 | 3.465% |
| Rank 3 projection | 2.556821 | 2.241% |

The full policy's advantage is expected from the constructed known system and
optimality theorem; it is not a discovery or held-out neural efficacy result.
These comparisons establish that the test can detect removal of the proposed
mechanisms. Neither an advantage in arbitrary tasks nor superiority to a fully
trained unrestricted controller follows.

## Execution

In a Python environment with NumPy, SciPy, and PyTorch:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python benchmark.py --output results.json
```

The retained `development_results.json` records versions, runtime, source
SHA-256 values, matrices, numerical errors, every ablation, and the seven
numerical gates. Local validation used PyTorch 2.5.1+cpu, NumPy 1.26.4, and
SciPy 1.17.0. The local existing Torch environment and the primary runtime's
SciPy package were read without modifying either environment.

`solver.py` exports `torch_dre(A,B,Q,R,H,horizon,steps) -> (S,K)`. `S` and `K`
are on the ascending uniform time grid, and `u=-Kx`. The solver preserves the
autograd graph. It assumes constant coefficients and does not enforce positive
definiteness or rescue invalid problems by clipping eigenvalues. The caller is
responsible for imposing the stated model family and checking numerical scale.

## Audit of the nonlinear model's local solver

`local_control_audit.py` independently checks `../control.py`. Its result is
`local_control_audit_results.json`, with the exact audited source hash. Run it
from any directory with:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python local_control_audit.py --output local_control_audit_results.json
```

It eliminates states in 15 batched affine problems with nonzero dynamics and
cost offsets, then compares the first action, value curvature, affine value
term, and value gradient against a condensed QP and Schur complement. Flow and
joint-state Jacobians are checked against automatic differentiation, including
the nonlinear preference derivatives. The Gauss-Newton curvature is checked
against an independently differentiated residual; the affine cost matches the
exact first derivative of the nonlinear state cost.

For actual local NDU actions, the audit independently builds the Euler model
and Gauss-Newton cost using automatic differentiation, solves a condensed QP,
and checks the action and returned value coefficients. Cases include a one-step
remaining horizon and disabled valuation actuators. Finally, three network
parameter derivatives through a full nonlinear NDU rollout are checked with
centered finite differences. All seven audit gates pass in the retained run.

`S,s` describe the initial value of the local discrete problem. The correct
first feedback is `-K x-k`; it must not be replaced by the continuous-time
formula using those initial value coefficients. Gauss-Newton is not the true
nonlinear Hessian. The local model freezes coefficients and time within each
lookahead, and a fixed lookahead step count gives different physical horizons
when the outer time step changes. These are explicit approximation choices,
not global nonlinear optimality guarantees.

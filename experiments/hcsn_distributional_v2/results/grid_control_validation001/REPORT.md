# Finite-state impulse-control reference 001

## What this establishes

`grid_control_reference.py` adds a separate, certified optimal-control reference for the **fixed finite state space and its declared actions**. It is not imported into the frozen neural model. It does not replace that model's own-policy J with an optimal value while leaving the old flow unchanged.

The existing finite generator has a natural upper-boundary firing action. The reference additionally permits immediate FIRE at every active cell center, with reward x_i-K followed by entry into refractory phase zero. Every refractory phase forces continuation. The lower wall, upper boundary, cell grid, reset interpolation and Erlang law remain fixed. A positive discount, at least one refractory phase and a positive refractory mean are required. This excludes zero-time repeated intervention cycles.

This extends the policy class on one fixed finite model. It neither optimizes the outer boundary/domain nor proves the optimum of the original continuous diffusion, deterministic-delay model, financial credit model, or neural task objective.

## Value equations and orientation

The source explicitly names the forward column generator Q and backward operator A=Q^T. A column probability solves dp/dt=Qp; row probabilities propagate as p exp(A t). With natural event-rate vector lambda and natural reward-rate g=(b-K)lambda, define

\[
C_i(V)=g_i+(AV)_i-\rho V_i,
\qquad I_i(V)=x_i-K+V_{phase,0}.
\]

The active-state quasi-variational inequality is

\[
\max\{C_i(V),I_i(V)-V_i\}=0.
\]

Refractory states satisfy C_i(V)=0 and have no FIRE action. Thus every feasible firing value includes its actual regenerative future return through the phase-zero value. All-CONTINUE evaluation solves

\[
(\rho I-A)J=g.
\]

The audit aligns this all-CONTINUE vector state by state with the existing kernel's `policy_value_vectors`, and separately with an independently assembled NumPy physical generator. It does not rely on two control solvers sharing the same transposition convention.

For a Boolean intervention set F, policy evaluation uses a continuation row of rho I-A for i outside F, and the row e_i-e_phase0 with right side x_i-K for i in F. Phase rows always continue. Howard improvement compares immediate FIRE with the normalized continuation alternative

\[
V_i^{cont}=\frac{g_i+\sum_{j\ne i}A_{ij}V_j}{\rho-A_{ii}}.
\]

A tie retains the current action. A stationary policy is accepted only if **both** continuation and obstacle inequalities, active complementarity, selected equations and forced phase equations pass. Cycle or iteration-limit detection raises rather than returning an unverified optimum. The test suite also starts from the all-FIRE policy and reaches the same value.

## The controlled flow changes with the selected policy

Instantaneous FIRE states are eliminated when propagating the controlled process. Let C contain the non-FIRE active states and every phase; let u_0 identify refractory phase zero in C. The retained column generator, reward rate and event rate are

\[
\widetilde Q=Q_{CC}+u_0\mathbf1_F^TQ_{FC},
\qquad\widetilde g=g_C+Q_{FC}^TR_F,
\qquad\widetilde\lambda=\lambda_C+Q_{FC}^T\mathbf1_F.
\]

Here R_F consists of the rewards x_i-K. Initial mass on a FIRE state immediately earns its reward, adds one event and moves to phase zero. The initial mapping and these immediate rewards/counts are returned explicitly. Probability self-return terms may cancel in the reduced generator, but marked event and reward contributions are still counted. This matters when release from the last refractory phase lands in a FIRE cell.

The source includes this controlled generator and a small dense reference propagator. It checks conservation, nonnegative off-diagonal rates, repeated counts, zero-time impulses and the dynamic consistency identity

\[
pV=E_p[\text{discounted rewards through }t+e^{-\rho t}V(X_t)].
\]

An all-FIRE test is deliberately included even though its value can be negative: it exercises repeated regenerative impulses and prevents a nonnegative-value assumption from hiding a reward bookkeeping error. A disconnected FIRE set tests policies beyond a threshold-shaped intervention region.

## Independent checks

The audit uses six physical scenarios, including drift of either sign and a zero-noise case. It covers n=4,6,8 for exhaustive policies and n=4,8,17 for all-CONTINUE generator/value checks. Every one of the 2^n Boolean policies is evaluated by an independent NumPy eliminated-generator route; the maximum is taken state by state, and the existence of one stationary policy attaining that entire vector is checked. No threshold-mask assumption is used.

The path reference separately simulates the original finite CTMC and applies immediate FIRE decisions on arrival. It does **not** simulate the reduced controlled generator. Two seeded 20,000-path cases test the selected optimal policy and the all-FIRE policy. Individual path counts, rewards, discounted returns and terminal states, together with all enumerated policy masks and vectors, are retained in `RAW_REFERENCES.npz` and hash-bound in `RESULTS.json`.

| Check | Result |
|---|---:|
| Enumerated policy evaluations across 18 problems | 2016 |
| Howard versus exhaustive, maximum value error | 1.7763568394e-15 |
| All-CONTINUE versus existing kernel, maximum error | 2.6645352591e-15 |
| Maximum QVI/inequality/phase residual | 2.3037127761e-15 |
| Controlled reward plus terminal value, maximum error | 3.73034936274e-14 |
| Seven physical gradients, maximum scaled FD error | 3.45507020231e-09 |

The initial-position comparison below uses x0=0 and n=8. These are finite-model control improvements, not task-accuracy or economic-return improvements.

| Scenario | All-CONTINUE J | Optimal finite-control V | Relative change | FIRE cells |
|---|---:|---:|---:|---|
| central | 0.11399112227 | 0.114022173665 | 0.027240% | [7] |
| negative_drift | 0.00362758766493 | 0.00362758766493 | 0.000000% | [] |
| positive_low_discount | 1.44877808896 | 1.588382512 | 9.636011% | [7] |
| large_noise | 0.961810561689 | 1.00695707026 | 4.693909% | [7] |
| negative_high_noise | 0.071702975514 | 0.071702975514 | 0.000000% | [] |
| no_upward_noise | 0 | 0 | undefined (zero baseline) | [7] |

The positive-low-discount case improves by 9.6360% on this coarse grid; the large-noise case improves by 4.6939%. This confirms the earlier distinction between an exactly evaluated chosen policy and the optimal policy in a larger finite action class. It does not imply that the fixed outer boundary is globally optimal, nor that these finite-grid improvements survive spatial refinement or improve content tasks.

| MC policy | Event z | Reward z | Discounted value z | Expected events |
|---|---:|---:|---:|---:|
| optimal | 0.288401 | 0.288401 | 0.989181 | 2.264280438 |
| all_fire | 0.063776 | 0.876676 | 1.055595 | 6.633801377 |

## Differentiation scope

After the discrete active set is selected, the source recomputes its linear solve with gradients enabled. On a fixed policy branch, A_pi V=h_pi gives

\[
dV=A_\pi^{-1}(dh_\pi-dA_\pi V).
\]

Torch differentiation through the solve is checked against seven finite differences for drift, noise, outer boundary, reset, refractory mean, discount and cost. Both sides of every finite difference independently select the same action set. The checked objective includes the boundary-dependent initial distribution. The minimum inactive-equation margin in the tested branch is recorded; no derivative through a policy switch or interpolation knot is claimed.

This oracle therefore supplies a piecewise differentiable optimal value and its matching controlled process. A jointly trained neural implementation would still need batched active-set handling, a matching controlled propagator, explicit branch treatment and a fresh registered comparison. The existing model remains the declared own-policy J/G model.

## Measured computation

All timings below are scalar float64 reference work: physical generator assembly, Howard selection, final value evaluation, and optionally backward through the chosen branch. They include no optimizer update, sequence batching or task training. Each median is from five recorded repeats after a warmup. Sparse/batched optimization has not been claimed from these measurements.

| Active cells | Forward median CPU ms | Forward + backward median CPU ms |
|---|---:|---:|
| 4 | 1.935811 | 2.387342 |
| 8 | 1.636834 | 3.284385 |
| 16 | 3.130849 | 3.371075 |
| 32 | 3.491982 | 3.606735 |
| 64 | 1.992554 | 3.503409 |

The complete source-bound audit process used 3.898521000 CPU seconds and 14.165692788 wall seconds, including interpreter/import/serialization/exit; Linux peak RSS was 208484 KiB. A preliminary five-case smoke was executed before the urgent duration repair without a complete CPU receipt. Its exact printed results and the unmeasured-cost limitation are retained in `results/grid_control_development001/SMOKE.json`; the formal receipt is not a claim to count all development compute. No GPU or energy measurement was taken.

## Source identity and reproducibility

The frozen kernel and model hashes matched before the final source snapshot; neither was modified by this reference. The source-bound test results, full process receipt, raw references and exact four-file source snapshot are preserved here.

| Source | SHA256 |
|---|---|
| distribution_kernel.py | `07195028877b4eb24f1bb1b53f1337019daf7bdabbdecbcd059f89079ba23de6` |
| grid_control_reference.py | `1aea0f50b1a8328394a2c2260dd89fc8203d416e73e1db8c3d38baf2e7ce2d84` |
| grid_control_tests.py | `aebdf943a97e130d46ac51e9f997813721c05d699647523a3a09108938e7e214` |
| model.py | `3eb5f6b8797475abf84b09ae5b588f3d0a253e0584578586cb081f15142a355f` |

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python -m experiments.hcsn_distributional_v2.grid_control_tests --output NEW_EMPTY_DIRECTORY
```

The run requires the recorded CPU PyTorch/NumPy/SciPy runtime. Existing evidence directories are not overwritten.

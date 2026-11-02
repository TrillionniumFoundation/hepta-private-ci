# Draft: convergence of the ideal causal jump-aware finite-difference map

Status: theorem/proof draft for independent review. This is not inferred from
R18 residual tables. It concerns the ideal numerical map under the conditions
below; the fixed-tolerance FP64 implementation is not automatically an entire
asymptotic sequence. No new executable convergence test has been opened.

## K1. Exact scheme and interpolation contract

Fix one admissible continuous task of PROBLEM_AND_THEOREMS.md. Choose uniform
spatial steps h=L/N→0 and time steps Δ→0 with ρ/Δ an integer. Each admission
kρ must coincide across all levels. Extend spatial nodal values evenly onto
the circle of circumference2L. The R18 reflected endpoint rate2D/h² is precisely
the restriction of the ordinary centered periodic Laplacian to that even grid.
There is therefore no unverified one-sided reflecting-boundary consistency.

On each open/left-trace slab, with its already known delayed obstacle H_h^n,
solve exactly the LCP

    min(v_i^n−H_i^n,
        (v_i^n−v_i^(n−1))/Δ − Q_h v_i^n + c)=0.             (K.1)

Here Q_h is the centered periodic diffusion generator, restricted evenly. The
reset obstacle is a nonnegative linear interpolation at x_r followed by M and
κ subtraction. At a slab's upper endpoint it uses the previous left trace.
Then apply the new right admission separately:

    G_h^(k+1)=max(W_h^k(ρ), −κ+M I_h G_h^k(x_r)).            (K.2)

This is the left/right order in actual jump_solver.py. An implicit step using
the newly available right obstacle before the jump is a different finite map.

Interpolate each W_h^k only within its own closed trace slab, from its initial
right value to its final left value. Set the global value at the admission to
the new right G_h. Never interpolate across a jump using the next right value.
This trace-aware reconstruction is part of the convergence statement.

## Theorem K (qualitative value convergence)

For fixed σ>0, bounded Lipschitz payoff, compact interval, nonnegative costs,
stochastic M and positive fixedρ, suppose all LCPs in(K.1) are exact, the initial
samples converge uniformly, and h,Δ→0 with alignedρ. Then each closed trace
slab W_h^k converges uniformly to the continuum W_k; all G_h^k converge uniformly
to G_k. The trace-aware global reconstruction consequently converges uniformly
to the right-valued càdlàg continuum task value on any finite aligned horizon.

No coupling restriction Δ/h² is required for this implicit central-diffusion
scheme. This statement does not cover the separate hat-quadrature reference,
whose repeated projection has additional h²/Δ and quadrature consistency
obligations. It asserts no rate, spatial derivative convergence or free-boundary
location/smooth-fit convergence.

For approximate LCP solves, it is sufficient that the residual in the scaled
operator(K.1) tends uniformly tozero and that obstacle/interpolation perturbations
tend uniformly tozero. In particular an unscaled complementarity residual r_h
must satisfy r_h/Δ→0. A constant absolute tolerance, or a few finite measured
residuals, does not establish that asymptotic condition.

## Proof

### 1. Discrete comparison and stability

Q_h has nonnegative off-diagonal entries and zero row sums. A=I−ΔQ_h is an
M-matrix. Let u be a discrete subsolution and v a discrete supersolution with
ordered previous values and obstacles. At a strictly positive maximum of u−v,
the u row cannot be on its obstacle if that would exceed v. Its continuation
inequality and the v supersolution inequality give A(u−v)≤0 there. But
Q_h(u−v)≤0 at a maximum, so A(u−v)≥u−v>0, a contradiction. The same argument
with a constant shift gives the sup-norm data estimate

    ||S(f1,H1)−S(f2,H2)||∞
      ≤max(||f1−f2||∞,||H1−H2||∞).                         (K.3)

For completeness, choose q≥max_i(−Q_h,ii). The LCP is equivalent to
v=max(H,Cv+d), where C=Δ(Q_h+qI)/(1+Δq) is nonnegative with row sum
β=Δq/(1+Δq)<1 and d=f/(1+Δq). This map is a sup-norm contraction, so
Banach iteration gives existence and uniqueness without an assumed policy-
iteration termination theorem. Constants0 and1 are sub/supersolutions for
registered nonnegative costs and bounded obstacles, so 0≤v≤1. The positive
reset interpolation, stochastic M and admission maximum preserve order and
sup-norm stability. These facts do not depend on a selected active branch.

### 2. Interior consistency and half-relaxed inequalities on the circle

For every C^(1,2) periodic test φ,

    (φ(t,x_i)−φ(t−Δ,x_i))/Δ − Q_h φ(t,·)_i+c
       → φ_t−Dφ_xx+c.                                    (K.4)

At a local grid maximum of v_h−φ, the backward time difference of v_h is at
least the test's difference, while Q_h v_h is at most Q_h φ. If the limiting
upper value lies strictly above its obstacle, the discrete PDE component is
zero, giving φ_t−Dφ_xx+c≤0. Otherwise the obstacle component already gives
the subsolution inequality. At a local grid minimum the inequalities reverse;
feasibility gives both the obstacle bound and φ_t−Dφ_xx+c≥0. Hence the bounded
upper/lower half-relaxed limits are viscosity sub/supersolutions on the circle.

A strict quadratic localization supplies local maximizing/minimizing grid
points. The previous-time point and nearest spatial neighbors remain in the
local neighborhood. Standard vanishing constant perturbations of the test
handle non-strict extrema. No grid residual is used as a continuum theorem.

### 3. Initial trace barriers

Let z be the continuous initial value of the slab and H(0)≤z. For ε>0 choose
smooth even periodic φ≥z and ψ≤z uniformly withinε. For sufficiently smalls,
continuity gives H(s)≤z+ε. The functions

    upper=φ+2ε+Cs,       lower=ψ−2ε−Cs

are discrete super/subsolutions for C larger than the bounded centered test
curvatures plus c+1, uniformly over sufficiently fine meshes. Small initial and
obstacle data errors fit inside the ε allowance. Discrete comparison yields
the correct upper/lower initial traces as s,h,Δ↓0. This prevents an unstated
terminal/obstacle compatibility assumption.

By semicontinuous scalar comparison on the circle, the two half-relaxed limits
coincide with the continuous stopping-slab value. Compactness then gives uniform
convergence on compact time subintervals. For the slab's upper left endpoint,
continuously extend its *old/left* obstacle a short distance pastρ as a proof
device. The causal scheme and PDE up toρ are unchanged. The endpoint is then
interior to that extended comparison problem, so the left trace also converges.
This extension does not activate the new physical reset opportunity early.

### 4. Delayed obstacle and jump induction

The first slab has no delayed obstacle and has just been covered. Assume
uniform convergence of every previous closed trace slab and right admission.
At a reset point the interpolation error is bounded by the previous uniform
value error plus the continuum spatial modulus over h. M is stochastic, so
applying M cannot amplify the sup norm. Therefore the next delayed obstacle
converges uniformly on its entire closed trace slab, including the appropriate
right/left endpoint convention. Steps1–3 apply again.

Finally max is1-Lipschitz in sup norm, giving uniform convergence in(K.2).
Only finitely many slabs are needed on a finite horizon. Stitching the aligned
right values and separate left-trace reconstructions proves the asserted
càdlàg value convergence.                                             □

## What this does not prove

- A shifted/rounded recovery lag can move a positive admission jump. Uniform
  convergence of ordinary time interpolants can then fail, even if the shift
  tends tozero. Alignment/trace handling is not optional here.
- Uniform values alone do not certify free-boundary locations. On a compact
  subset of {U>H} a positive gap is eventually detected, but an almost-zero
  numerical gap does not prove exact contact.
- A certified upper continuation point plus an analytic reset-contact point
  can bracket a monotone RESET interval. The task draft gives exact all-RESET
  regions and one coarse first-admission analytic bracket, not arbitrary narrow
  location brackets.
- No single STOP graph or global smooth fit has been shown. At actual admission
  dates the obstacle/value can have spatial corners as well as time jumps.
- Gradient convergence, finite-precision/FP32 qualification, continuous hitting-
  time owner execution, full finance, neural gain and adoption are separate.

The proof uses the half-relaxed-limit strategy of Barles–Souganidis, but verifies
its actual circle consistency, slab initial traces, delayed interpolation and
admission induction here. A bare citation to that framework would not establish
these task-specific obligations.

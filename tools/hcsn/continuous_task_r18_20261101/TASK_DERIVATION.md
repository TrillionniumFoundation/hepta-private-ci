# Continuous task, delayed reset and the admission-time jump

The task is deliberately reduced and synthetic. Public state is retrieval
quality `x∈[−4,4]` and an observed two-valued content mode `j`. The state is not a
hidden semantic label or a learned belief. Between interventions, quality is a
reflected Brownian motion with generator `L=(σ²/2)∂xx`. At STOP the owner samples
actual success with propensity

`g_j(x)=base_j+amplitude_j sigmoid(1.3x)`.

The actor sees this declared propensity law and the current state, not the
future sampled success. Terminal correctness is a synthetic content-quality
score, not an open-domain semantic, audio or cross-modal task.

WAIT consumes actual time and costs `c_wait` per unit time. RESET costs `k_j`,
consumes exactly `ρ=.2` autonomous recovery time, costs `c_rec ρ`, returns to
`x_reset=.6`, and samples a new observed mode with row `M_j`. Reset itself pays
no content reward. The owner then makes further decisions with the true
remaining time. RESET is admissible only when it finishes by the deadline,
including equality. The positive minimum recovery time bounds the number of
resets by `floor(T/ρ)` and prevents instantaneous reset loops.

For remaining time `t`, the objective is the supremum of expected actual STOP
reward minus all WAIT/recovery time costs and reset fees over these admissible
strategies. Define `V_j(0,x)=g_j(x)` and, when `t≥ρ`,

`B_j(t)=−k_j−c_rec ρ+Σ_l M_jl V_l(t−ρ,x_reset)`.

For `t<ρ`, no reset obstacle is present. Thus the reset operator retains the
whole successor value, subsequent resets, content changes and remaining time;
it is neither an immediate STOP reward nor an event-probability proxy.

On each open time interval without a reset-admission jump, the dynamic
programming obstacle relation is

`min(V−g, V−B, ∂t V−L V+c_wait)=0`,

with the reset term omitted when unavailable. Reflection is imposed on the
waiting generator. At a physical endpoint where immediate exercise is active,
no global classical Neumann derivative of the exercise payoff is claimed; the
Markov semigroup and obstacle determine the boundary inequality.

A deterministic minimum recovery creates a genuine admission discontinuity at
`t=ρ`, propagated through `B(t)` at multiples of `ρ`. The correct right limit is

`V_j(kρ,x)=max(V_j(kρ−,x), B_j(kρ))`.

At the first jump, the left limit is the no-reset stopping value. At later
jumps, the left reset obstacle uses `V((k−1)ρ−,x_reset)`, while the new right
obstacle uses `V((k−1)ρ,x_reset)`. A newly feasible reset cannot be available
while waiting in the preceding interval. The original implicit run01 solver
spread the new obstacle through that preceding implicit step. The explicitly
post-outcome `jump_solver.py` repair evolves the left limit first and then
applies the new right obstacle. The old solver and all its numerical failures
are preserved; they are not retroactively called a passed admission check.

At regular interior spatial contacts, STOP smooth fit is `V_x=g'_j`; a RESET
obstacle independent of x instead has contact slope `V_x=0`. The finite checks
sample times `.3,.5,.7,1.1`, away from the admission dates. Discrete contact
nodes are numerical estimates, not certified brackets around a continuous free
boundary. A mode may have no continuation interval, in which case no fabricated
pair of contact boundaries or smooth-fit statistic is supplied.

## Independent positive propagation

The reference uses the reflected Brownian Gaussian image density, equivalently
an even periodic extension on a period twice the interval length. It integrates
that positive density against nonnegative linear hat functions by positive
Gaussian quadrature. Exact hats partition unity, so their exact integral is a
stochastic kernel. The numerical row mass and 8-versus-16-node quadrature
agreement are measured without clipping or renormalizing. Image truncation has
an explicit log tail bound. Floating-point Gaussian tail underflow is retained;
no full extremely-small-support or Bayes-denominator claim is made.

The FFT implements convolution of those already nonnegative weights. It is not
a spectral sign correction. Linear interpolation/projection remains a finite
spatial approximation, so the projected matrices are not advertised as an exact
semigroup at fixed grid. Their continuous heat consistency and co-refinement
are separate checks. This differs from run01's cosine truncation, whose coarse
negative kernel entries are retained in its records.

## Execution and comparison

The owner samples folded Gaussian endpoints under the same reflected diffusion
and performs actual reset-mode draws and Bernoulli STOP rewards. It can act
only at the registered decision mesh. Exact endpoint sampling does not sample
continuous first-crossing times or execute a truly continuous stopping policy;
space/time refinement and direct owner returns describe that limitation.

A mode-conditioned stationary threshold family receives the same public x,
mode and recovery-feasibility information. All candidate policies are valued
under the same positive reference before owner outcomes. Its restriction to a
finite stationary family remains explicit. The unrestricted same-law positive
reference is the stronger ordinary control. Agreement with it cannot establish
an exclusive financial-neuron inference or architecture gain.

The four original active-branch parameter derivatives are derivatives of the
original finite-grid numerical map. They do not prove differentiability across
admission dates, hard action changes, continuous free-boundary topology or the
new jump solver, and they do not cover all financial parameters. Full financial
He–Xiong free boundaries, neural content learning, long-distance real multimodal
binding, production ownership, GPU/FP32, energy and adoption remain separate.

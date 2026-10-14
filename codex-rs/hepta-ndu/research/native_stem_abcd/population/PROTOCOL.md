# R4: trainable forward representation and population adjoints

Parent PR #1759, exact source 801c38a4811e9eacffa47f2f37d92e43ddfa76de.
This is an additive research experiment, not a native model promotion. No
historical source, weights, results, CURRENT, main or production owner changes.
The parent integral and numerical workflows passed; parent blocking-ci failed.
None of those statuses establishes acceptance of this new source.

## Why the next experiment is different

R3 largely reduced to one entropic slope. Here actual shared weights determine
the forward evolution of a three-dimensional representation h. Let s=(h,x),
where x is the unchanged raw numeric input, and let p in {0,1} be an observed
preference regime following a known Markov transition matrix. At depth k,

    u_k = K_(k,p) s_k,
    s_(k+1) = F s_k + G u_k + n_p epsilon_(k+1),
    epsilon in {-1,+1}, each probability 1/2.

Thus the effective Stem layer is the upper block of F+G K, not a frozen
encoder with a trained value head. There are 3 depths x2 regimes x3 outputs
x6 state/input coordinates =108 shared trainable weights. They are shared over
all initial states, noise paths and tasks, but are not tied across depth.
Five fixed linear readouts evaluate h_T against independently specified labels
R_m T x. T is a fixed, nonscalar, nondiagonal target map, not fitted output.
These are synthetic linear multitask representations, NOT natural language.

The registered objective is the conditional quadratic special case of NDU:

    U_T = s_T' Q^T_p s_T,
    U_k = s_k' Q_p s_k + u_k' R_p u_k + gamma E[U_(k+1)|s_k,p_k].

Preference changes alter the relative weights on the five tasks. Transition,
noise, costs and external labels are fixed and never optimized. This round is
NOT the nonlinear entropic profile of R3, nor arbitrary endogenous preferences,
a continuous Brownian FBSDE or a viscosity theorem. The discrete martingale
conditional expectations are evaluated exactly, with no sampled TD targets.

The complete training law enumerates all 64 sign combinations of (h,x), scales
h coordinates by 1/4, puts probability 1/2 on either starting regime, and uses
all four (next-regime,noise-sign) branches at every step. There are 128 initial
state/regime cases and 8192 leaf scenarios. Linear-family training uses an EXACT
second-moment reduction, checked against full-tree cost and gradient; it is not
an extra-information oracle. The nonlinear Transformer uses full enumeration.

## Objective, adjoint equations and independent reference

For a FIXED K, backward matrices satisfy

    Pbar_(k,p) = sum_j transition_(p,j) P_(k+1,j),
    A_(k,p) = F + G K_(k,p),
    P_(k,p) = Q_p + K' R_p K + gamma A' Pbar A,
    E_(k,p) = R_p K + gamma G' Pbar A.

Forward unnormalized conditional second moments M_(k,p) satisfy the known
noise/transition recursion. The full population gradient is

    dJ/dK_(k,p) = 2 gamma^k E_(k,p) M_(k,p).

This identity is independently checked against autodiff, finite differences and
full trajectory enumeration. E=0 is sufficient for stationarity; the converse
requires positive-definite conditional M and is checked at the reported model.
C solves all E equations over the actual shared weights simultaneously, rather
than fitting a precomputed value formula. A gradient-root control retains the
M factors to distinguish conditioning/preconditioning from a new objective.

D computes an independent NumPy Riccati solution with positive action Hessians
H=R+gamma G'Pbar G. A separately assembled adapted-action scenario-tree quadratic
program verifies its cost and initial action; it does NOT call the Riccati or
fixed-policy backward routine. Strict convexity in adapted actions and Bellman
completion of squares yield a globally optimal reference for THIS finite LQ
profile, not for arbitrary deep models. No fitted arm may call either reference.

The performance-difference identity gives a positive lower bound on the
objective gap of every per-depth/per-mode scalar controller u=alpha*(x-h),
using just its first decision. Its best initial alpha has a closed quadratic
projection formula. This tests non-scalar reducibility analytically, not merely
by observing a failed scalar optimizer. A diagonal-controller control is also
retained. The reference and lower-bound formulas are real-arithmetic arguments;
reported numbers are ordinary FP64, not outward-rounded interval certificates.

## Frozen runs and evaluation

29 fresh-process runs: matrix Adam/adjoint/L-BFGS/gradient-root and from-scratch
Transformer Adam at seeds 11/23/47, each with nominal 8-second training CPU cap;
matrix Adam/adjoint at 2 seconds for those seeds; scalar and diagonal controllers
with Adam/gradient-root at 8 seconds from seed0; three untrained matrix controls;
one direct reference. Thus 25 fits, three untrained controls, one direct run.
Primary: new-initial-state population objective gap to D, matrix C versus matrix
Adam at 8 seconds, all three seeds. No best-seed, held-out checkpoint or budget
selection. L-BFGS and unpreconditioned gradient-root are mandatory controls.

Eight panels: complete training law, 24 new continuous-valued initial states,
three-times scale, correlated h/x, changed F, changed preference transitions,
three-times noise, and horizon four using a DECLARED modulo-three reuse rule
for every fitted model. D is recomputed for changed problems. The changed-law
and longer-horizon panels are outside the original optimization guarantee.
A new fixed set of seven linear readouts evaluates the final h on each panel;
these are new readout combinations of the same latent target, not unrelated
semantic tasks. Report task MSE AND the resource-sensitive objective, because
the objective-optimal policy need not minimize unpenalized task MSE.

There are no learned probability forecasts in this round; probability calibration
is not replaced with a manufactured score. Branch probabilities are supplied by
the known law. Save final states, all branch probabilities, path costs, origins,
per-initial costs and both task/control metrics before independent scoring.

## Evidence and accounting

Before the efficacy sweep: freeze source hashes, protocol, runs and panels.
Eighteen mathematical/mechanism tests precede the sweep, including one short
training-only solve. An initial test incorrectly required the positive scalar
lower bound to exceed an arbitrary .01; the computed bound was .004206282.
The corrected test checks strict positivity above numerical tolerance. The
original failure log remains; no efficacy outcome or primary threshold changed.
This is local protocol freezing, not external preregistration or blind review.

All runs use one CPU thread in new processes. Count optimizer work, full
Jacobians/AD lanes, cost/gradient calls, data preparation, all predictions,
independent references, serialization and replay. Parent spawn-to-exit CPU/wall
includes imports. An operation may overshoot the CPU cap and its actual duration
is reported. No dummy work for early convergence. Full FLOPs, energy and native
GPU/device peaks remain unknown, not imputed. Tests, audit and publication have
additional costs. No exact time/FLOP or physical research-TCO equivalence claim.

Initial and final weights, all prediction panels and source identities are
sealed before any reference scoring. Independent replay and metric recomputation
must reject incomplete census, changed weights, rehashed false scores and
changed identities. Every failed run stays in the census. Persistent artifacts
are create-only. Existing R1/R2/R3 results and global CI gates remain intact.

Related theory: E, Han and Li, A Mean-Field Optimal Control Formulation of Deep
Learning, https://arxiv.org/abs/1807.01083 . This supplies the population-control
perspective, not a theorem that the present experiment establishes general LLM
superiority. NumPy 2.3.5, SciPy 1.17.0, PyTorch 2.10.0 CPU and Python 3.13 are
pinned for reproducibility, not asserted to be the latest versions.

# R5: nonlinear forward policies and nonquadratic recursive cost

Parent PR #1770, exact commit f8e873e4caebad51f3692bd243a7d83145b15401.
This protocol is pushed before the efficacy sweep. The parent ZIP SHA256
c1a81d9569e2e06550d7e76908c88449afb9a141c754510e52237c55dff0f4da and all
351 member hashes were checked. All prior code/results remain unchanged.
Eighteen development math/mechanism tests and training-only derivative/solver
checks precede this freeze. This is not external preregistration or independent
blind confirmation. No R5 held-out efficacy output has selected this design.

## Mathematical problem

State is (h,x,p), with h,x in R^2 and observed preference regime p in {0,1}.
The primitive plant is affine: h_next=A h+B u+n_p epsilon. Each known binary
branch sets the next observed regime to its branch index. The branch probabilities
are (.7,.3) and (.35,.65); both branches are fully enumerated, not sampled.
The target is a fixed nondiagonal linear transform of x plus .18*(x1*x2,
sin(x1+x2)). Three fixed linear readouts have regime-dependent positive weights.
The finite training law has 16 sign combinations of (h,x), two starting regimes,
three steps, and 256 leaves. New states use seed 2026101451, outside that finite
training law. Complete generator access does not mean every future input was
included in the objective.

Terminal cost is sum_j a_(p,j)*[z_j^2/2+.8*z_j^4/4], with z the readout error.
Local cost is .04*||h||^2/2+r_p*||u||^2/2, r=(.22,.35). The recursive cost is

    Y_node = local_cost + gamma/eta * log sum_b p_b exp(eta Y_child_b),
    gamma=.93, eta=.4.

At eta=0 use the exact conditional expectation limit. The profile is nonlinear
and nonquadratic. It is a known finite-tree entropic-cost NDU special case,
not learned endogenous preferences, arbitrary NDU, continuous Brownian FBSDE
or a viscosity-convergence claim. The binary martingale representation of child
values exists exactly; parameter gradients are not identified with its Z.

## Actual forward representation and methods

The primary nonlinear Stem has 78 parameters: six 2x4 matrices K_(k,p), and a
shared 4->4->2 tanh network with biases W,b,V,c. For s=(h,x),

    raw=K_(k,p)s+V tanh(Ws+b)+c,
    u=2.5*tanh(raw/2.5).

Thus learned parameters directly alter nonlinear recurrent h evolution. No
pretrained encoder, oracle action, fitted reference value, or frozen learned
features enter training. Every layer and shared nonlinear parameter group trains.
The action bound is shared with the independent optimizer and is not silently
removed. Plant coefficients and external success criteria are not trainable.

B uses ordinary reverse-AD Adam (.015); C uses explicit forward/backward costate
gradients plus their exact forward-AD Hessian in trust-exact minimization. The
latter safeguards the local quadratic model by objective-based trust-region
acceptance, not unconstrained stationarity-only promotion. The explicit adjoint
uses risk-tilted recursive branch weights, not physical occupancy in their place.
Both methods minimize exactly the same full-law scalar objective.

Controls: identical trust-exact with ordinary AD gradient/Hessian (adtrust),
full-gradient least-squares root (root), and L-BFGS-B without parameter bounds
(lbfgs). The complete-gradient root may terminate at a saddle or nonzero true
gradient; both are measured. Nonlinear parameter space remains nonconvex.
C is a reduced shared-policy population-adjoint solver, not a universal global
optimizer. Explicit adjoints and AD are equivalent representations of the same
derivative, not different objectives.

All B/C pairs share model class, weights, inputs, objective and nominal CPU cap.
Additional controls are a 48-parameter bounded matrix policy, a six-scalar
policy u=2.5*tanh(alpha_(k,p)*(x-h)/2.5), three untrained nonlinear models, and
three from-scratch two-token Transformer/Adam models. Cross-family capacities
and priors are not matched; a tiny attention baseline is not representative of
all Transformer training. These controls do not exclude every conceivable scalar
parametrization.

## Frozen execution and metrics

Seeds 11/23/47. At 8-second nominal CPU cap run nonlinear Adam/C/adtrust/root/
L-BFGS (15), matrix Adam/C (6), Transformer Adam (3), scalar Adam/root seed11
(2). At 2 seconds run nonlinear Adam/C for all seeds (6). Three untrained
nonlinear controls. Total 35 fresh processes, 32 fitting attempts. No oracle
serves as a warm start, selection criterion or checkpoint target.

Primary: mean new-state recursive-cost regret interval, nonlinear C versus B,
8-second cap, all paired seeds. Report tolerance and bounds rather than calling
negative roundoff a win. Panels: full training law, new states, twice-amplitude
states, correlated h/x, risk-zero-only, stronger-quartic-only, changed-A-only,
and horizon four under explicit modulo-three layer reuse. These shifts are not
pooled as one guarantee. Terminal task MSE and action bound checks are separate
from recursive utility. No learned probability forecast is emitted; probability
calibration is not applicable. Branch probabilities are supplied coefficients.

All candidate weights and full-tree predictions are sealed before ANY held-out
reference solve. No evaluation chooses optimizer, seed, budget or model. Record
true gradient, Hessian minimum and exact objective at final selected weights,
but post-fit diagnostics do not select or repair the candidate. Record every
failed run, optimizer failure, unchanged fit and scientific nonconvergence.

## Independent reference and verification bounds

For each fixed initial state/regime, use a separate NumPy action-tree optimizer
with one two-dimensional action at each preterminal node. With three steps it
has 14 variables; actions are adapted to history, never future branches.
States are affine in this action vector. Positive quadratic/quartic costs and
monotone convex log-sum-exp recursion make this action problem convex. It is a
richer policy reference than the shared neural family, NOT evidence that the
shared family can attain its optimum, and it is recomputed for changed problems.

Use analytic NumPy gradients/Hessians, independent of Torch and the neural
adjoint. At any feasible action vector v with value F(v) and gradient g,

    F(v)-g dot v-U*||g||_1 <= optimum <= F(v), U=2.5.

This is the supporting-hyperplane minimum over the box, so it remains valid in
real arithmetic even when optimization stops early. Report the actual bound
width. Floating-point evaluation is NOT an outward-rounded interval certificate.
Candidate cost minus the reference upper/lower gives lower/upper regret bounds.
Independent finite differences, action feasibility, positive Hessian probes and
candidate/tree-value equality cross-check implementation. A parameter Hessian
is not substituted for the convex action-coordinate argument.

## Resource, lineage and delivery

CPU caps include solver initialization and every objective, gradient, Hessian,
line-search and trust-region operation. A single operation can overshoot; record
actual CPU/wall, AD lanes, selected iterations and whole subprocess overhead.
Periodic Adam history loss is pre-update; never mislabel it as a later selected
weight's loss. Fixed-budget Adam is not a measured first time-to-quality.
Post-fit Hessian checks, prediction, independent reference, serialization,
replay and tests cost additional recorded work. No padding, exact-FLOP, energy,
GPU or full physical TCO claim. Missing measurements stay null.

Files are create-only. Save source hashes, initial and selected arrays, complete
scenario outputs, full failure census and all contrary findings. Independently
reload/recompute, reject rehashed false metrics/identities, and preserve history.
Run under Python 3.13, NumPy 2.3.5, SciPy 1.17.0 and Torch 2.10.0 CPU. No main
merge, selected-model switch, native Q24/Q32 semantics or authority changes.

Implementation references, not efficacy evidence:
https://docs.scipy.org/doc/scipy-1.17.0/reference/optimize.minimize-trustexact.html
https://docs.pytorch.org/docs/2.10/generated/torch.func.jacfwd.html

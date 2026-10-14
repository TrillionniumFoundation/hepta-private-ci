# R3: bounded-derivative integral Stem, frozen protocol

Parent: hepta-private-ci PR #1756 at 50550e6b6625f18d809649c595d595a873ad97e0.
The original nine Python source files and historical outcomes are unchanged.
Parent attachment SHA256 5364a513a42fce964968196a77e6d9c8f41bde1f6a48e22c1420592b94eb9a4f
and all 476 content hashes were verified before reconstructing this CPU source slice.
This protocol precedes the efficacy sweep. Unit/math tests and a one-second
C training-only smoke preceded it; that smoke consumed its cap before an
accepted update. No R3 evaluation result selects this protocol. It is locally
frozen, not external preregistration or an independently blinded trial.

## Native representation

For delta=a-b, define CE_theta=b+integral_0^delta q_theta(rho*s,p) ds.
Take 65 uniformly spaced derivative knots u_j in [-4,4]. A randomly initialized
2->16->1 tanh MLP N_theta has 65 trainable parameters. Define
F_theta(u,z)=[N_theta(u,z)+N_theta(-u,-z)]/2, z=2p-1, and
q_j(p)=sigmoid(logit(p)+u_j F_theta(u_j,2p-1)). The center node is exactly p.
The derivative is LINEAR between nodes and CONSTANT outside the grid. This is
the model definition, not numerical quadrature of an uncomputed neural field.
There is no pretrained encoder, solved-value label, or exact CE expert call in
this model. All 65 parameters enter the shared coefficient network.

The implementation integrates the PWL function analytically: cumulative trapezoid
areas for complete linear segments and a quadratic primitive for the final
partial segment. It integrates q-p away from zero to avoid cancellation when
rho is small, then adds p*a+(1-p)*b. At rho=0 the correction is identically zero.
An explicit strict-tail branch avoids an autodiff double derivative exactly at
|u|=4; derivatives are checked at internal knots, zero, both endpoints and tails.
No final value/probability clipping is used.

For fixed coefficients and any finite parameters, 0<=q<=1. Consequently
partial_a CE=q(rho*(a-b),p), partial_b CE=1-q, giving coordinatewise monotonicity,
translation equivariance, constant consistency, min/max enclosure and sup norm
nonexpansiveness. c+gamma*CE is gamma-Lipschitz. Symmetry of F and the grid gives
q(-u,1-p)=1-q(u,p), hence outcome-exchange invariance. Zero-risk correctness and
probability range are built-in priors, not learned gains. Finite numerical tests
are not interval-certified continuum proofs. Constant tails retain structural
bounds but do not guarantee accuracy beyond the derivative grid.

## Expressivity and a necessary control

The MLP admits F=1 (zero parameters except output bias=1). Then its node values
are exactly samples of the entropic target derivative sigmoid(logit(p)+u).
Thus the old two-temperature-mixture approximation floor does NOT apply to this
family as its grid is refined. This is an explicit entropic inductive prior;
no general NDU/LLM representation theorem is claimed.

For h=8/N and |rho*(a-b)|<=4, linear interpolation of those witness derivatives
has error <=(sqrt(3)/18)*h^2/8, since max|sigmoid''|=sqrt(3)/18. The one-step
value error is <=gamma*|a-b|*(sqrt(3)/18)*h^2/8. The exact integral introduces no
additional real-arithmetic quadrature error. Floating-point rounding and learned
node error remain. The witness is constructive, not a trained model, and all
its computation is retained separately.

A ONE-PARAMETER slope control q_j=sigmoid(logit(p)+kappa*u_j), initially kappa=0,
is fitted with both Adam and TRF. It identifies whether this known entropic
benchmark needs a rich learned representation at all. This is not a same-capacity
primary comparison and must not be omitted if it beats the 65-parameter model.

## Training and frozen comparison

Retain the existing 432-equation full-law residual (12 terminals x12 states x3
depths), with both sides differentiated through tied rollout, and original fit
implementation. No new risk-neutral or held-out training examples. B=Adam and
C=TRF full forward-AD Jacobian optimize identical objectives and initial weights
within each family. C is reduced-space finite-law collocation, not a general
joint policy/Pontryagin solve, learned unknown dynamics, or a viscosity theorem.

Primary: 65-parameter integral C versus integral B on new composed-terminal
RMSE, 64 intervals, nominal 8-second CPU cap, all seeds 11/23/47.
Controls: raw and prior mixture B/C, all three families' L-BFGS, from-scratch
Transformer A, untrained initial models, exact D. Integral B/C also run at two
seconds. Grid16 and grid128 C are seed11-only diagnostics, not another primary
or independently replicated parameter-scaling claim. Scalar Adam/TRF run once
from their fixed zero slope. Total 50 child processes: 40 fits, 9 untrained
controls, 1 direct reference. No warm start or held-out checkpoint selection.

New terminal seeds 2026101431/32/33 generate 32 uniform/composed/indicator
functions. Eleven panels retain R2's ten interventions with NEW terminal bytes,
and add four-times-amplitude tail_spread. Some independent Bernoulli terminal
draws can coincide; overlap counts are disclosed without replacement. New random
seeds are not new independent natural-language domains. Changed dynamics is
supplied equally to all arms, not hidden transition drift. Probability and
single-coefficient changes remain out of the finite training law.

## Evidence and resource accounting

Every run seals initial/final weight arrays and all prediction panels BEFORE
oracle scoring. Separate scalar Decimal-50 and matrix-power references remain.
Report every failure; a timeout cannot become a successful empty result. Retain
raw outputs, references, plans, source hashes, weights, optimization history,
residual/Jacobian/tangent counts, invariant probes, tail fraction, RMSE/max error,
full-domain finite-horizon error envelopes, initial and exogenous-price decisions,
raw/clipped Brier and out-of-range frequencies. Replay from saved weights plus
explicit interval metadata. The original reference is not used in fitting.

CPU caps are checked before residual/Jacobian work; individual nonpreemptible
operations can overshoot. Fresh process startup, imports, training, all AD work,
inference, oracle, audits, serialization and replay are separately metered or
included in whole-child CPU/wall. No dummy work to consume early convergence.
RSS is process peak, not model-only memory. FLOPs/energy/GPU remain null; no
exact-compute-matching, native-host, project-cloud or production claim.

Run from this directory with pinned requirements.txt:

    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m unittest -v
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python integral_sweep.py --out /new/output

Implementation references (version pinned; not efficacy sources):
https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.optimize.least_squares.html
https://docs.pytorch.org/docs/2.10/generated/torch.func.jacfwd.html

# Nonzero-generator Y-coupled continuation experiment

This additive study continues #1550 at `d5b20c7d98d98477b01caa453053138eaef089df`.
It does not change the two historical Encoder question profiles, any original
acceptance reviewer, production owner, selected model or admission requirement.

## Model and exact target of the numerical claim

The continuous motivation is the scalar system

    dX = a Y dt + sigma dW,
    dY = (lambda Y - beta tanh(X)) dt + Z dW,
    X(0)=x0,  Y(T)=tanh(X(T)).

The actual solved object is the full binary discretization with h=T/N,
DeltaW=+-sqrt(h), equal conditional probabilities, and one Y per public prefix:

    X_child = X + a h Y + sigma DeltaW,
    Y = (mean(Y_children) + beta h tanh(X))/(1+lambda h),
    Z = (Y_plus-Y_minus)/(2 sqrt(h)),
    Y_leaf = tanh(X_leaf).

There is real backward-to-forward coupling (a>0), nonlinearity and a nonzero
generator f=beta*tanh(X)-lambda*Y. Diffusion is constant, and f does not depend on
Z. This is not the previous independent-leaf f=0 probability recursion. It is
also NOT the general multidimensional diffusion/Y/Z-coupled NDU problem. All
noise branches are evaluated; individual terminal outcomes cannot be selected as
if known at the root. No action-policy optimality theorem is asserted here.

## A mesh-independent discrete contraction and posterior estimate

All coefficients a,beta,lambda,sigma are nonnegative. Represent internal Y values
as a vector in R^(2^N-1), with supremum norm. Given two candidate vectors and the
SAME binary noise prefixes, explicit forward propagation satisfies

    ||X-X'||_infinity <= a*T*||Y-Y'||_infinity.

The backward sweep B has terminal Lipschitz constant 1 and, since
1+lambda*h>=1 and tanh is 1-Lipschitz,

    ||B(X)-B(X')||_infinity <= (1+beta*T)*||X-X'||_infinity.

Thus Phi=B o forward is a contraction if q=a*T*(1+beta*T)<1. The complete
finite-dimensional space is invariant under this globally defined map; Banach's
theorem gives a UNIQUE solution to this discrete system. For ANY proposed vector
v (including one from a neural network), triangle inequality gives

    ||v-Y*|| <= ||v-Phi(v)|| + q||v-Y*||,
    ||v-Y*|| <= r/(1-q),  r=||v-Phi(v)||.

The corresponding X bound is a*T*r/(1-q). Including terminal values, the Z bound
is max(1,a*T)*r/((1-q)*sqrt(h)). The implemented admission cap is q<0.98, a
conservative registered margin. Its rejection outside this sufficient condition
is NOT proof of nonexistence there. Refining N cannot change q or bypass the cap.

These inequalities are an exact-arithmetic derivation for THIS discretization.
The program computes residuals in ordinary double precision: its displayed bound
is NOT an outward-rounded computer-assisted proof. Neither continuous-time
Brownian discretization error nor observation/model bias is included. In
particular, field-spacing convergence below is at fixed N, not a claim of a
continuous-time convergence rate.

## Local fields and global interfaces

Given u_(k+1), each grid-state x solves the implicit scalar local equation

    y = [mean u_(k+1)(x+a*h*y+-sigma*sqrt(h))
         + beta*h*tanh(x)]/(1+lambda*h).

The continuation Lipschitz envelope obeys

    L_k <= (L_(k+1)+beta*h)/(1+lambda*h-a*h*L_(k+1)).

A positive denominator, bounded iterations, and valid interpolation domain are
required. The local contraction factor is a*h*L_(k+1)/(1+lambda*h). The support
domain expands by a*(1+beta*T)*h+sigma*sqrt(h) each step, sufficient for all
reachable states under the bounded continuation solution. Silent extrapolation is
forbidden; only endpoint floating roundoff up to 1e-12 is tolerated.

The negative control deliberately substitutes tanh at interior boundaries 2 and
4 rather than the actual suffix field. Local roots can be accurate while the
left terminal/right continuation values disagree. The ORIGINAL global residual
is always recomputed, and its corrector cannot accept a small local loss instead.

The independent monolithic oracle imports no solver or field code. It builds
ancestral state sums, the dense analytic Jacobian and a damped Newton solve.
Finite-difference checks validate that Jacobian. This is a high-accuracy floating
reference, not an interval reference.

## Frozen experiment and execution

Two profiles use (T,a,beta,lambda,sigma)=(.8,.55,.5,.2,.3) and (1,.4,.6,.4,.5),
with N=5, x0 in [-.7,0,.45,.85] and spacings .5,.25,.125,.0625,.03125.
All 8 initial-value cases cover their complete 63-node binary trees. Forty grid
approximations, 8 monolithic roots, 8 cold solves and 40 corrected field proposals
are compared. Fields are prepared once per profile/spacing and reused across the
four initial states; the preparation CPU is reported once, never hidden.
Three unsupported q=1.2 cases at N=2,5,10 verify that refinement cannot waive the
same global admission condition. These are controlled mathematical data, not
human language tasks, native Hepta observations or independent future cohorts.

Use the SAME study entrypoint (the historical default remains unchanged):

```sh
PYTHONPATH=qualification/neuron-stem python3 qualification/neuron-stem/fbsde_study.py \
  --profile coupled_nonlinear_v1 --output /new/nonlinear-study
```

Source-head and prospective-merge jobs retain the old exact studies and run this
new profile separately. Green tests do not imply any production qualification.

## Theory context

Fromm and Imkeller, arXiv:1310.0499, study local/global decoupling fields and their
regularity. Han and Long, arXiv:1811.01165, analyze convergence/error estimation
for coupled deep BSDE methods. Their general results provide context, not an
unconditional justification of this implementation. The elementary discrete
contraction above is derived explicitly for the present coefficients.

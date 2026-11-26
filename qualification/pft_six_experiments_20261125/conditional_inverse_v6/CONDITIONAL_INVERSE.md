# Conditional parameter recovery from FBSDE observations

Status: root reviewed conditional results; no new model execution.
Scope: a finite parameter field, explicit observations, a local inverse result,
an exactly solvable coupled FBSDE, and compatible equation aggregation.
This document does not certify the hypotheses for the current Hepta model.

## 1. The unknown and the observation must be specified separately

Choose an open parameter domain U in R^p and fixed basis fields psi_k.
The unknown field is restricted to

\[
\vartheta_a(t,\xi)=\vartheta_{\rm ref}(t,\xi)
                 +\sum_{k=1}^{p}a_k\psi_k(t,\xi),\qquad a\in U.
\]

The basis, reference field, parameter units, model equations, observation rule,
and interventions are known. This is an inverse problem for p coefficients,
not unrestricted recovery of an arbitrary weight tensor or arbitrary field.
If the basis representation is redundant, first select independent coordinates.
If parameter symmetries remain, a result on a chosen local representative
does not recover the original numerical representative of an equivalence class.

For experiment e, consider the declared forward-backward system

\[
\begin{aligned}
dX_t&=b_a^e(t,X_t,Y_t,Z_t)dt+
       \sigma_a^e(t,X_t,Y_t,Z_t)dW_t, & X_0&=x_e,\\
dY_t&=-f_a^e(t,X_t,Y_t,Z_t)dt+Z_t dW_t,
       &Y_{T_e}&=g_a^e(X_{T_e}).
\end{aligned}
\]

Declare whether an observation is an exact expected value, a conditional
expected value at a specified information set, a single random realization,
or a statistic from finitely many realizations. These are different data.
Write the deterministic observation map as F: U -> R^m, for example a vector
of exact expectations under fixed experiment laws. A conditional expectation
is not an observed number unless it has been supplied or estimated.

### Forward assumptions used by the local result

H1. On an augmented Brownian filtration, each declared experiment has exactly
one adapted solution in S^2 x S^2 x H^2 for every a in a neighborhood of a_*.
Here S^2 bounds the expected squared path supremum and H^2 bounds the expected
time integral of squared Z. Coefficients and observation integrals are defined
and integrable throughout that neighborhood, not only at sampled points.

H2. F is continuously differentiable there. One sufficient route is a C^1
solution map into those process spaces followed by bounded linear observation
functionals. That route requires a separate differentiability proof; a finite
stencil, or the mere existence of automatic derivatives, does not supply it.

H3. All p declared coordinates are meaningful after any required symmetry
restriction, and J_* = DF(a_*) has full column rank p.

For a decoupled BSDE with a fixed forward process, square-integrable terminal
data and suitable Lipschitz generator assumptions give the familiar adapted
solution result; see Pardoux and Peng, Theorem 3.1 [S1]. For a fully coupled
system, Lipschitz coefficients alone do not guarantee arbitrary-horizon
solvability. Ma et al. state their scalar integrability and Lipschitz
assumptions in Assumption 2.1; Theorem 6.1 additionally bounds the diffusion's
Z slope and the terminal slope by positive constants c1, c2 with c1*c2 < 1,
and restricts the horizon to a sufficiently small interval [S2]. Neither
result is a theorem identifying an unknown parameter. The explicit family
below proves H1 directly and does not rely on extending those scalar results.

## 2. Local identifiability with a quantitative stability bound

**Proposition 1.** Assume H1-H3. Let s = sigma_min(J_*) > 0. Choose a convex
ball B contained in U such that

\[
\sup_{a\in B}\|DF(a)-J_*\|_2\le\epsilon<s.
\]

Such a sufficiently small ball exists by H2. For all a, a' in B,

\[
(s-\epsilon)\|a-a'\|_2
\le \|F(a)-F(a')\|_2
\le (\|J_*\|_2+\epsilon)\|a-a'\|_2.
\]

Consequently F is one-to-one on B and has a Lipschitz inverse on F(B).

**Proof.** Put h = a-a'. The segment is in B, so

\[
F(a)-F(a')=J_*h+
 \int_0^1[DF(a'+th)-J_*]h\,dt.
\]

The integral has norm at most epsilon*||h||. The smallest singular value
bound and the triangle inequality give both inequalities. This also proves
the inverse's Lipschitz bound 1/(s-epsilon) on the image. No numerical run
or general FBSDE inverse theorem is needed for this elementary argument.

If observed z = F(a_*)+e, ||e|| <= delta, and an estimate a_hat in B has
||F(a_hat)-z|| <= eta, then

\[
\|\widehat a-a_*\|_2\le(\delta+\eta)/(s-\epsilon).
\]

An optimizer whose residual is no larger than the true parameter's residual
has eta <= delta and hence error at most 2*delta/(s-epsilon).
This statement does not assert that every noisy z is in F(B), nor that a
least-squares minimizer is unique. If m > p, nearby ambient data generally
need not belong to the model image. Existence on the image is the precise
inverse existence claim.

Full derivative rank is sufficient, not necessary for injectivity: a -> a^3
is injective near zero despite a zero derivative there. A failed rank test
alone is not a general proof that a nonlinear parameter is unidentifiable.
For an affine observation map, however, full column rank is necessary and
sufficient, as the next result shows.

The inverse function theorem gives a compatible local formulation: apply it
to (J_*^T J_*)^{-1} J_*^T F, whose derivative at a_* is the identity.
The explicit inequalities above state the extra quantitative information and
avoid assuming an inverse onto an open subset of R^m when m > p.

## 3. An exactly solvable coupled FBSDE family

Fix experiment j with deterministic T_j > 0, x_j, kappa_j, sigma_j, and a
known deterministic phi_j in L^2([0,T_j]; R^p). Assume

\[
d_j=1-\kappa_j T_j>0.
\]

The unknown shared a appears in an affine drift field. The system is

\[
\begin{aligned}
dX_t^j&=[Y_t^j+\phi_j(t)^T a]dt+\sigma_j dW_t^j,
       &X_0^j&=x_j,\\
dY_t^j&=Z_t^j dW_t^j,
       &Y_{T_j}^j&=\kappa_j X_{T_j}^j.
\end{aligned}
\]

The forward drift depends on the backward state; the backward terminal
condition depends on the forward state. The zero backward driver is a
declared tractable special case, not a claim about general nonlinear drivers.

Suppress j and define deterministic quantities

\[
D(t)=1-\kappa(T-t),\quad P(t)=\kappa/D(t),\quad
q(t)=\int_t^T\phi(s)ds,\quad r=q(0).
\]

Since D(t) is bounded away from zero, the following processes are defined:

\[
\begin{aligned}
U_t&=D(t)\left[\frac{x+r^Ta}{d}
          +\sigma\int_0^tD(s)^{-1}dW_s\right],\\
X_t&=U_t-q(t)^Ta,\\
Y_t&=P(t)U_t,\qquad Z_t=\kappa\sigma/D(t).
\end{aligned}
\]

**Proposition 2.** These are the unique S^2 x S^2 x H^2 solution, for every
a in R^p. In particular, the family is well posed on the specified horizon.

**Existence proof.** D' = kappa and P' = -P^2. The product rule gives
dU = P U dt + sigma dW and dX = (Y+phi^T a)dt + sigma dW.
It also gives dY = P sigma dW = Z dW. At zero, X_0=x; at T, q(T)=0,
D(T)=1 and P(T)=kappa, so Y_T=kappa X_T. The bounds on D and q and
the square integrability of the stochastic integrals give the stated spaces.

**Uniqueness proof.** For any solution in those spaces, Y is a square-
integrable martingale. Conditioning the integrated forward equation at t
therefore gives

\[
Y_t=\kappa E[X_T\mid\mathcal F_t]
   =\kappa[X_t+(T-t)Y_t+q(t)^Ta].
\]

Thus Y_t = P(t)[X_t+q(t)^Ta]. Substitution makes the forward equation a
linear SDE with bounded deterministic state coefficient and fixed forcing;
its solution is the displayed X. Y is then fixed, and equality of the
stochastic integrals fixes Z up to dt*dP equivalence.

This proof is also a concrete check on why a horizon restriction matters.
For T=kappa=1, sigma=0, phi=0, the same linear equations imply Y_0=x+Y_0.
There is no solution if x != 0; if x=0 there are infinitely many solutions
X_t=c*t, Y_t=c, Z_t=0. Linear Lipschitz coefficients have not prevented
failure at the excluded boundary. We make no necessity claim for d>0
across every other possible special case.

### Endpoint information and exact rank

The observed terminal mean, if supplied exactly, is

\[
\mu_j=E[X_{T_j}^j]=\frac{x_j+r_j^Ta}{d_j}.
\]

Let H have rows r_j^T and define b_j=d_j*mu_j-x_j. Then b=Ha.

**Proposition 3.** With these exact mean observations, the shared parameter
a is uniquely recoverable in R^p if and only if rank(H)=p. If rank(H)=p,
for any positive-definite observation weight W,

\[
a=(H^TWH)^{-1}H^TWb,\qquad
\|\widehat a-a\|_2\le\|\widehat b-b\|_2/\sigma_{\min}(H)
\]

for the ordinary unweighted least-squares reconstruction in the error bound.
If the rank is deficient, every a+v with v in ker(H) gives the same means.

**Proof.** Full column rank makes H^TWH positive definite and the left
inverse recovers a from b=Ha. Conversely, any nonzero null vector creates
distinct compatible parameters. The unweighted error follows from the
operator norm of the left inverse H^dagger.

The backward terminal relation adds no independent information when X_T is
already observed: Y_T=kappa*X_T is a known deterministic transform. Here
Z_t=kappa*sigma/D(t) does not depend on a at all. An exact Y_0 observation
when kappa != 0 supplies the same mean equation, not an additional direction.
The existence of the backward process does not create missing observations.

Changing x_j alone, with the same T and phi, changes only the known offset.
It repeats the same row r^T and cannot increase rank beyond one. Varying
interventions phi_j or their time integrals can produce independent rows.
This is a precise version of the need for informative excitation.

### A closed-form two-parameter example

Take p=2, T_1=T_2=1, kappa_1=kappa_2=1/2, sigma_1=sigma_2=1,
x_1=x_2=0, phi_1(t)=(1,0), and phi_2(t)=(0,1).
Then d_j=1/2, H=I_2, mu_j=2*a_j and

\[
a=(\mu_1/2,\mu_2/2),\quad
Y_0^j=a_j,\quad Z_t^j=\frac{1}{1+t},\quad
X_1^j=2a_j+2\int_0^1\frac{dW_s^j}{1+s}.
\]

Replacing the second intervention by phi_2=(1,0), even with a different
initial state, leaves a_2 unrestricted. These statements are symbolic
calculations from the displayed formulas; no synthetic experiment was run.

### A realized endpoint is not its expectation

For the general family,

\[
X_T=\frac{x+r^Ta}{d}+\xi,\qquad
\xi\sim N\left(0,\sigma^2\int_0^TD(s)^{-2}ds\right)
       =N(0,\sigma^2T/d).
\]

The integral identity also holds at kappa=0, where D=1 and d=1.
After scaling, a single observed endpoint yields
b_obs=r^T a+epsilon with variance sigma^2*T*d.
If sigma != 0 and the noise is unobserved, full rank makes the Gaussian
family statistically identifiable, but does not make a finite noisy sample
an exact parameter recovery. Every parameter has positive likelihood for
every finite real observation vector when the noise covariance is positive
definite. Recording the driving noise would add information beyond endpoints.

With independent repeated paths, n_j sample means have variance
V_j=sigma_j^2*T_j*d_j/n_j after scaling. Assuming all V_j>0, independent
experiments and known variances, the full-rank estimator

\[
\widehat a=(H^TV^{-1}H)^{-1}H^TV^{-1}b_{\rm obs}
\]

is unbiased and has covariance (H^T V^{-1} H)^{-1}. This follows by inserting
b_obs=Ha+epsilon and computing its linear mean and covariance. Correlated
noise requires the full covariance matrix; diagonal weighting would not be
the same likelihood. If sigma=0, use the noiseless exact equations instead
of an inverse of a zero variance. In the two-parameter example, n independent
samples per intervention give coordinate variance 1/(2*n).

## 4. When peers can solve exactly the same objective

Let node i own rows A_i, response vector r_i, and positive-definite local
weight W_i. All nodes use the same parameter coordinates and the same
declared quadratic objective

\[
Q(a)=\tfrac12\sum_i(A_i a-r_i)^T W_i(A_i a-r_i)
     +\tfrac12(a-a_0)^T\Lambda(a-a_0),\quad\Lambda\succeq0.
\]

Each node supplies G_i=A_i^T W_i A_i, h_i=A_i^T W_i r_i and,
if objective values are needed, c_i=r_i^T W_i r_i. A common accepted set of
contributions defines

\[
G=\sum_iG_i+\Lambda,\quad h=\sum_i h_i+\Lambda a_0.
\]

**Proposition 4.** If G is positive definite, every node solving Ga=h from
that same accepted set obtains the unique minimizer of the centralized
objective. Positive definiteness is equivalent to
ker(A_stacked) intersect ker(Lambda) = {0} under the given weights.

**Proof.** Expand Q. Its gradient is Ga-h and its Hessian is G. A positive-
definite Hessian yields the unique minimizer. For any v,
v^TGv=sum_i ||W_i^(1/2) A_i v||^2+||Lambda^(1/2)v||^2, proving the kernel
condition. Exact addition of the same matrices is associative and commutative.

Required compatibility is substantive: the same basis and reference point,
feature/model versions, target semantics, weighting and normalization,
regularizer counted once, and a common contribution set counted exactly
once. Different local linearization points generally describe different
quadratic surrogates. Averaging their locally optimal parameters need not
solve this shared objective. Cross-node covariance terms require additional
statistics or a jointly specified whitening operation.

Exact algebra is distinct from floating-point identity. Reproducible binary
results additionally need a specified summation/solver/rounding protocol;
exact rational arithmetic on declared rational inputs is one option.
The theorem assumes successful authenticated agreement on inputs and does
not prove fault tolerance, privacy, delivery liveness, or peer independence.
Sufficient statistics can still reveal local data. No central solver is
mathematically required once every participating solver has the same inputs.

If Lambda is positive definite while A_stacked is rank deficient, the
regularizer selects a unique optimizer. It has not supplied missing evidence
about the true a. Replacing a nonlinear problem by a local quadratic also
requires an independent check on the resulting nonlinear candidate.

## 5. Admission against the actual Hepta evidence

The frozen V5 engineering evidence establishes finite stencil checks,
equation agreement, one accepted nonlinear trial and cold identity within
their stated scopes. It does not establish H1-H3 on a neighborhood.

| Requirement | Current conclusion |
| --- | --- |
| Exact FBSDE coefficient/observation correspondence for the implementation | Unproved; a numerical HCSN routine is not automatically this continuous system. |
| Unique adapted solution throughout the claimed parameter domain | Unproved for the proposed Hepta inverse formulation. |
| C^1 observation map and derivative variation bound on a ball | Unproved. Original parent finite-stencil failure remains; a later finite-point pass does not prove the hypothesis. |
| Full rank in six declared local coordinates | The retained affine surrogate has two rows and rank two, leaving a four-dimensional data nullspace. |
| Actual peer candidate's own finite-stencil gate | Not executed; the central candidate's pass cannot transfer by similar outputs. |
| Independent real-user generalization and old-task retention | Not consequences of any proposition above and remain empirical gates. |
| Exact common quadratic equations | Bounded V5 peer agreement supports its own declared two-row instance, not arbitrary learned representations. |

The pinned execution source is available for this audit at
discovery/retention_v6/original_model.py, 20658 bytes, with SHA256
aabc7a29ebfdaed592ebd4a16d7e4db927a6a88cb7247d4b334fd7299eab8576.
It defines clipping in _symmetric_clip, piecewise deposition using abs in
_deposit, and an explicitly nonsmooth _remap. The raw_cost parameter itself
enters the cost through tanh(raw_cost + 0.15*drive), not through abs(raw_cost).
These source facts preclude simply assuming global smoothness; they do not
identify which operation caused the original coordinate's stencil failure.
The latter remains an observed result with no stronger causal attribution.
An earlier audit copy has a different SHA256, d553eadb..., and was excluded
from claims about the executed source.

The universal endpoint-only claim remains refuted by
f_(a1,a2)(x1,x2)=a1*x1+a2*x2: observing (1,0)->1 permits every (1,c), while
(0,1) maps to c. Rewriting these same constraints as boundary conditions
does not remove that freedom.

## 6. Precisely closed and still-open claims

Following root proof review, Propositions 1-4 resolve the mathematical
questions for the stated finite-dimensional observation model and explicit
coupled family. They supply a complete conditional example of parameter
recovery and decentralized equation combination, including a noise model.
They do not establish a new general theorem or a priority claim.

This assessment is scoped to the frozen V5 evidence. A separately admitted V6
candidate retention measurement does not alter these proof assumptions.

The application claim, "the current Hepta implementation satisfies these
hypotheses and can infer its parameter field from the proposed user data,"
remains open. The broader questions about independent adoption, retention,
architecture gains, learned connections, foundation-scale representations,
and total training cost also remain open. Their status cannot be changed by
relabeling this explicit special case as a proof for the implementation.

## Sources and verification boundaries

[S1] E. Pardoux and S. G. Peng (1990), *Adapted solution of a backward
stochastic differential equation*, Systems & Control Letters 14, 55-61.
Author-hosted PDF: https://www.i2m.univ-amu.fr/perso/etienne.pardoux/_media/papeng1.pdf
DOI: https://doi.org/10.1016/0167-6911(90)90082-6
Theorem 3.1 and assumptions (3.2) were visually inspected on printed page 58.
The paper's own sign and diffusion conventions should be preserved when
applying it; it is cited here only for fixed-coefficient adapted solvability.

[S2] J. Ma, Z. Wu, D. Zhang, and J. Zhang (2015), *On well-posedness of
forward-backward SDEs: a unified approach*, Annals of Applied Probability
25(4), 2168-2214. https://arxiv.org/abs/1110.4658v2
Full text: https://arxiv.org/pdf/1110.4658v2
DOI: https://doi.org/10.1214/14-AAP1046
Assumption 2.1, Definition 2.2, Theorem 2.3 and Theorem 6.1 were inspected.
The paper explicitly works with scalar processes; no multidimensional
extension or parameter-identification result is inferred from it here.

[S3] S. Peng and Z. Wu (1999), *Fully coupled forward-backward stochastic
differential equations and applications to optimal control*, SIAM Journal
on Control and Optimization 37(3), 825-843.
https://epubs.siam.org/doi/10.1137/S0363012996313549
The publisher abstract and bibliographic record were verified. Its full
monotonicity theorem was not obtained from that page, so no uninspected
coefficient assumption is imported into these propositions.

All inverse bounds, formulas for the explicit family, noise covariances,
rank equivalences and aggregation arguments above are derived in this note.
The source citations supply background boundaries, not a claimed published
proof that current Hepta weights have been recovered.

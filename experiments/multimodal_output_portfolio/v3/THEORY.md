# Finite feedback control: guarantees and boundaries

This document defines the v3 mathematical mechanisms. The claims below apply
to the stated finite models and synthetic preference experiment. They do not
establish a general HEPTA FBSDE solver, identify a real user's preferences, or
guarantee robustness to unspecified distribution shifts. v1/v2 remain frozen.

## 1. A finite, history-rectangular objective

Fix a finite horizon T. A public state h includes all observed source reports,
the currently observable generation state and feedback, remaining budget, time,
and an exogenous preference profile. It excludes truth labels, unrevealed
verifier results, future innovations, and their random seed. A history can be
used directly when a smaller state has not been proved sufficient. A finite
innovation bank and a bounded number of refinements produce a finite history
tree even when each latent vector has real-valued coordinates.

For each feasible action a, declare a nonempty collection of conditional laws

\[
\mathcal P_{h,a}=\operatorname{conv}\{p^1_{h,a},\ldots,p^K_{h,a}\}.
\]

Nature can select a law separately at every public history/action. The set of
admissible path laws is the product of these conditional sets, including their
history-dependent pastings. This is the **rectangular** uncertainty model.
Classical robust DP requires a corresponding independence of row choices;
Nilim and El Ghaoui state this assumption explicitly and distinguish fixed from
time-varying uncertainty [1, sections 2.2 and 3]. The following entropic
specialization and its finite tests are our construction.

Use utility, so larger is better:

\[
C_\gamma^p(x)=
\begin{cases}
-\gamma^{-1}\log\sum_i p_i e^{-\gamma x_i},&\gamma>0,\\
\sum_i p_i x_i,&\gamma=0,
\end{cases}
\qquad R_{h,a}(x)=\min_{p\in\mathcal P_{h,a}}C_\gamma^p(x).
\]

The Bellman equation implemented by `rectangular_bellman` is

\[
V_T(h)=\Phi(h),\qquad
V_t(h)=\max_{a\in A(h)} R_{h,a}
\bigl(r(h,a,h')+V_{t+1}(h')\bigr).
\]

Costs enter r with a negative sign and must also constrain A(h). The generic
solver does not invent a feasible action when none is supplied. A caller that
requires complete four-modality emission must encode its minimum cost and seal
contract explicitly. A STOP terminal utility may itself be a robust CE over
unobserved truth under public conditional laws. Terminal truth is a random
variable in this calculation, not an observed controller input.

**Finite optimality.** CE is increasing in each component and commutes with
addition of a deterministic scalar. At the final decision, enumerating actions
and Nature's laws is exact. If all children have optimal continuation values,
monotonicity and the independent availability of Nature's law at each child
allow their substitution at the parent. Backward induction proves the recursion
optimal for this finite rectangular game. The implementation uses floating
arithmetic and first-in-order ties; it does not promise exact real arithmetic or
optimality for continuous neural parameters.

For positive gamma, minimizing CE over p is equivalent to maximizing the linear
quantity sum p_i exp(-gamma x_i). Therefore one of the listed laws attains the
minimum over their convex hull. At gamma zero the same conclusion follows from
linearity. `robust_ce` can return the minimizing row for a reviewable receipt.
The tests also enumerate complete controller and Nature strategies and evaluate
their terminal distributions independently of the Bellman implementation.

## 2. Dependence shifts and the cost of rectangularization

Let P_k(Y, R_1, ..., R_m) be frozen calibration regimes. For an observed history
H, `conditional_rows` computes P_k(target | H), retaining only regimes with
P_k(H)>0. This uses full joint laws, not a product of estimated marginals.
If every regime assigns H zero mass, the function rejects the history. A
deployment that needs broader support must predeclare a support-expansion model;
it cannot silently reinterpret an impossible event or consult its test label.

The family of conditionals is then rectangularized. It no longer requires the
same k to be used throughout an episode. Its guarantee is conditional on the
true transition kernels lying in the declared envelope at every relevant
history. There is no guarantee for arbitrary out-of-envelope shifts, an
incorrect observation likelihood, or an omitted common failure cause.

This conservatism can be strict. A fair first branch goes left or right. Regime
A pays (0,1) in those branches and regime B pays (1,0). Either single fixed
regime gives CE of a fair {0,1} lottery. The rectangle can choose A after left
and B after right, obtaining zero on both branches. The unit test verifies this
gap; a rectangular value must not be reported as the exact value under one
fixed unknown regime.

A separate test uses the binary joint laws assigning mass 1/2 to (0,0),(1,1)
or to (0,1),(1,0). Both marginals are identical; covariances are +1/4 and -1/4.
Their conditional laws differ after the first report. This verifies a genuine
dependence change. Reweighting a three-point, one-direction latent innovation
bank changes its dispersion but does not, by itself, demonstrate a
same-marginal/different-covariance multimodal shift.

## 3. The shared-wrong information boundary

Consider eight possible truths Y and a common observed report W. In the
explicit symmetric shared-wrong model,

\[
P(Y=y,W=w)=\frac{\mathbf 1\{y\ne w\}}{56}.
\]

Suppose every available input payload is generated from W and additional noise
independent of Y conditional on W. Then P(Y=y | all available inputs) is uniform
over the seven labels other than W. For every randomized controller based only
on those inputs, conditional classification accuracy is at most 1/7. Formally,
sum_y q(y | H) P(Y=y | H) is bounded by max_y P(Y=y | H). Decoding, verification
against the same information, or repeatedly querying the same corrupted
sources cannot increase this bound.

The numerical 1/7 bound requires the stated symmetry and information condition.
It is not a theorem for every distribution named `shared_wrong`. In particular,
side information or unequal conditional truth probabilities change the bound.
The test also constructs a clean world P(Y=W)=1 with the same uniform observed
W distribution. No procedure seeing only W can distinguish those two worlds.
This does **not** say that arbitrary noisy IID and common-cause regimes have
identical full observation distributions: disagreements across many samples
can distinguish some such regimes.

An independent verifier can change the information set. If its response R has
a calibrated channel P(R | Y,H) that differs across truths remaining possible
after H, then I(Y;R | H) can be positive. Conditional independence of R from the
corrupted inputs given Y is a useful sufficient design condition together with
an informative channel. Posterior updating uses the channel and observed R,
never the held-out Y directly. A perfect verifier gives accuracy one in the
constructed test, but that is an explicitly new information source. It needs a
declared cost and feasibility condition. It is not a solution using the
original information set, and a simulated perfect verifier is not evidence
that an equally reliable real verifier exists.

## 4. A narrow identifiable preference experiment

Each externally randomized pair contains Gaussian lotteries A and B in fixed
external utility units, with declared means and variances. The Gaussian
exponential moment gives C_gamma(A)=mu_A-gamma*var_A/2 exactly. The synthetic
choice model, a specified paired-comparison logistic model [2], is

\[
P(A\succ B\mid\gamma)=\operatorname{sigmoid}(o_i+\gamma x_i),
\quad o_i=(\mu_A-\mu_B)/\tau,
\quad x_i=-(v_A-v_B)/(2\tau).
\]

Temperature tau is fixed and known. Only gamma in a declared compact interval
is fitted. The negative log likelihood is convex; its derivative and Fisher
information are

\[
\ell'(\gamma)=\sum_i x_i(p_i-y_i),\qquad
I(\gamma)=\sum_i x_i^2p_i(1-p_i).
\]

A nonzero variance contrast makes the parameter-to-choice-distribution map
injective under these assumptions. Bisection on the monotone score or a bound
gives the global bounded MLE. Equal-variance pairs give zero information and
are rejected for fitting. Small information, numerical saturation, and a
boundary solution are recorded separately; structural identifiability does not
imply accurate finite-sample estimation. The reported inverse-square-root
information is an asymptotic local standard error, not a boundary-valid
confidence interval or a model-correctness certificate.

Fixed scale matters: multiplying payoffs by c, replacing gamma by gamma/c, and
temperature by c*tau preserves choice probabilities. The test verifies this
confounding. We do not simultaneously learn all three quantities.

Design seeds, response seeds, profiles, bounds, and utility units must be fixed
before confirmation. Training choices fit gamma; independent choices assess
log loss and Brier score with gamma frozen. Task truth labels and held-out
generation losses are absent from this API. The learned coefficient can be
plugged into the same declared task utility, but it does not identify real
human preferences or validate Gaussian/logistic assumptions for people.

## 5. A tested entropic BSDE special case, not a general solver

The dynamic entropic risk measure and its quadratic BSDE are stated in [3,
section 2.2.1]. We use the opposite sign, **utility**, and verify this explicit
case with terminal X_T=mu+sigma*W_T:

\[
U_t=\mu+\sigma W_t-\tfrac12\gamma\sigma^2(T-t),\qquad Z_t=\sigma,
\]

\[
dU_t=\tfrac12\gamma Z_t^2dt+Z_t\,dW_t,\quad U_T=X_T,
\qquad f(z)=-\tfrac12\gamma z^2
\]

under the convention dU=-f dt+Z dW. Gaussian exponential moments are finite;
the formula is directly checked by Ito's rule. This is a decoupled forward
Brownian model with an analytic backward solution. It is not a learned solution
of an arbitrary terminal condition, quadratic generator, or coupled forward
and backward system.

For a fair binomial increment Delta W=+/-sqrt(dt), the exact discrete step uses
U=C_gamma(U_next), Z=(U_up-U_down)/(2 sqrt(dt)), and
f_dt=(U-E[U_next])/dt. It satisfies U_next=U-f_dt*dt+Z*Delta W exactly. For bounded
Z, f_dt tends to -gamma*Z^2/2 as dt decreases. Tests check the decomposition,
the convergence rate, and an independent Gaussian quadrature evaluation.

Z is the coefficient of a martingale increment. For example,
dU/dsigma=W_t-gamma*sigma*(T-t), which differs from Z=sigma. The unit test checks
this numerically. Differentiating a neural generator's selected policy value
is a parameter derivative and must not be relabeled Z. Policy, worst-law, or
clamp ties also create nonsmooth points; no global neural-training convergence
result follows from finite Bellman optimality.

## Primary references

1. Arnab Nilim and Laurent El Ghaoui (2005), *Robust Control of Markov Decision
   Processes with Uncertain Transition Matrices*, Operations Research 53(5),
   780–798. [Author-hosted original paper](https://people.eecs.berkeley.edu/~elghaoui/Pubs/RobMDP_OR2005.pdf).
2. Ralph Allan Bradley and Milton E. Terry (1952), *Rank Analysis of Incomplete
   Block Designs: I. The Method of Paired Comparisons*, Biometrika 39(3/4),
   324–345. [Publisher record](https://academic.oup.com/biomet/article-abstract/39/3-4/324/326091).
   The Gaussian-lottery one-parameter restriction and its identification proof
   above are our specified model, not a claim made by that paper.
3. Nacira Agram, Jan Rems, and Emanuela Rosazza Gianin, *SIG-BSDE for Dynamic
   Risk Measures*, arXiv:2408.02853, section 2.2.1 and its Brownian example.
   [Author preprint](https://arxiv.org/html/2408.02853v1).
   Our module implements the analytic check only, not that paper's SIG-BSDE
   algorithm or its convergence theorem.

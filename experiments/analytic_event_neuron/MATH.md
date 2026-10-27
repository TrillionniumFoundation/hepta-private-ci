# Analytic terminal-event operator: mathematical contract

This file describes the implemented FP64 reference in `analytic.py`, not a
theorem that an entire Hepta policy, neural network or production runtime obeys
a Gaussian diffusion. Mathematical identities below are derived for the stated
model. Empirical qualification is a separate result.

## 1. State, time and observable events

Let the current latent state have conditional law

\[
X_t\mid\mathcal H_t\sim N(m_t,v_t),\quad v_t\geq0.
\]

For a specified duration \(\tau\geq0\), assume constant drift \(b\), diffusion
\(\sigma\geq0\), and future Brownian increments independent of \(\mathcal H_t\):

\[
X_{t+\tau}=X_t+b\tau+\sigma\sqrt\tau Z,
\qquad Z\sim N(0,1).
\]

Then the exact conditional mean and variance are

\[
m=m_t+b\tau,\qquad v=v_t+\sigma^2\tau.
\]

`gaussian_transition` implements this identity, rejecting negative durations,
negative variances, negative diffusion coefficients, nonfinite inputs and
unrepresentable outputs. It does not estimate these parameters from data.
Thresholds and observations must use the same state units; diffusion has state
units divided by square-root time. A learned state-dependent coefficient placed
in this formula is a locally frozen model, with a separate model-error budget.

The three mutually exclusive output channels are ordered **put, neutral, call**:

\[
E_- =\{X_{t+\tau}\leq\kappa_-\},\quad
E_0 =\{\kappa_-<X_{t+\tau}\leq\kappa_+\},\quad
E_+ =\{X_{t+\tau}>\kappa_+\},\qquad \kappa_-\leq\kappa_+.
\]

With \(a=(\kappa_--m)/\sqrt v\), \(c=(\kappa_+-m)/\sqrt v\) and \(v>0\),

\[
(p_-,p_0,p_+)=(\Phi(a),\Phi(c)-\Phi(a),\Phi(-c)).
\]

These probabilities sum to one because the events partition the real line.
At zero variance, the implemented distribution is an atom at \(m\), and the
inequalities above remain exact. An atom on the lower threshold belongs to put;
an atom on the upper threshold belongs to neutral unless both thresholds agree.
Equal thresholds provide a binary put/call partition with zero neutral mass.

Neutral is an observed terminal interval, not missing input, unavailable model,
an unobserved outcome, a cancelled operation, or a policy's decision to abstain.
Those conditions require separate typed records. A sample of the three events
must be a single categorical draw or one shared latent-state draw. Independently
sampling complementary call and put would define a different stochastic model.

## 2. Digital option interpretation and identifiability

Under constant Black--Scholes parameters, put and call cash-or-nothing prices
are respectively \(Ae^{-r\tau}\Phi(-d_2)\) and
\(Ae^{-r\tau}\Phi(d_2)\), where
\(d_2=[\log(S/K)+(r-q-\sigma^2/2)\tau]/(\sigma\sqrt\tau)\).
After removing discount and amplitude, these are the binary special case above.
The experiment models an explicitly specified task law; it does not import a
risk-neutral financial probability as an empirical task probability.

For fixed horizon and scale, \(\Phi((w^Tx+c-\kappa+b\tau)/(\sigma\sqrt\tau))\)
is exactly a probit affine unit. Redundant affine/threshold/scale parameters do
not add a new function class. The validation includes this negative control.
An optimizer in different coordinates may follow a different path; output
equivalence is not a claim that untransformed optimizer trajectories coincide.

## 3. Derivatives and their domain

Writing \(\phi\) for the standard normal density,

\[
\partial_m(p_-,p_0,p_+)
=\frac1{\sqrt v}(-\phi(a),\phi(a)-\phi(c),\phi(c)),
\]

\[
\partial_v(p_-,p_0,p_+)
=\frac1{2v}(-a\phi(a),a\phi(a)-c\phi(c),c\phi(c)).
\]

At infinite interval endpoints, \(z\phi(z)\) means its limiting value zero.
Drift, diffusion and time chain rules follow from
\(\partial_b m=\tau\), \(\partial_\sigma v=2\sigma\tau\),
\(\partial_\tau m=b\), and \(\partial_\tau v=\sigma^2\).
Here drift is an independent task parameter. The coupled financial drift
\(b=r-q-\sigma^2/2\) would require its extra derivative.

`event_gradients` rejects zero variance and any unrepresentable derivative.
There is no smooth ordinary derivative of the degenerate threshold model at its
jump. For a binary event the peak mean derivative is
\(1/\sqrt{2\pi v}\); numerical and learning regularity deteriorate as \(v\to0\).
Gradients of continuous event probabilities do not automatically differentiate
a sampled spike, latent reset, or the full discrete deployment objective.

## 4. Numerical evaluation and encoding

Put and call tails use separate log-CDF evaluations. Neutral mass uses stable
same-tail log subtraction and `expm1`; an interval straddling zero uses `erf`.
For narrow standardized intervals, a symmetric local density integral avoids
loss of relative precision from subtracting nearly equal CDFs:

\[
\Pr(a<Z\leq c)=w\phi(z)\left[1+
\frac{(z^2-1)w^2}{24}+
\frac{(z^4-6z^2+3)w^4}{1920}+O((1+|z|)^6w^6)\right],
\]

where \(w=c-a\), \(z=(a+c)/2\), used only when
\(w(1+|z|)\leq10^{-3}\). This is a numerical evaluation choice, not a different
probability model. Impossible events retain log probability minus infinity.
Far-tail FP64 probabilities may underflow to zero while log probabilities remain
finite; no artificial epsilon floor converts them into calibrated probabilities.

`quantize_simplex` uses largest-remainder encoding after removing only accepted
FP64 row-sum roundoff. Nonnegative integer channels sum exactly to \(2^{24}\),
with deterministic channel-order ties and approximately one-unit component error.
This encodes a probability vector; it does not authorize an action or calibrate
runtime confidence. Independent scalar rounding is deliberately not used.

## 5. Positive propagation and time composition

For ordered full-line bins \(I_j=(e_j,e_{j+1}]\), including infinite tails,
define \(K_{ij}=\Pr(X_{t+\tau}\in I_j\mid X_t=x_i)\). Then

\[
K_{ij}\geq0,\quad \sum_jK_{ij}=1,\quad
\|Kv-Kw\|_\infty\leq\|v-w\|_\infty.
\]

The last inequality follows from
\(|\sum_jK_{ij}(v_j-w_j)|\leq\sum_jK_{ij}\|v-w\|_\infty\).
This provides positive, monotone, nonexpansive propagation of a piecewise-constant
continuation. General continuation reconstruction and boundary truncation require
their own approximation errors.

For one fixed drift and diffusion, independent Gaussian increments give
\(P_sP_t=P_{s+t}\). The independent quadrature test verifies this continuous-law
identity. Applying a finite-bin matrix twice inserts a representative-state
projection; its discrepancy is recorded separately and is not called an exact
semigroup. Reset, refractory state, intermediate observations and changed actions
also change the transition. Multiple horizons on one trajectory share randomness
and are not independent evidence rows.

## 6. Endpoint versus first passage

For \(x<k\), constant drift/diffusion and \(d=k-x\), the probability of first
hitting an upper boundary by \(\tau>0\) is

\[
\Phi\!\left(\frac{b\tau-d}{\sigma\sqrt\tau}\right)
+e^{2bd/\sigma^2}
\Phi\!\left(\frac{-b\tau-d}{\sigma\sqrt\tau}\right).
\]

`first_passage_upper` is a separate semantic fixture with no reset. With zero
drift it is twice the terminal upper-tail probability, furnishing a counterexample
to any endpoint/first-passage conflation. It is not the model used by the first
terminal-event training experiment.

## 7. Verification and source relationship

Run `python -m experiments.analytic_event_neuron.reference --output <path>`.
The output binds both executable source SHA-256 values and environment versions.
The density-quadrature oracle does not call a CDF; it splits intervals around the
normal-density peak to avoid the known numerical failure of an unsplit wide
improper integral. Extreme tails use a rescaled positive integral.

The Hölder--Bellman connection is that a digital event is \(P_\tau H_\kappa\).
That observation alone does not establish low separation rank, sampled learning
convergence, Hepta policy superiority, or the regularity of a reset process.
The original step payoff is discontinuous, while its positive-time Gaussian
convolution is smooth with constants that deteriorate near zero time.

Background sources:

- https://people.duke.edu/~wbm5/documents/mfeformulasheet.pdf (cash binary formulas)
- https://arxiv.org/html/2606.16846v1 (diffusion Bellman target regularity)
- https://arxiv.org/abs/2404.14964 (probabilistic and surrogate spike gradients)

These sources motivate the research. The formulas, independent checks and their
declared finite precision scope above describe this implementation's own evidence.

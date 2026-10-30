# Mathematical scope of the regenerative value layer

This post-confirmation review explains the mathematical claims made by the
frozen implementation. It changes no training source, fitted model, protocol,
seed, threshold, or confirmation result. The controlling source/model freeze is
`a06e545d1c248d879c6e85d36b8bb4a375269ad3`; complete confirmation evidence is at
`c71bdb0583d3265b931b31579d6bf3a9b85691d3`.

## 1. Canonical states and the time-zero entrance convention

The active state is a strictly positive distance from a lower absorbing barrier.
A refractory state records remaining holding time in `(0, a]` and its reset
distance. At release the state is the active reset point. A supplied active
distance of zero is an entrance instruction: emit the initial event, reset, and
enter a full refractory hold before applying the elapsed-time branch.

Consequently, `P_0` is the identity on canonical states. It is a normalization
map on the extra, unnormalized zero-distance entrance representation. Claiming
the identity on that representation would contradict the implemented initial
atom. Likewise, a refractory duration exactly equal to the propagation horizon
releases at the endpoint; it is not an extra positive holding interval.

On canonical states, first-hit absorption followed by the declared reset and
hold defines a time-homogeneous Markov process. Strong Markov restarting gives
the regenerative semigroup. Mandatory positive holding time bounds the number
of completed reset cycles in any finite horizon. The killed Brownian kernel and
first-hit law reduce the finite renewal terms analytically; the retained
independent integral and semigroup comparisons validate selected cases.

This state contract is distinct from an observation contract. Missing an
observation supplies no survival evidence. The current control experiments use
known public states and laws; they do not implement a learned posterior filter.

## 2. What the learned operator preserves

For each fixed context, the transition head has nonnegative entries summing to
one. Therefore its action on a bounded vector of bin values is positive,
constant preserving, and nonexpansive in the sup norm. With fixed discount
`gamma = exp(-q dt)`, a discrete Bellman backup with a common legal action set
obeys

\[
 \|\widehat T V-\widehat T W\|_\infty
 \leq \sup_{s,a}\gamma(s,a)\,\|V-W\|_\infty.
\]

It is a strict contraction only when the right-hand coefficient is less than
one, for example under a positive discount and a uniform positive decision
interval. The `q=0` finite-horizon experiment has backward finite-horizon
recursion, not a strict discounted-contraction certificate.

These structural facts do not bound the learned transition error. Three seeds
pass the registered *mean* error gates; retained maximum total-variation errors
are about 0.51 to 0.59. No uniform operator approximation bound follows.

The exact transition-bin reference integrates bin mass exactly, but replacing
the continuation inside a bin by its representative-point value is a separate
projection. Its finite-bin dynamic program is not an exact continuous-state
oracle. The moment branch is linear in the supplied payoff coefficients; this
does not make the nonlinear context encoder an exact semigroup.

## 3. Regularity and the connection to Holder-space analysis

Brownian ellipticity supplies interior parabolic smoothing for the appropriate
killed equation. Absorption, reset, deterministic refractory motion and initial
atoms add boundary and transmission conditions. Continuity across refractory
release requires compatible traces, such as a refractory terminal payoff at
zero remaining hold equaling the active payoff at the reset point. An entrance
event reward adds its own value-matching term at the absorbing boundary.

Arbitrary discontinuous terminal bins need not satisfy these compatibility
conditions. The current learned trunk is not constrained to match its active
and refractory traces at every seam, and finite validation does not prove a
global Holder estimate. Positive transition weights alone imply neither a
Holder regularity bound nor a learned semigroup law. A rigorous extension of
the analysis must state the hybrid domain, compatible function space, boundary
traces, and uniform approximation assumptions explicitly.

The relevant theoretical comparison is the operator and regularity viewpoint
in [Qi, *Deep Q-Learning on Holder Spaces*](https://proceedings.mlr.press/v336/qi26a.html).
Its ellipticity and approximation hypotheses cannot be transferred merely by
renaming this architecture. In particular, neither that comparison nor the
present tests prove convergence of practical sampled deep Q-learning.

## 4. Global verification of the stated scalar natural-firing boundary

Consider an active voltage `dX = mu dt + sigma dW`, with `sigma > 0`, discount
`q > 0`, reset voltage `r`, mandatory hold `a > 0`, and reward `x-c` on firing,
where `c >= r`. Running and refractory rewards are zero. After holding, the
state restarts at `r`. Policies may choose stopping times adapted to the
voltage filtration, subject to the same reset and mandatory hold.

Define

\[
 \lambda=\frac{\sqrt{\mu^2+2q\sigma^2}-\mu}{\sigma^2}>0,
 \qquad \beta=e^{-qa}\in(0,1).
\]

The unique threshold `b > c` solves

\[
 g(b)=\lambda(b-c)-1+\beta e^{-\lambda(b-r)}=0.
\]

Indeed, `g(c)<0`, `g(b)` tends to infinity, and
`g'(b)=lambda(1-beta exp(-lambda(b-r)))>0` for `b>=r`.
Let `C=exp(-lambda(b-r))/lambda`. The candidate is

\[
 V_A(x)=\begin{cases}
 C e^{\lambda(x-r)}, &x<b,\\
 x-c+\beta C, &x\geq b,
 \end{cases}
 \qquad V_R(\eta)=e^{-q\eta}C.
\]

Value matching gives `V_A(b)=1/lambda`; the derivative from each side is one.
In the continuation region the generator equation holds because
`sigma^2 lambda^2/2 + mu lambda = q`. The exponential lies above its tangent,
so `V_A(x) >= x-c+beta C`, with strict inequality below `b`. In the firing
region,

\[
 (\mathcal L-q)V_A(x)
 =\mu-q(x-c+\beta C)
 \leq\mu-q/\lambda=-\sigma^2\lambda/2<0.
\]

The refractory equation is `-partial_eta V_R-q V_R=0`, with release trace
`V_R(0)=V_A(r)`. Thus the continuation equation, stopping obstacle, value
matching and smooth fit all hold. The nonnegative candidate grows at most
linearly above and is bounded below the threshold. Discounted Brownian moment
bounds give the terminal transversality limit. Localized Ito verification and
iteration over resets bound every admissible expected reward by the candidate.
The threshold policy attains equality. Positive refractory time excludes
accumulation of firing times in a finite horizon. These facts establish a
global optimum for this scalar regenerative impulse problem.

They do not establish an optimum for finite deadlines, input-dependent laws,
partial observations, nonlinear rewards, coupled neurons, or native NDU action
constraints. Those variants have different value equations and boundaries.
The independent QVI refinement and implicit-gradient comparisons in the frozen
package test the declared scalar case rather than certifying those extensions.

## 5. Training and empirical scope

The multilayer model samples the declared segmented stochastic process in the
forward pass, including repeat hits and residual holds. Its conditional-moment
straight-through backward rule is biased. Analytic gradients of a probability
or continuation operator are not automatically pathwise gradients through a
sampled spike and all subsequent resets.

All 55 active parameters changed in all 27 fits, including dynamics, thresholds
and resets. That establishes joint training, not training-estimator correctness
or cross-task advantage. All six registered superiority gates failed. Any
architecture revision needs a distinct development study and fresh confirmation
data; the published confirmation cannot become an undisclosed tuning set.

The NDU evaluation retains the original scalar-Q32 recursive utility contract
and verifies realized downstream rewards and legal action costs. The empirical
results are mixed across laws. A successful fixed-point receipt does not certify
optimal control or production authority; `DENY_ALL` and the false safety
certificate remain explicit.

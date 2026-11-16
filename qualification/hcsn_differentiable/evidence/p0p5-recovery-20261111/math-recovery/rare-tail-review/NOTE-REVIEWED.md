# A finite generator does not by itself qualify rare first-hit tails

## Status and source scope

This is a new mathematical note written after the scratch reset on
2026-11-11. The earlier uncommitted draft and its incomplete review did not
survive as complete source bytes. This note is not a reconstruction of their
original hash. No model, training posterior, numerical oracle, scalar sweep or
new physical-parameter experiment was executed for this note.

The retained source context is the fixed-grid diagnosis and the exact operator
snapshot already committed in the terminal numerical appendix. Those records
separate source-cell quadrature, repeated projection, remaining-time transport
and loss of tail shape. This note addresses a different question: which of
those problems a finite, time-homogeneous Markov generator can solve by itself.

The claims below are mathematical deductions under their stated assumptions.
They neither allocate the twelve existing perpetual-value failures among error
mechanisms nor qualify a replacement implementation. The proposed finite-volume
and age-state comparison remains unimplemented and unexecuted.

## 1. A fixed finite chain has a polynomial first-hit onset

Let Q be a fixed generator of a finite-state, time-homogeneous continuous-time
Markov chain, with all rates finite. Add an absorbing event marker A and start
at a state i outside A, with no initial mass on A. Suppose A is reachable and
the shortest path from i to A through positive off-diagonal rates has length
k >= 1. Then

\[
  \Pr_i(\tau_A\le t)
  = (e^{tQ})_{iA}
  = \frac{(Q^k)_{iA}}{k!}t^k+O(t^{k+1}),
  \qquad (Q^k)_{iA}>0.
\]

For fewer than k factors, no product can connect i to A. At order k, every
contributing product must follow a shortest path and contains only positive
off-diagonal rates. Negative diagonal entries cannot cancel that coefficient,
because inserting a diagonal step would leave fewer than k transitions to
reach A. The matrix exponential is analytic at zero since Q is finite.

For a fixed positive initial mixture on finitely many states, the smallest
reachable path length with positive initial mass determines the first power.
Positive mixture weights cannot cancel its positive coefficient. If A is
unreachable, the hit probability is identically zero instead. An initial atom
on A contributes an immediate hit and is a separate case.

Consequently, for a reachable marker and no initial hit,

\[
  \lim_{t\downarrow0}t\log\Pr_i(\tau_A\le t)=0.
\]

This holds for the frozen finite Q. It is not a statement about a sequence of
different generators whose state counts or rates grow as a mesh is refined.

## 2. A diffusion started away from the boundary has a different log rate

Consider the continuous reference

\[
  X_t=x+\mu t+\sigma W_t,\qquad
  x>0,\quad \sigma>0,\quad
  \tau_0=\inf\{t\ge0:X_t\le0\}.
\]

For finite fixed drift mu and volatility sigma, its first-hit density is

\[
 f(t,x)=\frac{x}{\sigma\sqrt{2\pi t^3}}
        \exp\!\left[-\frac{(x+\mu t)^2}{2\sigma^2t}\right].
\]

Integrating near the upper endpoint, or bounding that integral above and
below on shrinking endpoint intervals, gives the logarithmic asymptotic

\[
 \lim_{t\downarrow0}t\log F(t,x)
 =-\frac{x^2}{2\sigma^2},
 \qquad F(t,x)=\Pr_x(\tau_0\le t).
\]

There is no contradiction with eventual escape for positive drift: this is a
small-time statement, not a claim that the total first-hit probability is one.

The same argument extends to a fixed initial law whose essential lower
support endpoint is a > 0 and which has positive mass arbitrarily close to a.
Monotonicity in the starting distance gives

\[
 \Pr\{X_0\le a+\varepsilon\}F(t,a+\varepsilon)
 \le \mathbb E[F(t,X_0)]\le F(t,a).
\]

Taking t log, then sending epsilon to zero, yields rate
-a^2/(2 sigma^2). No smooth-density assumption is needed for this bound.

A fixed finite-chain probability with the positive coefficient in Section 1
therefore has the wrong extreme small-time logarithmic rate for this starting
law. Its ratio to the diffusion first-hit probability tends to positive
infinity as t decreases to zero. This is a limit statement, not a claim that
the ratio is monotone at every intermediate time.

For a fixed nonnegative discount rho, the discounted hit mass obeys

\[
 e^{-\rho t}F(t,x)\le
 G_\rho(t,x)=\mathbb E_x[e^{-\rho\tau_0};\tau_0\le t]
 \le F(t,x).
\]

Thus F and G have the same small-time logarithmic rate, and the same leading
power whenever a power-law asymptotic applies. Discounting alone does not
repair this discrepancy. A robust log-domain implementation can avoid
floating-point underflow without making the represented law accurate.

## 3. The boundary shape of the starting law changes the leading order

A starting law that reaches arbitrarily close to the boundary is a different
case from Section 2. Suppose it has no atom at zero and has a density with
finite, strictly positive right limit 0 < p(0+) < infinity. Then

\[
 \Pr(\tau_0\le t)
 \sim p(0+)\,\sigma\sqrt{\frac{2t}{\pi}}.
\]

At leading order, put x = sigma sqrt(t) y in the density integral and use
the zero-drift limiting hit probability 2 Phi(-y). The integral
of 2 Phi(-y) over positive y is sqrt(2/pi). A finite fixed drift affects
higher-order terms, and mass bounded away from zero is exponentially small.

If instead p(x) = c x + o(x) as x decreases to zero, with 0 <= c < infinity,
then

\[
 \Pr(\tau_0\le t)=\frac{c\sigma^2}{2}t+o(t).
\]

Here the integral of 2 y Phi(-y) over positive y is 1/2. Only c > 0 gives
a nonzero leading term and an asymptotic equivalence to that linear term;
for c = 0 the conclusion is only o(t). These statements assume a fixed
probability density with the stated local behavior, not an atom or a
time-dependent initial distribution.

For a regular killed diffusion at a strictly positive elapsed time, its active
transition density vanishes at the absorbing boundary. If an observation
likelihood is nonnegative, bounded and sufficiently smooth near that boundary,
and its normalization satisfies 0 < Z = integral L(x)p(x) dx < infinity,
conditioning preserves the zero boundary value. Singular likelihoods, boundary
atoms and zero or divergent normalization require separate analysis.

A piecewise-constant reconstruction that replaces the first active cell by a
uniform density can instead assign positive p(0+). Replacing that basis with
a linear function that vanishes at the boundary changes the decoded starting
law even if the cell mass stays fixed. It can be a useful design change, but
it requires a new source/model binding and new qualification. It cannot be
retroactively assigned to posteriors trained and decoded with the old basis.

Matching a linear leading power in one law also does not establish the correct
coefficient, the complete hit distribution, its parameter gradients or the
quality of mixtures with different boundary behavior.

## 4. A finite phase chain does not exactly encode a positive deterministic wait

From a known remaining refractory time r > 0, physical release has probability
zero before r. A reachable event in a finite homogeneous chain with finite
rates has positive probability at every t > 0: it can traverse its finite
positive-rate path within any positive time. Thus a fixed finite phase chain
cannot exactly represent that deterministic wait. An unreachable marker would
give zero forever and would not solve the problem either.

An Erlang construction with j phases and rate j/r has mean r and variance
r^2/j. Its variance vanishes only in a refinement limit, not for fixed j.
An initial distribution of remaining times is another law and must be encoded
explicitly. In particular, release before the support's positive lower endpoint
is a distinct error even when total phase mass is conserved.

## 5. What a common finite generator would establish

Using the same finite Q for propagation and event flux can give an exact
discrete semigroup e^{(s+t)Q} = e^{sQ}e^{tQ}, with conservative bookkeeping
when the reset and marker states are included correctly. This removes the
particular failure of repeatedly applying incompatible projected maps.

That algebraic property does not prove continuum accuracy. A useful replacement
must pass separate checks for spatial refinement, boundary reconstruction,
rare F/G and log-risk, age transport, reset counts and accumulated value. The
ratio Delta/(sigma sqrt(t)) is a resolution diagnostic, not a certified error
bound or a universal pass threshold. Changing the mesh with t is a different
limit from holding Q fixed and sending t to zero.

The existing numerical holds remain in force. No trained-state qualification,
new common-learning-rate selection, confirmation score, energy advantage or
P5 scaling admission follows from this note.

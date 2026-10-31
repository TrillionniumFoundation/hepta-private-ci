# Round 4: conditional laws, event transport, and independent acceptance

This round continues the terminal-state prediction and communication study. It
does not reinterpret the preceding experiments or their confirmation data. All
Round 1–3 sources, prepared models, observations, results, and acceptance rules
remain historical evidence. Round 4 fitting, development, and confirmation use
separate registered identities. Engineering completion and scientific acceptance
are reported separately.

## 1. What a probability predicts

The physical task state is a real-valued latent diffusion. A component with
parameters `(b, q, s)` has constant drift `b`, positive process variance rate `q`,
and positive observation-noise multiplier `s`:

\[
dX_t=b\,dt+\sqrt q\,dW_t,\qquad X_0\sim N(0,1).
\]

The public conditioning information consists of observations that have actually
been acquired and read back, their physical times, occupancy and observation
masks, declared sensor variances, and already available action costs. A missing
observation advances time without adding a likelihood term. An unoccupied slot
does neither. Two acquired sensors at the same time contribute two likelihood
factors. Neither target values, hidden regime labels, window indices, trajectory
identifiers, nor observations available only after an unchosen action are model
features.

For lower and upper thresholds `l <= u`, the event order is always

\[
p_-=P(X_{t+h}\le l\mid\mathcal F_t),\quad
p_0=P(l<X_{t+h}\le u\mid\mathcal F_t),\quad
p_+=P(X_{t+h}>u\mid\mathcal F_t).
\]

Thus call and put are two directional interfaces to one conditional law. At one
common threshold they are complementary; two different thresholds leave a
neutral interval. They are not independently fitted distributions. Under a
Gaussian component, `M=m+b*h`, `V=v+q*h`, and the event probabilities are stable
normal integrals. Zero variance uses the exact stated inequalities, including
atoms on thresholds. Continuous derivatives are claimed only at positive
variance and interior parameter values.

These are physical task probabilities. They are not discounted option prices
under a risk-neutral measure. The Gaussian CDF is the probit link; its use does
not establish a new function class or superiority over an independently
implemented matched Gaussian/probit calculation.

| Quantity | Meaning | Must not be substituted for it |
| --- | --- | --- |
| Terminal event | State at one stated future physical time | First crossing before that time |
| Neutral probability | Terminal state between two thresholds | No communication or missing data |
| First-passage event | A continuous path reaches a boundary before a deadline | A terminal Gaussian tail |
| Zero increment packet | No changed quantized state at the stated resolution | No physical observation or no uncertainty |
| Missing observation | Sensor value was not acquired | An observed zero or a negative event label |
| Signed communication increment | Change in encoded conditional state | Realized call/put outcome |
| Runtime confidence/authority | Separate Hepta control fields | Predicted event probability |

## 2. Exact mixtures and time propagation

An exact mixture preserves its components:

\[
p_h(x\mid\mathcal F_t)=\sum_j w_j(\mathcal F_t)
  \varphi(x;m_j+b_jh,v_j+q_jh),\qquad
w_j\ge0,\quad\sum_jw_j=1.
\]

Density log scores use log-sum-exp. Interval probabilities sum component
interval masses. Mixture quantiles invert the mixture CDF; a Gaussian having the
same mean and variance is a distinct approximation and is scored as such.
Posterior component log weights are retained directly using stable softplus
identities. A small component is not obtained by subtracting a rounded dominant
weight from one. Log-domain scoring can therefore preserve a physical component
even when its linear FP64 weight underflows. The positive-weight runtime schema
rejects such an unrepresentable export instead of silently removing it; only a
structural zero caused by an exactly zero prior may be omitted.
The predictive weights remain fixed during propagation without a new
observation. Every component obeys its Gaussian Chapman–Kolmogorov identity.
Equivalently, an augmented process with a fixed component indicator has a
block-diagonal transition semigroup. The marginal state alone need not be
Markov, so repeatedly replacing a mixture by two moments is not the same
semigroup.

When weights equal normalized prior times public-history component likelihood,
they are Bayesian component posterior weights for the declared mixture model.
A learned transformation of likelihoods remains a conditional mixture forecast
but is not automatically that Bayesian posterior. In particular, a learned
gate at each observation, clipping, or development-selected interpolation does
not by itself establish a time-consistent joint path model. Componentwise
propagation and whole filtering consistency must be described separately.

A component's independent reference conditions a multivariate Gaussian directly.
For observed times `t_i`, its sensor covariance is
`1 + q*min(t_i,t_j) + diagonal(s*r_i)`, its sensor mean is `b*t_i`, and its
cross-covariance with the future state is `1 + q*min(t_i,T)`. Missing observations
are removed before that construction. This reference must not call the recursive
filter being checked.

The context study adds eight prior public sensor histories from distinct paths
sharing the query's latent regime. It is a new information experiment relative
to the prior zero-context task. Only those sensor histories are exposed; their
latent targets are discarded. Exact-mixture, independently conditioned
classical, projected-moment, and replay comparisons declare whether the same
context is used or deliberately ignored. A full context/query block is the
independent sampling unit; eight context histories are not eight extra query
outcomes. The frozen registration specifies how block membership is available
without revealing the regime label, and accounts for this additional input.

The calibration Q24 profile rounds component dynamics and the prior before
filtering. The runtime profile additionally quantizes transmitted conditional
state and the original native head's input parameters. Sharing the conditional
law schema does not make those numeric profiles identical or transfer their
individual empirical results to one another.

## 3. Q24 is a representation of a law

There are three distinct objects: the physical continuous forecast; the forecast
after any declared input-parameter quantization; and the released categorical
integer distribution. Their identities and errors are reported separately.
For the positive categorical profile, let `Q=2^24`, `K=3`, and let `p` be a
normalized nonnegative three-class vector. Allocate `Q-K` units by largest
remainders, resolving equal remainders by channel index, then add one unit to
each class:

\[
n_i=1+\operatorname{Hamilton}_i((Q-K)p),\qquad\widehat p_i=n_i/Q.
\]

Consequently `sum(n)=Q` and every `n_i>=1`. Before integer rounding this is the
uniform contamination `(1-K/Q)*p + 1/Q`; it changes the original distribution.
Hamilton rounding contributes less than one additional unit to any coordinate.
Therefore a safe componentwise absolute bound is

\[
|\widehat p_i-p_i|\le K/Q=1.7881393432617188\times10^{-7}
\]

for `K=3`, with a separately declared floating-point tolerance in validation.
An observed released class has finite negative log probability no larger than
`log(Q) = 24*log(2)`. This is a property of the released categorical code, not a
claim that extreme physical tail likelihoods are accurate in relative error.
There is no uniform relative-error or log-score-error bound as `p_i` approaches
zero. Original stable log probabilities are retained as separate diagnostics.

The physical positive-tail profile requires finite ordered distinct thresholds
and strictly positive variance, so all three events have positive mathematical
mass. Structural zero events, including empty intervals and deterministic laws,
must be handled by an explicit different support contract; the positive
three-class release must not silently assign them possible status. A zero
FP64 mass caused by underflow can still correspond to positive physical mass.

Parameter rounding must not borrow the categorical bound above. Its effect on
the underlying law is evaluated independently. Likewise a density-retention
certificate does not automatically survive parameter rounding, probability
projection, or replacing a mixture by a Gaussian.

## 4. Communication state and recovery

Encoder state, receiver state, and original native state are separately
identified. Every packet has a schema/configuration binding, logical sequence,
physical time, update kind, and typed payload. A receiver's sole dynamic input
is the successfully serialized, delivered, reopened, validated packet; it does
not read the sender's continuous target or rounding residual.

Signed increments and direct absolute quantized state share the same rounding
rule and representation grid. With exact integer reconstruction and matching
reset semantics they are algebraically equivalent, which is a useful
implementation check and cannot be counted as an independent predictive gain.
Their communication costs may differ. A continuous floating-point arm uses the
same owner, journal, framing/integrity checks, readback, and downstream delivery
path when used as a cost comparator.

The packed runtime validates a finite positive source law, then enforces native
bounds on decoded and native-rounded parameters. Its accepted source domain is
the preimage of those bounds under the declared quantizer. It is not a claim
that every unrounded source parameter already lies in the same closed numeric
box: a mean slightly above 8 can quantize to 8. Floating and integer transport
can consequently have different boundary acceptance. Matched comparisons use
inputs accepted by all compared modes; these numeric boundaries do not change
the underlying event definitions.

Episode reset initializes declared transport/filter state. Residual subtraction
resets communication error. Neither operation is a biological membrane reset
after a first-passage firing event. New schema versions cannot load old state
without an explicit validated conversion. Sequence gaps, clock regressions,
noncanonical/overflow payloads, changed duplicates, corrupt checksums and model
bindings, and unreconciled partial commits fail closed. A checksum detects
accidental corruption; it is not an authentication or hostile-filesystem
security theorem.

Record payload bytes, complete frame bytes, durable journal/snapshot bytes,
logical event units, native calls/ticks, serialization time, I/O time, and total
wall time separately. Shared-host wall measurements do not establish energy,
hardware latency, or monetary savings. Nested timers must not be added twice.

## 5. Training and action-value evaluation

Trained continuous-model parameters, learned mixture/gate parameters, readout
parameters, and finite development choices are recorded separately, including
initial/final values, optimizer work, actual label consumption, and all retained
candidates. Selecting an encoder configuration is not gradient training through
hard spikes. Same information means the same actual permitted query fields;
same label budget includes both fitting and development labels.

Wait, repair, and stop remain concrete actions with observed costs. A selected
action acquires its observation only after it has been chosen and paid for.
The completed delivery is reopened before its hidden target is used for scoring.
Prediction metrics and downstream utility are separate endpoints. A matched
Gaussian/probit or direct-quantized control is retained even when numerically
equivalent. An original sparse control runs the original native path; fitting a
new readout does not mean that the sparse state-update kernel was trained.

A calibrated or mixture forecast used for control needs an explicitly stated
planner. A planner using a Gaussian moment approximation, anchor dynamics, or a
single fitted observation law is not automatically exact for the mixture.
Actual outcome scoring remains decisive. Native runtime authority remains the
registered research authority; a better forecast is not a production grant.

## 6. Retention, calibration, and sampling

Every retention difference is relative to the original unchanged anchor, not
the immediately preceding checkpoint. An empirical development constraint is a
selection rule, not a pointwise or population guarantee. For comparison, a law
`p_new = alpha*p_anchor + (1-alpha)*p_candidate` satisfies
`NLL_new-NLL_anchor <= -log(alpha)` pointwise whenever `alpha>0`; imposing a
0.02 bound requires `alpha>=exp(-0.02)` and sharply limits adaptation. This
mathematical comparison is not automatically the mechanism of the empirical
models studied here.

The registered old-NLL margin, new-NLL efficacy, ECE threshold, coverage range,
utility superiority/noninferiority, and runtime requirements are separate gates.
A new registration may declare new comparisons but cannot retroactively change
the Round 3 gates. Retention across a finite recurring schedule does not imply
unlimited preservation over arbitrary future tasks. Calibration in one mixture
of conditions does not imply calibration separately in every latent regime.

The independent unit is an entire trajectory. Multiple horizons, actions, model
outputs, and revisits to the same old holdout are dependent measurements. The
trained seed is the upper-level resampling unit. Reusing one old holdout across
windows does not increase the count of independent trajectories. Confirmation
data is generated only after the source, model, selection, and protocol freeze;
unsuccessful, equivalent, and non-significant outcomes remain in the record.

## 7. Scope of first passage and external theory

This round does not implement a newly trained first-passage/reset cell. Such a
cell would require a separate stopping-time law, survival/censoring likelihood,
reset distribution, refractory period, remaining-time propagation, and repeated
firing likelihood. The previous Brownian hitting fixture remains a semantic
reference. It is not evidence for those missing mechanisms.

[Deep Q-Learning on Hölder Spaces](https://arxiv.org/abs/2606.16846) analyzes
Bellman-target regularity and approximation for uniformly elliptic diffusions.
An analytic Gaussian transition is a concrete solvable propagation example.
The paper explicitly studies a Cauchy problem and excludes the absorbing-boundary
complications relevant to first passage; it does not automatically prove this
study's calibration, reset behavior, practical sampled DQN convergence, or
end-to-end hard-event learning. No DQN-convergence claim is made here.

[Sigma Delta Quantized Networks](https://arxiv.org/abs/1611.02024) supplies prior
art for communicating changes in quantized activations. Hence this round tests
measurable law, action, transport, and recovery properties rather than claiming
that signed residual communication alone constitutes a new neural function
class.

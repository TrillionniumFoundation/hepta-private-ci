# Round 4 packed conditional-law runtime and paid-feedback contract

## 1. One law, explicitly different events and representations

`hepta.conditional-law.v4` contains `weights`, `means`, `variances`, and
`semantics="terminal"`. It represents one or two Gaussian components with
strictly positive weights and variances. The weights sum to one. A genuine
zero-weight component is omitted rather than revived by a numerical floor.
The law is an exact finite mixture; mean and variance summaries do not replace
its tails, density, or continuation calculation with a moment-matched Gaussian.

The three categorical outputs are the terminal residual events
`E <= lower`, `lower < E <= upper`, and `E > upper`. Call and put are directional
interfaces of that same conditional law. They are not independently sampled
probabilities, first-hit events, emitted pulses, missing observations, or
authorization confidence. In this task the residual remains constant between
the two sensors; observing a sensor changes the posterior, not the latent path.
There is no firing/reset first-passage claim in this runtime extension.

For the feedback task, the packet clock is the number of acquired observations,
one or two. Sequence additionally orders same-stage refreshes. The codec's
`propagation` kind means an unchanged-stage refresh and requires equal clock;
it is not an implementation of a continuous diffusion semigroup. `missing`
allows an explicitly advanced packet clock without treating a missing sensor
as a neutral categorical observation. The ordinary study has no missing sensor
draws. A calibration bridge separately records its physical prediction horizon
of one time unit; that physical horizon is not the feedback observation clock.

## 2. Actual native probability computation and positive release

Every component is sent to the existing verified native typed prediction head.
The head rounds its mean, variance and boundaries to its original Q24 input
representation, computes its Gaussian probabilities, advances its original
native state, and returns its durable journal/witness receipt. All component
head calls are real. Their actual floating-point probability vectors are mixed
with the received mixture weights. This native mixture vector, not a Python
replacement, supplies the released category probabilities and the analytic
sparse readout features.

For a normalized K-category native vector p, release uses

`q_i = 1 + Hamilton_i((2^24 - K) p)`,

where Hamilton denotes floor plus largest fractional remainders, ties in
category order. The released vector is q/2^24, has exact total mass one and
positive integer counts. For K=3, each coordinate differs from normalized p by
less than 3/2^24, apart from separately measured floating normalization error.
Its event NLL cannot exceed `24 log(2)`. This is a specified uniform-contamination
release distribution followed by rounding. It does not assert that a physical
Gaussian tail of 10^-100 is actually 2^-24, and it provides no calibration or
relative-tail-error guarantee. The raw native zero counts remain in every
receipt. Separate stable physical log probabilities retain extreme-tail
information without applying this floor.

This release error bound is relative to the actual native mixture vector.
It excludes mean/log-variance/weight transport error and native input parameter
rounding, both of which have separate diagnostics. The continuation planner
uses the received native-effective component law. Its mean/variance channel is
separate from released categorical features. Consequently zero-tail removal is
a representational acceptance criterion; it is not automatically an identified
utility improvement caused by the floor.

## 3. Matched transport and bounded owner

The event and direct controls share the same absolute representation: mixture
weights use a positive Q24 allocation; component means and log variances use
nearest 2^-12 levels, with exact half ties toward positive infinity. Event
packets transmit signed differences of those integer levels; direct packets
transmit the absolute levels. This is difference coding of one quantizer,
so the decoded integer states agree. It does not establish a distinct function
class or a differentiable training rule through a hard spike.

The FP64 control sends the same mixture coordinates without this 2^-12 state
quantizer. Every mode has the same 24-byte version/mode/kind/component-count/
sequence/clock/CRC framing, actual binary write, flush/fsync, independent reopen,
strict decoder, advisory lock, pending journal, state/witness owner, native calls,
and final output delivery. Delta and absolute payloads use the same canonical
zigzag varints. Overlong integers, excess bytes, overflow, invalid schema,
regressing sequence/clock, component-count changes, and CRC failure are rejected.
CRC32 detects accidental corruption; it is not an adversarial security claim.

An owner permits at most 16 requests. Source components must have finite means,
strictly positive finite variances and positive normalized weights. After
transport decoding, component means must have absolute value at most 8 and
variances must lie in [2^-24,8]. Native parameters and boundaries must then meet
the original native head's own bounds and strict-order checks, including its
Q24 rounding. The accepted source domain is the preimage of these decoded/native
checks. A slightly out-of-box source can round into the event/direct domain;
the same source can be rejected by FP64 mode. For example, variance 8 decodes
to approximately 7.9992333 under the fixed log-variance quantizer. The matched
benchmark uses its common eligible corpus, and does not assert identical
admissible source sets across all three modes. Model identity, owner identity
and transport mode are hash-bound in the owner.

Adapter and native component states have distinct transactions. Interruption
after a packet, after one component, or after all native components leaves
evidence and fails closed. There is no cross-owner atomic commit claim. A lost
acknowledgement after complete commit returns the identical cached receipt
without another native tick. Caller-held checkpoints and a separate local
witness detect the tested stale or rolled-back adapter state. This is not
protection against a hostile writer replacing all local evidence together.

## 4. New hidden-residual task and fitted controls

For each trajectory, initial output A is standard normal, and the private
residual E is drawn from a mixture with weights (0.65, 0.35), means (-0.45, 0.85),
and variances (0.09, 0.36). The private target is Y=A+E. The first sensor observes
Y with variance from {0.04, 0.36, 1.44}; a paid second independent sensor uses
variance from {0.04, 0.16, 0.64}. Repair cost c is drawn from {0.03, 0.12, 0.48}
and waiting cost w from {0.01, 0.04, 0.12}. These costs and sensor variances are
public before the first choice. Initial output, residual feedback and final
output use the existing actual Hepta text/PNG delivery and readback functions.

First choose stop, repair or wait; after paid wait choose stop or repair.
Repair delivers A+a, where a is the actual received mixture mean rounded to
Q24. Final utility is `1-(delivered-Y)^2-c*repair-w*wait`, scored only after the
final delivery readback. The policy worker loads a strict target-free schema.
This is ordinary process/dataflow separation, not hostile same-UID isolation.

Prior mixture parameters receive 80 actual EM updates from fresh training
residual labels. Sensor noise scale is fitted by supervised maximum likelihood.
A separate K1 Gaussian prior is fitted from the same training rows; its
precision posterior and independent dense-conditioning/probit formulation form
an equivalence control. Analytic and numeric inputs drive the original sparse
kernel's three channels, with two real native ticks each and a 63-dimensional
readout. History uses a matched 63-dimensional polynomial/RBF representation.
Each readout has three ridge candidates, 600 actual gradient steps per candidate,
and five development offsets. Complete candidate weights, gradients, development
outcomes and parameter changes are retained. Hard packet coding is not jointly
trained by backpropagation, and the original sparse kernel is unchanged.

Repair value is `2*a*E[E|public]-a^2-c`. The wait value integrates the positive
optimal continuous repair gain over the exact mixture predictive sensor law
using a fixed 64-point Gauss-Hermite rule per component, then subtracts w.
This is a named numerical approximation. Independent adaptive integration
splits at posterior-mean crossings of +/-sqrt(c); development fixtures show
error can be about 0.00126. It is not floating-point roundoff or an exact Bellman
certificate. All three codec controls share the identical rule, and actual
follow-up actions determine the final utility. Learned readouts can deviate from
the plug-in optimal continuation used for this common waiting score.

## 5. Frozen sampling, acceptance and cost accounting

Seeds are 1213, 1427, 1619, 1823 and 2017, with 256 training, 128 development,
and 256 independent confirmation trajectories per seed. Generator seed is
`640000000 + 1000*seed + split`, with split codes 1, 2, 3 and 4 for training,
development, confirmation and runtime qualification. Confirmation is generated
only after publication and source/model/data freeze. Old confirmation rows
are not fitting data. Negative and equivalent outcomes are retained.

Two primary tests are event-minus-direct and event-minus-FP64 utility
noninferiority. Each uses a paired seed/whole-trajectory bootstrap with 4000
replicates and a 97.5% interval, a 0.01 noninferiority margin, and every seed mean
above -0.01. Event/direct exact action, output and probability equivalence is
reported separately. Sparse analytic-minus-numeric/history and event-minus-K1
comparisons have descriptive 95% intervals. Equal codec models are not required
to show superiority. Five training seeds do not supply a universal confidence
or production guarantee.

Bytes, signed integer quantum counts, packets, native requests/ticks, native
IPC time, Python CPU time, complete per-execution wall time, journal writes,
archive bytes and separate replay time are reported independently. Quantum
counts are a communication representation, not individually executed physical
spikes. Actual task costs are utility units, not dollars or CPU time. Paired
random arm order reduces systematic timing order bias. Latency measures are
shared-host Python/I/O measurements, without hardware-energy inference.

Every original per-case archive member is reopened and hashed before removing
the temporary source directory. Audits independently decode all original PNGs,
reconstruct acquired public histories and dense-mixture posteriors, replay all
native component and sparse ticks, and recompute outputs, choices and scores.
Fresh-process qualification exercises duplicates and continuation for all
three transport modes, extreme tail fixtures and the actual calibration-to-
native law bridge. The bridge uses ten deterministic calibration development
queries per seed and preserves their source model/data hashes.
Each bridge query also retains its exact public history/context, query identity,
physical horizon and conditioning digest; that digest enters the owner identity.
The owner's fixed diagnostic cost context only supplies boundaries and request
clock. It is explicitly not the calibration law's conditioning history. This
bridge accepts an actual prediction-head/state adaptation, and does not claim
paid-feedback utility for the calibration queries.

The native executable is the existing verified research artifact; this round
does not claim a fresh Rust build. Native confidence remains zero, abstention
enabled and authority `DENY_ALL`. Production promotion is false.

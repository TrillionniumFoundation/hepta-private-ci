# R15 conditional position/content-moment core

## Exact object implemented

`DistributionContentCore` carries a discrete spatial probability law and its
position-conditioned content **first moment**. It does not carry an arbitrary
joint density over continuous content vectors. Between acquired observations,
probability and content moments follow the same finite linear generator up to
floating-point matrix-exponential error. The learned observation operation
defines a moment-based recurrent network, not an exact Bayesian filter for a
separately established physical sensor model.

The formal default preserves 182 fine positions at spacing `1/17`, appends 98
tail positions at spacing `0.5`, and places an absorbing upper cemetery at `60`.
Initial location is `1.0`, drift `-0.25`, diffusion `1.0`, reset location `0.8`,
and reset delay is zero. Physics, grid and boundary are fixed, not trained.
This differs from the older scalar renewal content gate with refractory time
`0.15`. The old finite uniform profile remains available with
`tail_spacing=None`.

## Nonuniform generator and complete successors

`tail_grid.py` implements a new nonuniform discretization. It does not claim to
be the unchanged R14 uniform generator. At a node with left/right spacings
`l,r`, the rates are

\[
 q_+=\frac{\sigma^2+\mu l}{r(l+r)},\qquad
 q_-=\frac{\sigma^2-\mu r}{l(l+r)}.
\]

Before boundary actions, these satisfy

\[
 q_+r-q_-l=\mu,\qquad q_+r^2+q_-l^2=\sigma^2.
\]

Negative rates are rejected. The forward state stores probability mass at
nodes; it is not multiplied again by cell widths. Lower-boundary flux is
immediately reinserted at the interpolated reset atom. The same generator
therefore retains any number of events and the remaining time after each
reset. Upper loss is retained as an absorbing cemetery state. Physical
propagation does not clip or renormalize probability.

For column probability `p` and unnormalized per-position content moment `m`,

\[
 p'=\exp(\Delta t Q)p,\qquad m'=\exp(\Delta t Q)m.
\]

This defines content-preserving physical resets. It is not a learned reset
kernel, an erasing reset, or a claim of optimal active recovery. Content changes
at learned observation/write operations and explicit interventions. The marked
diagnostic uses the same nonuniform rates, including the fine/tail interface.
It reduces to the original R14 construction in the uniform-grid limit.

## Learned content operation and fixed physical anchors

After advancing by the supplied physical interval, an acquired encoded frame
and the current readout determine a bounded positive internal likelihood over
active positions. Only active mass is reweighted; existing cemetery mass is
unchanged. Content moments receive the same likelihood multiplier. A learned
position-specific gate then mixes conditioned content moments with a new
bounded candidate times the updated position probability.

Readout is a learned position-weighted sum of active content moments. Position
probability and position/content association can therefore affect predictions.
Cemetery content is retained for accounting but never read out. Labels, future
encoded frames and hidden task state are not inputs to the update.

Twelve learned spatial anchors retain their original physical coordinates
between `1/17` and `182/17`. The first 182 rows of their interpolation basis are
bit-identical to the old model. Every appended tail position uses constant
extrapolation of the last anchor. Enlarging or refining the tail adds no learned
parameters and does not stretch these features. Fine node coordinates agree
with the old implementation within approximately `1.78e-15`; that roundoff
comes from R14's recomputation of spacing as upper divided by interval count.

## Ordinary distribution comparator

`ordinary_distribution` has the same probability/moment shape, learned
observation/write/readout functions, and 2,028 trainable core parameters. Its
active dynamics are a single-rate exponential relaxation toward a full-support
fixed distribution, plus the same upper exit hazard at the last node:

\[
 Q_{\rm mix}=\lambda(\pi\mathbf1^\top-I).
\]

For prior matching, `pi` and `lambda` are the stationary law and slowest nonzero
decay rate of the analytic generator with a reflecting upper endpoint. Both
families receive the same fixed physical calibration information. Calibration
is recomputed for each declared grid, so cross-domain ordinary changes include
this calibration change; they are not attributed solely to removal of cemetery
loss. This comparator does not represent all strong ordinary SSMs or a generic
HMM with the identical analytic generator.

Both formal families have 4,777 recurrent scalars per row: 281 probabilities
and 281 by 16 content moments. With FP64 probability and FP32 content that is
20,232 bytes, excluding temporary tensors, gradients, weights and caches.

## Execution interventions and identified effects

`content_independence` preserves spatial probability, cemetery state and total
active content moment, replacing active moments by

\[
 m_i'=p_i\frac{\sum_jm_j}{\sum_jp_j}.
\]

It removes position/content association. Because readout is position-weighted,
it can immediately change current predictions. It is a complete execution
intervention, not a test that holds current predictions fixed.

`readout_independence` additionally provides a comparison matched on current
weighted features. For positive readout weights `w_ik`, set

\[
 C_k=\frac{\sum_iw_{ik}m_{ik}}{\sum_iw_{ik}p_i},\qquad
 m_{ik}'=p_i C_k.
\]

This preserves probability, cemetery probability/content, and the current
weighted feature up to floating-point summation error, while removing the
position/content association. `C_k` is a positive weighted average of the
conditional contents, so their boundedness is preserved. Current linear-readout
logits and controller inputs are consequently preserved to that numerical
precision. Unweighted total content moment need not be preserved. Subsequent
changes can identify the carried association's execution effect under these
fixed weights; this is not a separately trained architecture comparison.

`mean_position` also projects active probability to the two actual adjacent
nodes around its mean, using `searchsorted` and local spacings. It preserves
active mass and mean position, then independently distributes total active
content moment. It changes several distribution properties and is not a
single-factor variance intervention.

Independent light/value training effects require separate fitted models and
explicitly identified training conditions. The core itself makes no claim that
execution interventions establish those total effects.

## Interface, timing and numerical scope

- `initial_state(batch, device=None, dtype=None)` returns `probability[B,281]`
  and `content_moment[B,281,16]` under the formal default.
- `propagate(state, dt)` performs physical transport only.
- `observe(state, encoded_frame)` performs acquired-observation conditioning
  and content writing only.
- `read_state(state)` returns a 16-feature vector.
- `step(encoded_frame, state, dt)` returns `(feature, successor_state)`.
- `forward(encoded[B,T,16], dt[B,T])` returns `[B,T,16]`.

There is no hidden mutable recurrent state. Explicit states can be cloned or
serialized. Unobserved physical intervals have finite-semigroup partition
consistency; repeating a learned observation/write is a different operation.
Reprocessing old observations must explicitly specify whether time advances
again. Calling `observe` alone does not replay historical physical intervals.

Cache keys preserve exact floating-point intervals, without rounding or
bucketing. At most 128 transition matrices are retained per core. Preparation
and misses are actual work; warm reuse is reported separately. Four cached
formal matrices occupy 2,526,752 bytes, and the 128-entry bound is about 80.9 MB.
Shared intervals use the same shared-matrix GEMM optimization for both families,
checked against the batched expression. Loading weights or converting a module
invalidates cached matrices. The qualified default keeps generator/probability
buffers in FP64; arbitrary `.float()` or `.half()` conversion is not qualified.
Time gradients bypass the cache. Physical-parameter and moving-boundary
gradients of the nonuniform model are not implemented.

`diagnose_interval(state, dt)` separately exponentiates a marked SciPy operator
to report first hit, count PMF with overflow, expected count and upper loss.
Marks begin at zero for that interval. These are not complete-history event
posteriors, free training features, or free online diagnostics.

## Verification, failures and tail repair

The final default passed 157 core checks, including SciPy transport, mass,
positivity, moments, partition consistency, multiple events, incorrect
interval-end reset detection, parameter/time gradients, causal prefixes,
step/forward alignment, cache invalidation and current-feature-matched
`readout_independence`. Count observables and coarsened probabilities are also
compared against an independent uniform R14 solver; different spatial grids
are not asserted to have identical full state vectors.

The discarded 12-node prototype had first-hit error around `0.02854` and count
errors around `0.03557` to `0.04555`. Its records remain. The initial uniform
182-node model passed the fixed-atom tests, but actual validation posteriors
later showed up to `0.0925589` upper loss. That failure is retained in
`development_posterior_diagnostics.json`. It demonstrated that initial-state
qualification did not cover actual content-network histories.

The tail repair keeps all learned parameters and physical anchors unchanged
when migrating the old development fits. Across both tasks, both distribution
families, every declared stress domain and the first 16 validation objects,
maximum upper loss falls to `9.6469e-10` for outer bound 40 and `4.2171e-14`
for the selected outer bound 60. The latter was chosen before formal training
and confirmation. These development traces do not qualify all later fitted
posteriors; formal evaluation must retain its own loss measurements.

At outer bound 40, halving tail spacing from `0.5` to `0.25` changes no greedy
prediction and changes one READ count across these cases. Moving the outer
bound from 40 to 60 changes no greedy prediction and changes five READ counts.
The ordinary global calibration also changes, as described above. Per-prefix
logits, predictions, utilities and all old-domain failures are retained in
`tail_migration_validation_01.json`.

At initial position 1 and times `0.25, 1.0, 1.75, 4.0`, all three extended
profiles pass the original relevant R14 continuous thresholds: first-hit
absolute error `0.0005`, expected-count error `0.002`, count-PMF L1 `0.002`,
upper loss `1e-7`, complete-successor histogram L1 `0.003`. Their maximum errors
are about `4.6424e-4`, `6.1884e-4`, `9.2848e-4`, below `2.5e-61`, and `0.0015612`,
respectively. The complete reference independently integrates every renewal
branch with its remaining time. These are four initial-state comparisons, not
uniform continuum, posterior, horizon or parameter-domain certificates.

Earlier numerical scale-check failures are retained: generator column-sum
roundoff and grid-index reward derivatives were subsequently checked in
explicit machine-scaled and physical units. A strict bit-equality assertion on
old/new fine positions also failed at `1.78e-15`; the final tail check uses the
declared machine-scale coordinate bound while anchor-basis equality stays exact.

## Reproduction and measured CPU

Use `law_checks --mode checks`, `--mode complete-successor`, or `--mode benchmark`
with a new `--output` path. Tail checks are in `tail_checks --mode numerics` and
`tail_checks --mode migration --checkpoint-root <development-output>`; migration
hardcodes validation data and never opens the confirmation split.

The frozen `tail_checks` CLI has a retained JSON-encoding failure for a NumPy
boolean after successful computation. `tail_numerics_02.json` is its unchanged
partial output. `tail_numerics_03.json` is written by an external wrapper calling
the same frozen `numerics()` function and converting NumPy scalars only during
JSON encoding. That record includes the wrapper source/hash, computation-source
hash and partial-output hash. No model, training or evaluation source is changed
to perform this serialization repair.

At batch 64, length 12 and width 16, the final fixed-random-tensor benchmark
measured warm forward/backward CPU around `0.188` seconds for the analytic
family and `0.197` seconds for the ordinary family. Cold forward/backward was
about `0.448` and `0.264` seconds; model construction was measured separately.
These are development CPU measurements, not task cost/quality acceptance, GPU
throughput, wall latency or physical energy. Actual training/evaluation process
accounts remain necessary.

The implementation connects a complete finite position law and conditional
content moments to content predictions. Task benefit, total cost benefit,
active recovery utility, general learned boundaries, uniform continuous-process
qualification, GPU/energy measurements and large real multimodal capability
require separate evidence.

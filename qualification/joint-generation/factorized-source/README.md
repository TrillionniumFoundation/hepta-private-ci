# Canonical source-attribute factorization: qualification only

**11 tests passed; scientific benefit has not been evaluated.** The new explicit
model preserves the original202→32→two12 raw logits and learned pixel decoder.
Each head is projected to the product of its color3 / shape2 / position2 marginals,
with explicit normalization and exact analytic pullback to the raw logits.

This supplies an additional known semantic factorization prior. It adds no FIT
labels beyond the existing12-class source labels, but it is not free structural
knowledge: each head loses seven correlation degrees of freedom (11→4). Equal
parameter counts and initial tensors do not imply equal function classes or initial
predictions. Correlation loss may harm generation. Canonical source-class indexing
is a training schema, not a guarantee that the learned decoder has those meanings.
Actual decoded semantics, transport, coupling and FIT calibration remain required.

For upstream virtual-factor-logit gradients g, already averaged over rows, let
h=g−q*sum(g), G[a,v]=sum_{y:attr_a(y)=v}h_y. Then

    chain_k = sum_a [p_k/m[a,attr_a(k)]] * G[a,attr_a(k)]
    raw_gradient_k = chain_k - p_k*sum(chain)

The bounded ratios p/m avoid standalone reciprocals. Both normalizations are
retained; no extra row mean is applied. Incoming gradients must be finite and have
row sums within the fixed1e-12 tolerance. This is the mathematical reference chain,
not a derivative of binary64 rounding. Strict positive support, canonical integer
attributes, finite normalized policies and marginal closure are checked; underflow
rejects without epsilon, floor or fallback.

The mode/profile makes model digests distinct; cloning preserves mode/tensors and
resets optimizer state. Each forward or parameter-gradient call performs one raw
network forward, retaining the existing command mask. Decoder training is unchanged.
Save/load is deliberately unsupported; no old checkpoint compatibility is promised.

## Verified scope and cost

Five unchanged source-model tests plus six new tests cover marginal preservation,
idempotence/product fixed points, a changed correlated joint law, allkeep/fullset
and partial command maps, parameter/init parity, mask and input immutability,
clone/mode/decoder behavior, operation counts and strict refusals. Source-only v1/v2
were never executed; v3 tightened nested canonical attribute types before the first
run. No claim of a numerical-mapping bug is made for that schema correction.

All70 finite-difference coordinates passed:48 raw-logit coordinates(max1.10e-10),
eight both-head A+ordinary-anchor coordinates(max5.81e-11), seven supervised model
parameter coordinates(max2.36e-10), and seven full A+anchor model parameter
coordinates(max5.10e-11). Prospective bounds were3e-8 for heads and2e-7 for model
parameters. The inherited supervised log-floor convention is unchanged; these
checks use interior probabilities, not its extreme nondifferentiable boundary.

Fully waited: **0.258624 CPU seconds**,0.454317 wall seconds,30452KiB RSS under
5CPU/30wall/512MiB/4MiB, CPU0, one numerical thread and the existing synthetic lock.
Ten literal toy model initializations and real toy updates are included, not
misreported as zero model work. Zero model restores, scientific models, scientific
training updates or scientific dataset rows; no renderer access. Source/review,
historical work and unknown supervisor tails are additional, not zero.

The planned representation-only direct-A/factor-A comparison retains strong exact
historical controls and the original five quality gates. It cannot establish an
NDU gain. No scientific run or benefit claim is contained in this qualification.

## Portable tests

```sh
PYTHONPATH=../source-scene-decomposition:../explicit-semantic-transport:../transport-aligned-training:.. python -B -m unittest -v test_factorized_source
```

Only portable source/tests, the executed plan and aggregates are public. No weights,
private inputs, per-request predictions, runtime paths or unrestricted runner;
no default change, merge or deployment.

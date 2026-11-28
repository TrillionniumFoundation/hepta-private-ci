# Known-mechanism GPT transfer under new weight-program coordinates

This follow-up is declared after the original late-information results are known.
It does not claim that GPT independently discovered that circuit, nor that the
original experiment was blinded. It asks whether a GPT editor can compile the
known task from a fresh anonymous weight view with changed feature units, unit
order and sign gauges, without labels, examples or evaluation feedback.

## Fixed source and task

Use the same three actual frozen parents and explicit final-tick mark graph.
The source, protected parameters and four permissible canonical mark-price
words remain unchanged. The editor receives no source seed mapping or new data.
The task still means waiting until the final quote and selecting the lower
physical numeric price. Histories and final nonprice inputs are shared and
external baselines are equal. Only this declared task contract is accepted.

## Weight-program view, not an unreported native architecture

For canonical final affine weights W, biases b and signed-feature readout C,
define anonymous row permutation pi, feature permutation phi, row signs g in
{-1,+1}, and feature coordinates z_k = s_k*x_phi(k) + t_k. Every scale is a
nonzero signed power of two; every translation is a quarter-integer. The view
contains A_jk = g_j*W_pi(j),phi(k)/s_k and
d_j = g_j*b_pi(j) - sum_k A_jk*t_k. Signed-feature readout coefficients are
multiplied by the same g, with a separately permuted, explicitly identified unit
order. Historical signed offsets and recurrent offsets transform by g too.

This is an exact-arithmetic representation of the final affine/signed-readout
interface. It is not a claim that a partially gauged persistent native network
has identical hidden dynamics. The host always applies decoded edits to the
original source-bound native model and evaluates the complete original kernel.

The physical quote is x_price = (z_quote-t_quote)/s_quote; its scale may be
negative. The editor must account for the supplied physical units. It may only
change the four quote-column A words and must preserve their magnitudes. To keep
canonical biases unchanged when the coordinate origin is translated, its derived
bias representation must satisfy d'_j = d_j-(A'_j,quote-A_j,quote)*t_quote. These
derived view biases are not additional writable native parameters.

Use PCG64 seed 2026112807 to create the alias/view packet. Each source parent's
quote scale is fixed respectively to +2, -0.5 and -4; which anonymous case has
which source seed is retained only in the host mapping. Other scales, row signs,
row/feature orders, head-column order and anonymous IDs are generated before the
editor sees the packet. The editor receives the affine and head tensors plus
unit/coordinate contracts, but no task examples or target labels.

## Editor seal and final test

One GPT editor attempt is allowed. It must produce a standalone deterministic
program and explicit candidate JSON from the packet, explain the sign/origin
logic, and abstain if all relevant signed-head contrasts vanish. Program,
candidate and packet digests are sealed before any new test is generated. The
host may reject a malformed or out-of-scope candidate but cannot request a
success-guided revision. Any failure remains a failure of this attempt.

After the seal, generate 40 new contexts/80 swapped queries using PCG64 seed
2026112808, physical price interval [-4,4], minimum quote gap 0.2, and the original
task generator. This is a new synthetic test of a previously known mechanism,
not natural future market data. The same contexts are shared by all three
parents; paired samples and parent views are not independent replications.

Evaluate four graph-enabled arms at each parent: KEEP; canonical sign compiler;
the GPT program decoded from anonymous coordinates; and a negative control that
uses the same unit mapping but ignores the sign of the quote unit scale. It
still preserves native scope and view-origin compensation. The negative control
is a semantic-error intervention, not an equal-radius optimization comparator.

Also evaluate the GPT patch on the original graph on the new test and on the
historical normal retention inputs with the explicit normal route. The first
must remain at the exact shared-history chance barrier. The second must match
the original retained parent features, heads and scores byte-for-byte. Report
all 18 complete native forwards, physical residuals, accuracy, CE, prediction
bytes, candidate digests, changed-word count and timings. A canonical/GPT byte
tie is reported as a tie, not a new performance advantage.

No gradient fit or candidate search is permitted. Direct scientific CPU budget
is 120 seconds and 18 native forwards. Editor wall time is recorded separately;
agent inference compute/cost is unavailable and must not be reported as zero.
No deployment or new claims about Call/Put, Belief, learned Q, NDU or trader
profit follow from this representation-transfer check.

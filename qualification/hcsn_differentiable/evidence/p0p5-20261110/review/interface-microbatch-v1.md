# Independent interface, CfC and microbatch follow-up

This note supplements the preserved [head-domain analysis](frozen-head-domain.md)
and [raw36 audit](raw36-summary.json). It does not alter those original artifacts.
The [source-bound review receipt](interface-microbatch-v1.json) records exact
source hashes and the scope of each finding. No new training run is credited.

## CfC correction and head geometry

The actual wrapper explicitly uses `ncps==1.0.1`, `mode="default"`. Its output is
`(1-s)*tanh(ff1) + s*tanh(ff2)`, where `s=sigmoid(...)` lies between zero and one.
The raw output is therefore coordinatewise bounded by [-1,1]. The existing
GRU-box confidence certificates apply to this outer CfC output domain as well;
CfC must not be described as an unbounded readout in this comparison. Its two
raw adequate fits are consistent with these bounds because accuracy and
softmax confidence are different quantities.

The domain witnesses show that each class can win in the declared algebraic
output domain. They do not prove that the recurrent dynamics can produce every
witness. Consequently no class is ruled out by the frozen head alone, but the
cause of a model's memorization failure is not established by this calculation.

The uniform identity-initialized `Linear(16,16)` plus bias adds 272 trainable
real parameters to every core. For the observed full-row-rank fixed head W,
`W(Ah+c)+b` can represent any affine 16-to-11 readout. The stored head remains
frozen, while the effective classifier becomes trainable. This is an explicit
capacity/interface change that requires a fresh comparison and full cost
accounting. It does not repair the historical raw36 results retroactively.

## Effective-batch gradients and the epoch diagnostic

The reviewed helper computes each microbatch's weighted CE numerator using the
single denominator from all valid targets in the whole effective batch. The
sum of its gradients therefore equals the declared effective-batch objective;
clipping and Adam stepping occur once after accumulation. Each slice retains
the full padded time length. This reasoning covers the deterministic,
independent per-sample cores used here, not arbitrary BatchNorm, stochastic
Dropout or batch-coupled computations.

The reported epoch `training_weighted_loss` is an event-count-weighted average
of batch-normalized weighted objectives. It is not the globally normalized
weighted CE over the whole epoch when class-weight totals differ across batches.
This is a diagnostic-label/aggregation issue, not a change to the optimization
or separately computed development metrics. The training owner acknowledged
it and will retain the historical meaning while using summed weighted
numerators and denominators in a fresh full-training source.

## Exact frozen-table caching

The reviewed cache keys exact time bits, all physical tensor identities,
operator configuration and fixed buffers. It rejects learnable physics or dt,
uses a bounded per-instance cache, starts cold, and clears on state-dict load.
It does no gap rounding or interpolation. Table construction is charged inside
the fit; the byte counter explicitly covers unique tensor storages rather than
Python keys or allocator overhead. No new mathematical operator or numerical
qualification follows from this reuse. The scope of later timing comparisons
must still include cache construction, memory, failed attempts and host changes.

# Sampling refinement of frozen irregular-task encoders

This post-baseline diagnostic evaluates fifteen previously selected checkpoints:
three seeds each of free-boundary J/G HCSN, conditional-boundary J/G HCSN,
ordinary two gates, causal Transformer and hard-forward LIF SNN. It does not
train, choose new checkpoints or change any original test/OOD report.

For each of the original 512 test examples, a factor `k` in `1,2,4` repeats
every original token `k` times and divides its duration by `k`. The entire
64-dimensional input, including data/query markers, is held constant within
each original interval. Binary subdivision preserves original interval
endpoints and total physical time exactly in float64 bookkeeping. Only the
final query at position `32*k-1` is scored, so refinement adds no supervised
examples. All model evaluations use batches of eight.

The external label is the sign of a rate-0.2 leaky integral over the 31 data
intervals. Its exact constant-input transition is

\[
L_{h,u}(s)=e^{-0.2h}s+(1-e^{-0.2h})u,
\qquad L_{h/k,u}^{\,k}(s)=L_{h,u}(s).
\]

An independent weighted-sum expression and a recurrent computation verify this
identity, all labels and time endpoints. A zero-input final query interval
only multiplies the integral by a positive decay and preserves its sign.
Training examples are checked before sealing; all 512 heldout examples must
pass the same fixed checks before model inference.

These oracle checks are **not** a semigroup claim about the learned encoder.
Its frontend explicitly consumes duration and elapsed time, so subdivision
changes intermediate embeddings, physical coefficients and gates. The result
measures end-to-end robustness to sampling representation, distinct from the
fixed-generator numerical audits and the old OOD experiment that changed both
sequence length and total time scale.

The new batch-eight factor-one output is compared with the original saved
predictions. Any discrepancies, including hard-spike amplification of
batch-shape floating-point differences, remain visible. Factors two/four are
compared with the new batch-eight factor-one result, without replacing it.

Protocol and source hashes must be publicly sealed before inference. A
single-worker queue preserves the original finite/nonnegative/probability-mass
gate and records all predictions, coordinates, numerical failures and complete
process CPU/RSS. No numerical helper is substituted to repair a failing factor.

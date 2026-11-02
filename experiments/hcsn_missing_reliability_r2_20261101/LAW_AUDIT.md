# Conditional-law audit before R2 confirmation

The source is the unchanged `hcsn_four_stage_flow_20261031/synthetic_data.py`,
SHA-256 `4fbb836356e6017ae3baeb30f37e6cc3818de7caf7b01f98baf736c14511c35e`.
The declared constructor task and its typed schema are shared by both cores.
No answer, availability mask, erased address, dependency index, row ID, or
future query is passed to the posterior.

Four original values are distinct exchangeable draws from eight classes.
Selective then updates two distinct keys with two distinct values excluded
from all original values. The missing condition chooses one WRITE uniformly
among the four originals or six Selective writes, retaining a zero observation
slot and `observed=False`. This observation law is substantially stronger than
an arbitrary missing-data process.

For MQAR/Binding, an erased original key is the absent key in the visible
four-key write set; its value is uniform over five classes excluded from the
three observed original values. Binding's four observed bridge events resolve
the B alias without giving a value.

For Selective, an erased original key is likewise observable. The three visible
original values and two observed fresh update values exclude five classes, so
the erased original value is uniform over the other three. If that key receives
an observed final update, its final value is known instead.

When one final Selective update is erased, all four original values and one
other fresh update remain visible. The erased update key is uniform over the
three keys excluding the other updated key; it is **not recoverable** from this
visible prefix. The erased fresh value is uniform over three classes excluding
the five visible original/fresh values. For a query of any of those three keys,

\[
p(y\mid o)=\frac23\,\delta_{\text{visible old value}}(y)
 +\frac19\sum_{v\in\text{three unseen classes}}\delta_v(y).
\]

Thus a stale old-value argmax is Bayes optimal on that observation class, even
though it is wrong on the evaluation-only subset where that particular query's
final write was erased. The subset is not observable at inference. This
explains why R1's unavailable-only accuracy can be zero without making that
conditional argmax intrinsically wrong; R1's probability allocation and
selective reliability still required repair.

The exact ordinary reference uses `q=2/3`. R2's train-only fitted value uses
`(retained+.5)/(ambiguous_queries+1)`. Although the frozen protocol calls this a
"Jeffreys Binomial posterior mean", the three ambiguous queries from one
erased-final-update episode have exactly two old-value labels, and are not
independent Bernoulli observations. The expression is only a **Jeffreys-style
smoothed ratio** here; no independent-binomial interpretation, q posterior
certificate, or query-count-based sample-size claim is made.

Under uniform deletion among the six writes, one third of Selective episodes
have an erased original overwritten later (four certain queries), one third
have an erased original retained (three certain queries), and one third have
an erased final update (one certain and three ambiguous queries). The expected
certain-query count is `8/3`, while the expected number of truly available
queries is `10/3`. Certainty-only rejection therefore lies exactly on the
original 80% known-answer coverage boundary and can fail in finite samples.

R2 was designed after the R1 failure and before new R2 confirmation: accept
certain queries, reject erased-original unknown values, and accept a fixed
quarter hash subset of the final-update ambiguity class. The hash uses only
visible semantic state and the current query. The ideal accepted count is
`8/3+1/4=35/12`, correct accepted count is `8/3+(2/3)(1/4)=34/12`, giving
accepted correctness `34/35≈97.14%` and known-answer coverage `17/20=85%`.
These are law-level expectations, not a substitute for the original 95%/80%
observed confirmation gates. Hash fractions and conditional counts are reported.

This adapter bypasses neural content state; an ordinary parser can match it.
Passing this finite interface cannot qualify learned neural uncertainty,
analytical-core advantage, unknown generators, or general multimodal memory.
The implementation uses fixed observable prelude/update positions and treats
each unobserved slot as a registered erasure. It excludes resampling placeholders,
multiple missing writes, and a clock-subdivision equivalence claim.

# Frozen free-running network diagnostic

The script and protocol were committed before any new calibration path was
generated: c391e8b7d8ceada0765b6b9d454d2736b98e04dc.
Run `node research/rr_snn_v3/evaluate_network_calibration.cjs`.
The CLI verifies the executable protocol, exact fitted weights, original
learning-protocol freeze and teacher weights. It records the fitted artifact's
actual byte SHA-256. No optimization or model selection occurs here.

## Fixed design

The synthetic generating model and the frozen fitted model each generate 1024
complete two-neuron paths at H=4. Fresh seeds 60000..61023 do not overlap training,
heldout likelihood or development seeds. Four maturity/shock strata each contain
256 paired episodes. Both models start each pair with the same seed but consume
random numbers according to their own realized event histories.

The four prespecified summaries are total physical pulses, zero-pulse indicator,
terminal total budget and retained obligation count. The retained count is not
value-weighted utility. Each interval is a pointwise percentile interval from
10000 stratified bootstrap resamples of complete paired two-neuron episodes.
Uncertainty in the earlier training sample is not included. There are no
equivalence margins or acceptance thresholds.

Every path must satisfy finite state, nonnegative bounded budget, fee accounting,
log/count agreement and declared event/queue caps. Any failure suppresses the
complete-case estimates and intervals. Initial budget 6 plus at most one refill,
with a positive unit pulse cost, gives at most seven physical pulses per neuron
and fourteen per network in this fixed horizon. It is not a long-run stability
proof.

## Executed result

All 2048 paths completed with every declared invariant satisfied. The four overall
fitted-minus-generating differences are:

| Summary | Generating mean | Fitted mean | Difference | Pointwise 95% interval |
| --- | ---: | ---: | ---: | --- |
| Physical pulses | 6.4892578125 | 6.365234375 | -0.1240234375 | [-0.1533203125, -0.09375] |
| Zero-pulse indicator | 0 | 0 | 0 | [0, 0] |
| Terminal total budget | 1.740234375 | 1.85546875 | 0.115234375 | [0.0869140625, 0.1435546875] |
| Retained obligation count | 3.7783203125 | 3.7880859375 | 0.009765625 | [0, 0.0205078125] |

The frozen fitted model produces fewer pulses in each of the four strata. Its
larger remaining budget must not be presented as a demonstrated task benefit:
the model generates less activity. The retained-count statistic has no information
value weights and cannot replace the requested future-utility metric.

No zero-pulse episode was observed for either model. The degenerate empirical
bootstrap interval [0,0] does not establish that the true zero-event probability
or the probability difference is exactly zero.

The declared diagnostic is completed. Full calibration acceptance, long-run or
large-network stability, architecture superiority and real future-window quality
are not established. The observed generating-distribution difference is retained;
the model was not tuned on these results.

## Reproducible outputs

network_calibration_results.json contains all overall and stratum estimates,
the exact provenance and scope. Four network_calibration_rows_*.json files retain
every paired episode, both models' metric vectors and all unit resource audits.
The raw CLI output is also retained by the Node verification workflow.

# Independent native execution and cost review

Post-panel read-only audit. No model, policy, threshold, dataset, selection or sealed result is changed.

Verified 94 registered source/data identities, 38 selection-locked artifacts and 255 original audit inputs. Recomputed all 240 native stream/price/policy cases from labels, actual event clocks, quantized decisions, checkpoint chains, stopped-owner probes and native process counters.

Actual execution totals: 8273 reads and kernel/NDU steps, 594 successful native processes, 594 intentional rejected post-STOP requests; zero cache/native or float/Q24 disagreements. Quiet ticks perform no model or owner steps.

## Uncertainty scopes

| Candidate minus validation-selected ordinary reference | Actual native 16 streams | Cached 128 streams |
| --- | --- | --- |
| tabular_bellman | 0.31422917 [0.10633333, 0.50281354] | 0.11673958 [0.04353242, 0.19212826] |
| bellman_value_head | -0.06041667 [-0.14375000, 0.02291667] | -0.05736979 [-0.09132813, -0.02333333] |
| ordinary_action_head | -0.08166667 [-0.16500000, 0.00166667] | -0.06343750 [-0.09208333, -0.03479167] |

Intervals use 19,999 paired whole-stream bootstrap draws after averaging the three prices. They are post-panel descriptive intervals, without a multiplicity gate. The 128-stream interval must not be attached to native execution or net utility.

## Complete cost sensitivity

All 24 original tabular addendum values reproduce. A stricter new allocation adds the separately measured outer analysis (2.473637 CPU s) and addendum (0.057944 CPU s), charging the candidate 105.489869 extra setup CPU s while giving the ordinary reference free new setup. Historical backbone setup is shared and cancels. Native runtime difference is -0.04689567 CPU s/stream.

| Lifetime streams | Extra CPU / stream | Net utility difference at 0.01 utility / CPU s |
| ---: | ---: | ---: |
| 1 | 105.442974 | -0.74020057 |
| 10 | 10.502091 | 0.20920825 |
| 100 | 1.008003 | 0.30414914 |
| 1000 | 0.058594 | 0.31364322 |
| 10000 | -0.036347 | 0.31459263 |
| 100000 | -0.045841 | 0.31468757 |

Short deployments can lose after setup amortization. The positive original 1,000–100,000-stream grid is not a claim of positive net benefit for every lifetime or compute price. Native quality uncertainty is separate from unmeasured runtime/energy variability.

The direct planner result concerns one frozen v1 encoder and its finite task controller. The learned value head remains negative on the full cached quality panel. Neither result establishes an advantage for the v2 distributional content model or a foundation model.

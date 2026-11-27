# One timer-only shared diagnostic D2

This is one prospectively declared diagnostic, not qualification. T8 exit 1 and its 12.274880402s CPU budget failure remain valid. No candidates or test data were constructed, and no repeat or outlier deletion was performed.

Source `d0b99c25a26739c52e5695433625ac1b966f25a4`; execution `fb1436db11664603bb637ca0b1db95d129f08b1d`. Worker and protocol hashes match the pre-execution declaration. Both commands exited 0, with empty stderr; their actual stdout is retained.

Observed shared process CPU 2.123904049s + child CPU 0.404147000s = **2.528051049s**; wall 2.529363091s. The original function returned 2.522369819s using its coarser os.times child counter; this small clock/boundary difference is retained. Diagnostic setup/verification plus observed execution used 2.667236227s CPU; later report/hash persistence is administrative.

| Disjoint phase | Calls | CPU seconds |
|---|---:|---:|
| dataset_train | 1 | 0.165040730 |
| dataset_validation | 1 | 0.073146188 |
| matching_manifest | 1 | 0.019180490 |
| compile | 1 | 0.407529377 |
| decoder | 3 | 0.263366712 |
| pretrain_loop | 3 | 1.123304673 |
| validation | 3 | 0.034955967 |
| calibration_measure | 27 | 0.404635165 |
| export | 3 | 0.014895444 |
| Sum of disjoint spans | 43 | 2.506054746 |
| Explicit residual | — | 0.021996303 |

All timer and collection overhead during the observed phase remains in the total and residual; no component was subtracted.

| Seed | Decoder | Pretrain loop including RNG | Validation | 9 calibration calls | Export |
|---|---:|---:|---:|---:|---:|
| 11 | 0.106376143 | 0.356246264 | 0.013238096 | 0.097374896 | 0.004182651 |
| 23 | 0.077637244 | 0.480707257 | 0.010513220 | 0.062398594 | 0.006585510 |
| 47 | 0.079353325 | 0.286351152 | 0.011204651 | 0.244861675 | 0.004127283 |

All 27 complete measure calls (1,944 real outputs) are retained with their entire cost and per-row receipts in timing.json. Their CPU totals are: preparation 0.028245667s + service 0.357651426s + protocol/whole-call overhead 0.018738072s = 0.404635165s. Service splits into native/input/ledger 0.024662197s + actual decode/sampling/PNG/JSON/output-ledger 0.330768122s + remaining service bookkeeping 0.002221107s. summary.json retains each call separately.

A real localized outlier remains: seed 47, full mode, repeat 2 (ordinal 19) used 0.171677477s for the full call, including 0.169345460s output encoding/ledger. Adjacent full calls used 0.012215425s and 0.007934092s. The event is retained; these timers do not identify which encoding operation or environmental factor caused it. Seed 23 pretraining also used 0.480707257s versus 0.356246264s and 0.286351152s for the other seeds, without per-step instrumentation.

All three base NPZ files are byte-identical to T8 (and retained d1/T7). The compiled library SHA256 is also identical. Declared shared work is 3611371737 units.

The observed process had one thread before/after. Major faults, container throttling and memory.events deltas were zero; minor faults were 4,405. GC total was 4.259638ms, maximum 1.393105ms. Container counters include other processes and cannot establish causation. These observations do not explain the earlier T8 slowdown or exclude all unmeasured CPU/memory effects.

**Conclusion:** T8's multi-second slowdown was not reproduced. The diagnostic locates this execution's work and preserves a real output-encoding outlier, but proves neither a fix nor eligibility for another qualification attempt. No further experiment was run.

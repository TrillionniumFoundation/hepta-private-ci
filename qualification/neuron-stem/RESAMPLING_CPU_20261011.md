# Exact source-cluster resampling without Cell-row expansion

The previous selective reviewer charged its bootstrap budget by source clusters,
but expanded each sampled cluster back into every Cell observation on each draw.
The replacement computes seven exact integer counts per cluster once and sums
those counts using the same RNG calls and source ordering. All four ratios,
percentile intervals, finite-sample guards and source-count requirements remain
unchanged. Work is O(rows + clusters * replicates), not O(rows * replicates).
No new evaluator, acceptance profile, model or authority is introduced.

Three additional regressions compare exact point estimates and intervals with a
row-expanding oracle across twelve uneven cluster cases; verify row accesses do
not multiply with replicate count; and preserve budget rejection before sampling.
The full locally reconstructed qualification subtree ran 162 regressions with
no skips. Full-repository and hosted exact-head qualification are separate.

## Local CPU diagnostic, not a model speed claim

Original input: artifact 11697729546 from real-public-learning run 38127998329,
using the unchanged trained-arm learned-rejector acceptance records. The first
workload has 1400 records grouped by 800 original input hashes. The second repeats
those same records 16 times inside the same 800 groups; it does not create fresh
observations or establish statistical independence. Each benchmark used 200
bootstrap draws and three interleaved old/new executions in one local process.
The complete old/new report dictionaries were exactly equal in both workloads.

| Workload | Prior median CPU ns | Compact median CPU ns | Ratio |
| --- | ---: | ---: | ---: |
| 1400 original records | 80320241 | 53685741 | 1.4961 |
| 22400 same-source repeated records | 713892910 | 78386853 | 9.1073 |

Raw CPU ns, original: prior [80320241, 82966948, 80300964]; compact
[53685741, 54886241, 53129285]. Repeated: prior [746399246, 713892910, 691902859];
compact [78386853, 81035964, 78369753]. These timings cover this Python statistics
function only, not model inference, whole-run latency, independent outcome
collection or production throughput. Two hundred draws are a performance probe,
not a lowered acceptance-bootstrap requirement. No new real-world learning,
reasoning or NDU efficacy follows from this optimization.

Source Git blobs: prior 38cfc609d400b0e02aa9175b3135b3598492dd1c;
compact 6c366bc80d9d05ae64ecd74fb2f01bdb376bd8a9.

# Development profile of unchanged R16 execution

All eight frozen fits, three laws (HX/free/same-matrix HMM), full and anchored memory, IID and OOD, and value/fixed-read-refresh policies were executed. The predeclared deterministic development protocol produced 192 complete executions on 16 owner worlds, with zero failures. Real checkpoint writing, fsync, readback and restore were included. Actual executed actions were READ 754, REFRESH 708 and WAIT 40. Fixed-policy decisions exercise actual acquisition/refresh, while value policy executes the unchanged controller.

The profile enabled cProfile only around the unchanged execute function; world generation and law preparation were outside cProfile. The whole child wait4 receipt includes interpreter/imports, all work and artifact writing. Its 3.943517 CPU seconds are the non-overlapping outer quantity. Model preparation 0.064273 s and internally metered execute 2.934754 s are nested diagnostics and must not be added to that outer CPU. cProfile perturbs performance; these figures diagnose code structure and are not a new quality or deployment benchmark.

| Function/group | Calls | Profile cumulative seconds | Interpretation |
|---|---:|---:|---|
| execute |192|3.082|Complete profiled executor|
| choose / values |794|1.609 /1.606|About 52% of execute time; nested, do not add|
| ordinary / anchored _values |6640 /6624 total|0.835 /0.762|Recursive Bellman expansion dominates controller work|
| project |15162|1.057|About 34% of execute; nested inside planning and memory|
| allclose |24232|0.817|Repeated probability contract checks are a major part of projection cost|
| _belief |11562|0.576|Mostly full-projection validation, nested above|
| expm |2190|0.296|Only about 9.6%; matrix-only speedups have limited whole-executor headroom|
| Planner.__init__ |1152|0.237|Only about 7.7%; caching setup alone is unlikely to achieve 10% whole-execution gain|
| fsync |192|0.165|Contractual checkpoint IO; retaining it matters to full cost|

The useful exact optimization target is repeated Bellman expansion and its duplicate validation/projection overhead. Batch equal-horizon WAIT/READ successor beliefs together, share identical `p @ P1` computation, or directly evaluate terminal children while preserving every observation branch, probability, fee, shape and original argmax tie rule. Cache immutable planning coefficients only as a secondary measure, accounting for preparation and resident memory. Removing checkpoint IO or silently changing validation/rare-branch/tie semantics would not be an equivalent comparison.

`executor.prof`, readable cumulative/internal top 50 tables, all 193 raw function statistics, per-execution raw records and actions, source identities, source script/protocol, stdout/stderr and full child receipt are retained. This is read-only baseline development evidence and cannot establish candidate benefit or independent HX contribution.

# R22 shared validation: exact behavior, failed resource qualification

The shared scalar-one validation fastpath preserved every retained timed action,
query field, memory checksum, receipt/history and final durable wire hash.
It reduced measured actor CPU in aggregate, but it did not pass the registered
per-group software or adoption gates. No production activation is qualified.
Ordinary baseline code benefited more than the optimized planners, so this is
not evidence of an exclusive analytic-core contribution.

The exact source was published and read back at
`5a8472045183fa638e77ac8f2ad903f3b00e3d06`, with manifest
`cb65df2e75c2226c5441b9f4a293e8fe0ae8305a51cc3f4a5a61b6fdede160d6`.
All 61 frozen input hashes remained unchanged. The source/protocol preparation
race concerned two reviewer files, was caught before publication or registered
execution, and is retained in `PREPUBLICATION_FREEZE_RACE.json` and
`FREEZE_PREPARATION_RECORD.json`. There was one fresh fixed resource campaign;
no failed group was excluded or rerun.

The implementation changes only three scalar-one, zero-relative-tolerance mass
predicates after the original FP64 coercion and shape/finite/negative guards.
The reduction operands, order, absolute tolerances and inclusive comparisons
remain the same. Packed/anchored method bodies and their matrix objects remain
the original ones; the executor body, R21 typed admission and R20 persistence
functions remain unchanged. `PROOF.md`, both diffs and the independent review
describe the exact scope, including inherited legacy coercion behavior.

The registered independent checker passed 634 actual boundary/type/byte/alias
cases and 23 static contracts. It also bound the installed NumPy 2.3.5 predicate
source fingerprints. The fresh cold campaign passed 117 worker processes,
54 SIGKILL lost-reply query cuts and nine old semantic references, using the
new law and full/packed/anchored memory. WAIT→READ and REFRESH→STOP controls
preserved already-paid history. Every complete reference made six file fsyncs
and six directory fsyncs; continuation made exactly the remaining pairs. Atomic
rename, checksum verification, two readbacks, typed restore and the final
checkpoint comparison remain charged. This qualifies the declared trusted
single-writer Linux query boundary, not suspended external effects inside a
query, physical power loss or production ownership.

The independent checker retains one NumPy overflow warning from declared
invalid `sum_overflow` restore controls. All 18 retained controls with that name
rejected with matching old/new `ValueError` outcomes; no input was repaired.
Its stderr remains byte-exact. Formal resource, cold and raw-audit stderr were
empty. The earlier development overflow warning is likewise recorded separately.

The resource campaign used all eight original frozen fits, three cores, full
and anchored representations, and all four planners. Each fit used 32 fresh
worlds (16 IID and 16 OOD), shared across paired arms with randomized preparation
and execution order and independent charged caches. There were 12,288 timed
actors, 1,536 separate memory probes and 256 unique worlds. Timed old/new arms
and all four variants were exactly equal within each model/world. Probe
outputs were not retained as additional quality observations. The frozen
stdlib audit reconstructed 124,733 checks from the raw records and passed.

| Planner | Old CPU s | New CPU s | New/old | Failed software groups /48 |
|---|---:|---:|---:|---:|
| ordinary baseline | 31.063162 | 25.210180 | 0.811578 | 2 |
| R18 | 24.528690 | 23.373834 | 0.952918 | 43 |
| R19 | 25.474881 | 24.127296 | 0.947101 | 45 |
| R20 | 24.270204 | 22.846784 | 0.941351 | 44 |

Actor CPU includes each arm's model/cache preparation and all six durable
query commits/restores. Across the actual measured arm population, old/new
actor CPU was 105.336937/95.558095 s (ratio 0.907166), saving 9.778842 s.
These aggregate values do not override the following registered failures:

- The additional software CPU≤0.90 and traced-peak≤1.0 gate failed 134/192
  groups: 128 failed CPU and 21 failed peak, with overlap. Eight groups were
  slower than their old counterparts. CPU ratios ranged 0.755508–1.134338;
  traced-peak ratios ranged 0.988795–1.001932.
- The inherited R20/shared-baseline CPU≤0.90 gate failed 27/48 groups.
  Ratios ranged 0.814145–1.003375.
- The inherited R20/R18 CPU≤1.0 and traced-peak≤0.90 joint gate failed
  17/48 groups, all on CPU. CPU ratios ranged 0.863109–1.068602; all traced
  peak ratios were within 0.683085–0.855863.

`ACCEPTANCE.json` retains every failed group, without a pooled-mean override.
These are the inherited thresholds tested on a new 32-use all-query profile;
the failed R20 results and original historical/1,000-use qualifications remain
unchanged. The ordinary baseline's larger shared-validation gain narrows the
optimized-planner comparison rather than establishing a model-specific gain.

Per-arm measured complete-episode throughput, including preparation, changed
from 40.84→47.43 episodes/s for the ordinary baseline and 49.82→50.85 for R20.
All group latency p50/p95 and wall/throughput values are retained in the raw
group summaries. These are serial six-query actor measurements in a shared
environment, not a production SLA. The complete resource child consumed
278.758955 CPU s and 341.344343 wall s with combined peak RSS 82,492 KiB;
that RSS is not a per-arm memory ratio. The memory gate uses four separate
`tracemalloc` probes per arm/group. CPU affinity was exactly `{8}` and all
declared BLAS thread variables were 1. Other project jobs used CPU0–7, so
shared disk/cache, frequency and scheduling interference remain possible.

R22's nonoverlapping recorded CPU lower bound is 339.517122 s: profile
2.962058, development 17.309760, independent checker 0.524629, cold controller
and waited children 39.466214, resource child 278.758955, and separate raw-audit
body 0.495506. Inner actor/profiler/checker timers are not added again. The
previous 941.053004 s remains charged, including the original 141.098189 s
investment, producing a cumulative recorded floor of 1,280.570126 s. Even the
actual shared software saving of 9.778842 s is far below the earlier floor;
the new R20/shared-baseline actor saving is only 2.363396 s. The full investment
gate is false. Unknown supervisor, bookkeeping, publication and review costs
remain null in `COST_LEDGER.json`, as do GPU/energy/production costs. There is
no extrapolated amortization or actual 1,000-use claim for this campaign.

The earlier profiled 96-actor hotspot and 768-timed/96-probe development trial
remain separate evidence. Development's 0.892 aggregate ratio was a reason to
freeze the fresh test, not a replacement for its weaker result. The reported
continuous peer review is marked as reported-only without raw/process receipts;
the registered 634-case independent audit supplies the retained verification.

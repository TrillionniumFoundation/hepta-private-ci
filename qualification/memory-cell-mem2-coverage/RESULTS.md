# MEM-2: measured source-matched replay order controls

**80/80 native replay windows completed. Structured replay is not promoted.**
The final replay matches source/version multisets, serialized sample bytes,
emitted update-request bytes, initial native state, update count and teacher
cost. Structured-minus-uniform stable-A accuracy is **+2.5 percentage points in
the dynamic B window and −15.0 points in the stationary B window**. This does
not establish a consistent structured advantage or explain the historical
MEM-1 gap causally. Scientific qualification is **HOLD**; adoption is **NoUpdate**.

## Exact execution and scope

The repository base is `d13761500aba28634238ec23fb1d62eae5cf81ec`. The new Python
files are individually SHA256-bound in each campaign manifest; this base SHA
alone does not identify the uncommitted experiment overlay. The evidence bundle
retains the exact executed Python bytes for both the initial and final runs.

The native binary was **newly built**, using Rust 1.96.0 and an isolated exact
source projection of `hepta-memory-retrieval`, `hepta-cognitive-types` and
`hepta-types`. All 66 projected source files are individually bound. The
resolved 24-package identity set is a subset of the original repository lock;
every registry name, version, source and checksum matches. The workspace
membership/manifest transformation and pruned lock are retained. This is not a
full-workspace build or test qualification.

| Item | Observed result |
| --- | --- |
| New native binary SHA256 | `e8b95e5b88bfbbdd962812d800f2617daa924aa237dcdeba45b71697cad0713d` |
| Native binary size | 23,616,504 bytes, unoptimized debug build with debug information |
| Offline build | Exit 0; 13.08 seconds |
| Focused Python controls | 6 passed in normal Python; the same 6 passed under `-O` |
| Final campaign | 10/10 parent trajectories; 80/80 fork windows; no failed/missing windows |
| Fork replay work | 5,120 updates and 1,600 evaluation queries |
| Matched pairs | 20/20 exact state/data/byte/update/teacher matches reconstructed |
| Final campaign elapsed time | 15.92 seconds, including orchestration and parent trajectories |
| Native kernel behavior | Actual Rust execution; no Python numeric reimplementation |

No new Rust test suite was run because the Rust implementation was unchanged.
The build and actual experiment do not imply that all repository CI checks pass.

## Registered comparison and results

The [protocol](PROTOCOL.md) fixes five synthetic stream seeds, two owner modes,
and two sleep boundaries. At each boundary the unchanged MEM-1 `fast_uniform`
trajectory supplies a common pre-sleep checkpoint and eligible pool. Four
workers start from that exact state; their outputs never replace the parent.

The legacy forks retain the original selection **rules**. They share a frozen
state and a newly specified selector seed, so their numbers are not reruns of
the historical full-trajectory MEM-1 table.

### Stable-A accuracy after the B replay window

Each entry is the descriptive mean over five seeds, with eight fixed stable-A
probes per seed (40 probes per condition/arm).

| Common-state fork | Dynamic | Stationary | Mean distinct replay sources, dynamic / stationary |
| --- | ---: | ---: | ---: |
| Legacy uniform selector | 80.0% | 80.0% | 21.6 / 23.0 |
| Legacy structured selector | 87.5% | 85.0% | 11.6 / 12.0 |
| Coverage-matched uniform | 85.0% | 90.0% | 22.0 / 24.0 |
| Coverage-matched structured | 87.5% | 75.0% | 22.0 / 24.0 |

The matched comparison controls the exact multiset of complete records, not
only the number of sources. Every eligible record receives either the floor or
ceiling of `64 / pool_size` repetitions. The structured arm chooses priority
order only among its remaining quotas.

| Seed | Dynamic uniform | Dynamic structured | Stationary uniform | Stationary structured |
| --- | ---: | ---: | ---: | ---: |
| 0 | 87.5% | 75.0% | 75.0% | 87.5% |
| 1 | 100.0% | 100.0% | 87.5% | 75.0% |
| 2 | 75.0% | 87.5% | 87.5% | 75.0% |
| 3 | 87.5% | 100.0% | 100.0% | 50.0% |
| 4 | 75.0% | 75.0% | 100.0% | 87.5% |

At A1, matched uniform scores 100.0% and matched structured 97.5%. Dynamic and
stationary A1 share the same initial regime and are not ten independent seeds.
No confirmatory test or practical-effect qualification is claimed from five
synthetic streams. The 80 windows are not 80 independent model-training repeats.

## Cost and evidence accounting

Each matched window has 64 updates, 26,624 replay-kernel multiplications and
zero teacher calls, bytes or multiplications. It also makes 28 elementary
predictions for the 20 panel queries, accounting for another 3,584 kernel
multiplications. Complete serialized replay-record multisets and actual emitted
update-request byte counts match within each pair.

These equality checks do not equalize selector CPU time, IPC, RSS, energy or
money. Profiles execute in a fixed order; observed wall times are retained but
are not causal speed comparisons. Parent trajectory wall times include all
four added forks, while its original kernel counters exclude fork work; parent
and fork accounting must therefore be reported separately. Neither timing table
can be substituted into the earlier MEM-1 cost table.

The retained reconstruction verifies all planned identities and terminal
statuses, frozen owner generation, source exposure/last-observation steps,
checkpoint bytes, source and binary identities, exact replay plans, provenance,
request-byte accounting, native operation traces and final checkpoint hashes.
Expected query answers are reconstructed from seeded owner facts. Missing
knowledge about a still-valid source counts as an incorrect abstention; it is
not relabeled as a correct refusal. Revoked/out-of-scope queries retain their
separate panel. The paired-constituent panel is not relational reasoning.

This checks consistency of retained evidence. It does not authenticate an
untrusted executor or provide production owner authority.

## Repairs, initial run and limits retained

The initial 80-window campaign completed in 19.12 seconds with the same numeric
outcomes. Independent review then found that a later parent-trajectory failure
could omit an earlier successful window from the top-level summary. The final
runner persists the entire planned roster before execution, marks each window
running/completed/failed, and retains earlier successful windows in `finally`.
An injected B failure verifies that A1 results survive and unstarted windows
remain visible. The final same-source campaign and reconstruction both pass.
The two campaigns are software-verification reruns of the same seeds; they are
not pooled as ten seeds or new independent confirmation evidence.

The first dependency-cache preparation stopped on absent optional WebAssembly
crates; no native build had started. That preparation failure is retained.
The subsequent actual Linux build resolved entirely offline and all resolved
dependencies matched the frozen lock. A prior Hepta read-only ROG archive probe
did not return a process identity to this caller; its remote outcome is unknown,
and it supplies no execution evidence for this campaign.

The original [MEM-1 results](../memory-cell-mem1/RESULTS.md) remain unchanged.
Exact-key retrieval is still the established strong baseline from that task;
this experiment did not rerun or replace it. Neither the neural matrix nor the
structured scheduler enters a new product-critical path. Real task retention,
independent evaluation, owner integration, cross-document memory and learned
relational composition remain separate gates.

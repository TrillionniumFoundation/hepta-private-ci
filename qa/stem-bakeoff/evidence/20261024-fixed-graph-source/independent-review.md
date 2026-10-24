# Fixed six-head graph benchmark: independent source review

Reviewer: `/root/codex_architecture`. Review is local and read-only with respect
to the experiment implementation. No remote worker, original graph inference,
model service or task-label access was performed for this review.

## Current review outcome

The revised source candidate with protocol
`cae0f27b93b2e4bf00b80b16916882dbc8523ce05d41e10e95f87e1546ba2883`
is cleared by this independent source review. All five concrete findings below
are addressed, and no new source blocker was found. This clearance covers the
frozen implementation and its declared measurement scope; it does not establish
that the native adapter, actual cgroup enforcement or real benchmark has run.
Those remain the explicit pre-run gates below. This document is not a substitute
freeze receipt.

The initial full source read used the superseded protocol
`159ce3a0c01b4887b488b46d4072835ff1b2363b292712f3eb20ec5e25a7b654`.
That version was held before execution while the findings were corrected.

The reviewer independently recomputed the revised protocol and five runtime
hashes, checked equality with `verification/final-v2.json`, and compared each
file against the exact copy under `verification/source`. The recorded test log
hashes also match their actual bytes. The logs report 18 Python tests and 8 Node
tests passing; the reviewer did not rerun them or execute original graph data.

| File | SHA-256 |
|---|---|
| `cell_graph_worker.py` | `bb9a6ddc30cc267d22a530e9486e6590cdef15247d1546905b4a051e8eed8358` |
| `cell_graph_benchmark.py` | `7d77c2c0ba63013ac22bd996ee3c612d0d086f9edacfffe29d58f5111ad8bd65` |
| `cell_graph_reduce.py` | `5ac4bba925d161f8fe3eda5c5c036207d7182ec84733f6c1f310befa0da54efb` |
| `cell_graph_report.py` | `7a5b7dfaccda71143e0de6b1087d2744bc5ee16e14d0e146f06b77734621544d` |
| `cell_graph_owner.js` | `a8f1e561f3bff60b0247351c27619a874403006cd44ee40035b2cc3c8a1de112` |
| `python-final-v2.log` | `8ec094bad4824f62d70e7b26e70c234dd76eb4d8ca2600743c09bd74f06c2312` |
| `owner-final-v2.log` | `6a09741b5c9e54a6a5d7647890eb280f72724d9a7654c82344bd029e0a68ae34` |

## Findings delivered before any graph execution

1. The owner checked the 60-second collection budget before each native read,
   but a final awaited read could finish after the limit and still qualify.
   Recovery had the same issue. Require a post-call deadline admission check
   while retaining the completed call and measured costs. A rejected result
   does not by itself prove an underlying uninterruptible native call stopped.
2. Recovery event validation was weaker than primary validation. A nonempty
   event list did not prove one original start, bounded original status/read
   calls, successful native provenance or valid after-census intervals. The
   recovery report must validate those facts explicitly.
3. Recovery compared absent fields using `.get`; two missing stdout fields
   could compare equal. Its original reference must be an authoritative
   completed, successful, full-output collection with valid exact bytes/hash.
   An incomplete primary cannot become a successful recovery reference.
4. `reducer_cpu_ns` started after module/NumPy imports and CLI setup, although
   its name and cost explanation appeared to describe process CPU. Either
   measure executable-entry/import and body separately, or name/report it as
   function-body CPU with the missing import/startup interval explicit.
5. Failed-job cleanup called `adapter.reconcile` outside the instrumented API
   path. Its wall time was inside the critical path but its native calls and
   provenance were absent from API counts, and reducer summaries dropped the
   cleanup object. Retain a separately bounded cleanup lane and its costs;
   do not silently exclude it or charge nested durations twice.

The revised owner checks collection and recovery deadlines after awaited calls,
retains completed native events even when late, and separately records bounded
cleanup calls inside the enclosing critical path. These checks reject late
observations; they do not interrupt an uninterruptible API promise. Recovery now
requires complete original stdout, exact two-line worker validation, original
created provenance, repeated arguments and reused job identity, plus a bounded
after-census event sequence. Reducer entry and body counters are named separately,
with the remaining interpreter/receipt-publication costs explicit.

The resource-receipt extension reads only the known self cgroup membership and
the corresponding `cpu.max`/`memory.max` files. The worker checks the exact
declared local ceilings before inference, and the reducer verifies the retained
numeric ceiling receipt. It distinguishes those ceilings from effective capacity
under unknown ancestor caps, affinity and host load. The fixture test injects
the own-limit reader for its cold subprocess; it is not a native cgroup proof.
Equal aggregate local ceilings are an operational control, not proof of equal
physical capacity. Numerical arithmetic and the fixed tolerance are unchanged.

One nonblocking terminology remnant in the frozen protocol calls the CPU sum an
aggregate reservation. Publication must describe it as the sum of configured
ceilings, not guaranteed or reserved CPU capacity. Failed evidence and raw native
receipts must remain available alongside the report, including costs that are
not projectable when a reducer or collection record is absent.

## Source findings that support the design

The exporter opens only the original registered protocol, shared feature
projection and six original warmup checkpoint pairs. It verifies full saved
state through the original `CellTrainingState` implementation, then exports the
readout arrays. It does not choose controlled-condition heads or read task
outcomes. The six seed/head identities, all 480 rows, shards, equal-weight
reduction and all six block permutations were fixed before benchmark output.

The standalone worker validates exact portable little-endian float64 bytes,
features/head shapes and hashes. Its copied readout arithmetic corresponds to
the original linear/gated normalization, clipping, logits and softmax. Existing
constructed tests compare the six original computations, including clipping and
a zero row; this review has not re-executed those tests or original inference.

Reduction restores canonical head indices before stacking and taking the
float64 mean. Functional reference is only `b0-A`; its absence blocks a
qualified comparison. The reporter preserves all 18 scheduled graphs and
withholds paired summaries if any graph is invalid or noncomparable. Known
completed sibling costs remain visible when another node fails, and unknown
failed-process costs are not filled with zero.

The primary C-minus-B contrast holds worker count/sharding fixed while changing
the actual placement/host/service stack. C-minus-A and B-minus-A also include
process/sharding/parallelism differences. Heterogeneous CPUs and numerical
environments prevent a pure network-latency interpretation. One-thread NumPy
under equal aggregate declared CPU quotas does not imply equal used CPU.

Six paired blocks support the stated descriptive raw differences and
median/range summaries. They do not establish tail latency, a population
confidence interval, learned communication, cell growth, native-agent
competence or general intelligence. Per-process RSS peaks and head array sizes
must not be promoted to simultaneous memory or whole-system net benefit.

Primary starts require an authoritative newly-created receipt; recovery must
reuse the exact original start arguments/key/job/output after the primary
census. Returned historical worker CPU/RSS must not be charged as new work.
This is completed-job lookup/read idempotency, not crash or power-loss recovery.

## Remaining execution gate

The actual native adapter, physical-host evidence, worker executable/environment
snapshots, exact self-resource receipts and fixed reducer placement remain
separate pre-run evidence. Source-only fixture success is not an actual native
benchmark result. The root operator owns those bindings and execution.

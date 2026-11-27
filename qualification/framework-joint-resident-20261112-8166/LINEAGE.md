# Shared computation: exact lineage and integration boundary

Audit anchor: current ordinary-owner assembly #6006 at
`3c8dabe46598599e91b2b8b80081e09069ff9426`.
Comparisons below are GitHub's exact commit comparison metadata, with each
historical head as base and the current anchor as head.

| Historical PR | Exact head | Actual common ancestor | Current-only / historical-only commits |
| --- | --- | --- | --- |
| [#4938](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4938) | `f09dea504916d551e13fe36752dd1e833bcaa51b` | `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75` | 662 / 11 |
| [#2237](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2237) | `367aeccf1d698607d3a99a59ab423fbffae1d3b4` | `78fdb0cf8537e3a84fc6e0a849707559c80881e8` | 1578 / 950 |

These counts describe ancestry, not the number of commits that must be copied.

## Resident slice selected from #4938

The historical resident caches immutable model/public tensors and initial
encoding. It serializes exchanges, has bounded frames and capacity-one channels,
and permanently poisons a session after uncertain submission. It does not provide
Joint tensor microbatching, a fair global scheduler or an automatically selected
product pool. Its historical descriptor integration was explicitly incomplete.

Current #6006 has a real production route from Agentd main to the pinned
generation bootstrap descriptor, opened-file worker construction and the existing
controlled generation port. It also has newer observed V2 behavior: owner-bound
delivery contracts, remaining budgets, legal output portfolios, planning receipts
and autoregressive text state. Substituting #4938's proposal file would lose those
newer semantics.

[#6060](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6060)
selectively adapts that resident slice to the current owner chain. It retains the
current V2 proposal body, extracts immutable loading/initial encoding, selects
resident V1/V2 profiles through the existing descriptor, and preserves current
no-follow file acquisition, held-inode identity and mounted-procfs resolution.
The cache binds the complete manifest digest; each request still carries its own
state, prefix, owner contract and digest.

The original imported files are fixed by these Git blobs:

| File | Original blob |
| --- | --- |
| Neuron transport | `98c28cc59494fd2c1e4b483299ea8754db5b1399` |
| Neuron bounded IO | `6b71780f9e783950d95256da3bf9cc6d480c6758` |
| Neuron resident process tests | `9167b8959de084cb4382d4ae2504a07c2d455c3e` |
| Helper resident protocol | `3db0953694350e0801ceead6de3433e4b4c95e29` |
| Helper resident tests | `1301e58a594f73a5ebe6ca496275f445f6d914cf` |

Current source at this audit snapshot is
`4ae6bbe94ef5be31401ac31b4a6fdeb5128d548f`,
tree `049b6be2b572e61adeca0764f78e0ab312975fc0`.
Its native run 43130589962 is queued at the 2026-11-12 00:56 UTC observation;
this is not a qualification pass. The original 340f43b candidate's three native
jobs were cancelled before any steps when superseded. Independent review found
and fixed a V2 zero-clock path that could otherwise convert unavailable time into
a terminal Rejected proposal. The correction preserves typed Unavailable for
both one-shot and resident profiles.

Resident RSS lifetime reservation, global fair memory allocation, cross-Agent
pool selection and tensor microbatching are still separate work. The journal's
native headroom is serialized journal/result capacity, not a resident RAM budget.

## Why #2237 is not a seven-file production batch integration

The seven-file PR is an incremental Arc enqueue change on an older branch with a
larger prerequisite stack. Direct file/definition inspection at #6006 found the
following required pieces absent:

| Owner | Historical prerequisite absent from the current anchor |
| --- | --- |
| inference core | `microbatch.rs`, `shared_feature.rs`, `stem_feature_binding.rs` |
| worker host | `batched_neuron.rs`, `original_evidence_neuron.rs`, Stem batch preview, physical batch driver API |
| contracts | `FinalUseAuthority::claim_batch`, `with_verified_effect_batch` |
| shared types | `PhaseMetricEventV1`, `PhaseMetricKindV1`, `PhaseMetricSinkV1` |
| evidence | `metrics_group_commit.rs` and `metrics_sink.rs`, plus their Agentd exports |

Historical reference blobs include batch worker
`29237eab79b17c0e4d09fbf356d02420f8b3f515`,
original evidence wrapper `b5e28a719038c1a158ce31c347d0ab8dd3ae2844`,
scheduler `26d8f0241594d9fffb907fe69fe34a551de99e82`,
shared feature buffer `13101c9e279d58d36c61488ae30fbc3c4ea70407`,
evidence group commit `8faa8b04833ed9f02f1b645b834adc4a97125082`,
and evidence sink `2b5028ace8038d4e0debe02c9c6ac51b884ecc7a`.

More importantly, the original wrapper's first non-test gate
`require_original_control_v1()` unconditionally returns
`UnverifiedOriginalControl`. Its startup also refuses any nonempty committed
WAL with `PriorHistoryNeedsReconciliation`. These are explicit incomplete
Control/CNS provenance and recovery boundaries; copying modules or supplying a
generic trait object cannot establish them.

The original batch regression source
`511aa35936e23109fa5e4852e45e82b85ae4efd6` uses `NativeTestDriver`, with
synthetic results and a counted invocation. That exercises signed batch mechanics
but does not establish a loaded production model or real tensor batch backend.
The original API still materializes one owned feature vector immediately before
the authorized driver boundary. It is not an end-to-end zero-copy claim.

The current anchor already has its own `CellBatchQueueV1` and
`AgentdCircuitCellOwnerV1::execute_batch` path, with per-Cell durable admission,
queue/deadline checks, receipt membership validation and individual commits.
A future real batch integration should complete that current controlled port
with an actual admitted numerical backend and explicit fair/resource budgets,
then qualify durable request recovery and authenticated live Control/CNS checks.
It must retain unknown outcomes and original effect ownership. Removing the old
production denial or importing all 950 divergent commits is not an integration
plan.

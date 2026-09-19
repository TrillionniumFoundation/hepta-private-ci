# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: authoritative read boundary, existing SQLite owner provider and Agentd product caller are source-composed; exact-candidate qualification and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-read`.
Packages: `MEM-READ-1-SNAPSHOT-PORT`.
Product composition: `composed`; production writer: `not_applicable_read_only`.

The cognitive-read crate owns the read contract and deterministic projection only. `hepta-memory` is the delegated durable owner adapter and `hepta-agentd` is the named product caller. These delegated callsites do not create a second memory writer or widen the module's exclusive source root.

## 2. Public operations and contract details

The product read contract is `read_authoritative(provider, now, acquisition_request, read_request) -> AuthoritativeReadResultV1`. Agentd retains the resulting authoritative guard server-side and exposes only snapshot/read digests to the worker. The actual model consumer calls `CognitiveContextFinalize` after durable dispatch intent and immediately before provider `TurnStart`; Agentd then consumes the guard once and runs `revalidate_authoritative_read(...)` against a freshly reacquired owner cut.

`SnapshotAcquisitionRequestV1` binds request identity, scope, purpose, the expected consumer-profile digest, minimum memory/source/tombstone/knowledge frontiers, minimum knowledge-graph generation, authority epoch and deadline. `AuthoritativeReadGenerationVectorV1` binds the exact owner-observed values plus a consumer-profile digest. `AuthoritativeSnapshotV1` binds that vector to one immutable `CognitiveSnapshot`, provider identity, acquisition time, short lease and snapshot receipt digest.

The lower-level `read_v2` typed projection remains in `src/v2.rs`, but it is not re-exported from the crate root. Product callers therefore do not obtain a weaker public path that validates only caller-supplied snapshot bytes.

No mutation, SQL-writer handle, runtime authority or external-effect grant is exposed. Authoritative read results retain `DENY_ALL` authority.

## 3. State records and transaction design

The cognitive-read crate owns no durable state. The real owner is the existing `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`.

`CognitiveStore::lane_c_snapshot` reads heads, immutable revisions, citations and owner frontiers in one SQLite transaction and materializes a `DurableCognitiveSnapshot`. A `LaneCAuthoritativeSnapshotProvider` can only be constructed from that immutable cut and is bound to the acquisition-request digest. It cannot re-read independently moving `visible()` and `fetch()` state.

The read-specific generation vector intentionally excludes prompt, compact, model, tokenizer, template and tool-schema generations. Those values are owned and consumed elsewhere; fabricating placeholders for them would create a false authority proof. The cognitive vector contains only the owner/host state this read actually consumes and can revalidate truthfully.

## 4. Deterministic algorithm and scheduling

1. Agentd validates the bounded query/result request and captures one host time.
2. StateControl supplies the current fleet lifecycle generation as the host authority epoch.
3. The SQLite owner acquires one immutable Lane-C cut.
4. Agentd derives a consumer-profile digest from the exact read request, query, limit, body generation and ranker-presence bit.
5. The owner cut constructs a request-bound `LaneCAuthoritativeSnapshotProvider` with a short lease.
6. `read_authoritative` validates acquisition, scope/purpose, authority epoch, all declared frontiers/generations, lease, snapshot integrity and receipt binding, then invokes the internal deterministic `read_v2` projection.
7. Retrieval/ranking may use current indexes, but only exact revision/content digests admitted by the frozen authoritative result may cross into the context payload.
8. Before publication, Agentd reacquires the owner cut and calls `revalidate_authoritative_read`. Any changed owner snapshot/vector/frontier, expired original lease, provider mismatch or digest mismatch fails closed.
9. StateControl refreshes fleet generation after I/O, fences the response if the authority epoch changed, and registers the exact guard in a bounded short-lived one-shot registry keyed by its read binding digest.
10. The native worker creates the provider thread and syncs durable dispatch intent without sending `TurnStart`.
11. Immediately before `TurnStart`, the worker calls `CognitiveContextFinalize` with only the published snapshot/read digests. Agentd removes the retained guard before async work, reacquires the current owner cut, validates the same host epoch/frontiers/vector/original lease/receipts and optional ranker witness, then returns the exact finalized digests.
12. Any finalization failure records a durable local pre-`TurnStart` stop and the provider turn is not sent.

The authoritative result binding digest, not the raw `read_v2` receipt alone, is passed into context planning and identifies the retained final-use guard. Finalization is an immediate pre-effect observation, not a write-blocking lease over subsequent memory writes.

## 5. Capacity and performance profile

The native projection enforces its existing result-count and encoded-byte caps. Agentd currently requests at most 1 MiB from the read port and independently caps the final context JSON at 24 KiB with a caller result limit of 1..=4.

The product authoritative lease is 5 seconds and the acquisition deadline is 10 seconds. Lease expiry is a hard unavailable failure; a slow request never silently widens the validity interval. The Lane-C owner retains its existing materialization bounds for revisions, citations and source rows.

These are source constants/constraints, not target-host latency measurements. External performance qualification remains separate.

## 6. Concrete verification cases

- READ-01: a source-frontier advance after the context is issued but before final model-dispatch revalidation returns fail-closed rather than allowing stale context to reach `TurnStart`.
- READ-02: a committed tombstone/revocation in the same post-publication window returns fail-closed rather than allowing the already-computed content to reach `TurnStart`.
- READ-03: scope, purpose or host authority-epoch drift rejects the authoritative envelope/result.
- READ-04: memory, source, tombstone, knowledge-fact or knowledge-graph minimum-frontier drift rejects acquisition/revalidation.
- READ-05: lease expiry, deadline expiry, snapshot mismatch, generation-vector digest mismatch or receipt mismatch rejects; no fallback to raw `read_v2` occurs.
- READ-06: identical current owner state may produce a fresh reacquisition receipt while still validating the original authoritative result; changed vector/snapshot may not.
- READ-07: exact/prefix typed projection remains deterministic under input permutation and respects missing/stale/resource-cap semantics.
- READ-08: a future backend cannot be product-composed unless it first materializes one immutable owner cut from which its authoritative provider is constructed.
- READ-09: a finalization receipt is one-shot; replay, expiry or host-epoch drift rejects and cannot reuse the same guard.
- READ-10: failed finalization after durable dispatch intent releases the local slot with no provider terminal claim and no `TurnStart`.
- READ-11: strict exclusion of a memory write after finalization returns is not claimed; that stronger linearization requires a writer-participating consumption lease/fence.

Source identities for these cases include [authoritative tests](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs), [Lane-C owner tests](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [Agentd cognitive-context tests](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs) and [Agentd product E2E](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs). These are executable source tests; a pass claim still requires the exact-candidate workflow receipt.

## 7. Integration, rollback and capability ceiling

The product path is deliberately one-way: SQLite owner cut -> request-bound authoritative provider -> `read_authoritative` -> bounded context construction -> publication revalidation -> one-shot Agentd guard -> durable native dispatch intent -> `CognitiveContextFinalize` -> fresh owner/authority/ranker revalidation -> provider `TurnStart`.

There is no production escape hatch to a crate-root `read_v2`. Rollback of this change restores the predecessor product path only as an explicit code rollback; it must not be represented as equivalent to the stronger authoritative contract.

Immediate correction/deletion/source-frontier changes remain effective because final owner-cut equality is rechecked. Host lifecycle revocation remains effective because the fleet generation is both digest-bound into the read vector and compared after asynchronous I/O. Read outputs retain `DENY_ALL` effect authority.

External gates remain non-self-certifiable: exact-candidate CI, merge-candidate qualification, independent semantic review, target-host qualification, operator acceptance, canary, promotion and release are distinct from source composition.

## 8. Current native implementation

- **Implemented entrypoints:** `read_authoritative` in [codex-rs/hepta-cognitive-read/src/authoritative.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative.rs); `LaneCAuthoritativeSnapshotProvider` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs); `cognitive_context::issue/finalize` plus the one-shot guard registry in [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs); and the pre-`TurnStart` native consumer gate in [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs). These form the named source-composed production path.
- **Internal primitive:** `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs) implements deterministic typed projection and is intentionally not re-exported at the crate root.
- **State and recovery:** `DurableCognitiveSnapshot` is an immutable, digest-only historical SQLite cut. The request-bound provider binds only actual read-owned frontiers plus purpose/profile/authority epoch. Agentd retains the exact guard under a bounded original-lease TTL and removes it before final async validation. Final model dispatch reacquires the owner cut, validates the original lease/receipt/vector, requires the same StateControl lifecycle epoch, and cannot replay the guard.
- **Source tests:** [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [codex-rs/hepta-cognitive-read/src/authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs).
- **Implementation and operating reference:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- **Revision-fence status:** exact owner cut/revision/time revalidation before publication and again at the native pre-`TurnStart` final-use gate is implemented and product-wired.
- **Broader authoritative status:** scope/purpose, authority epoch, memory/source/tombstone/knowledge frontiers, generation-vector digest, bounded lease, one-shot guard semantics and snapshot/read receipt binding are implemented and source-composed in the same production path.
- **Remaining work:** obtain passing exact-candidate/merge-candidate receipts and independently governed target-host/acceptance/canary/release evidence. A strict no-intervening-write guarantee after finalizer return is not claimed; if required, it needs a writer-participating consumption lease/fence. The additive Agentd finalization method is an existing-owner local control extension, not a new authority source.

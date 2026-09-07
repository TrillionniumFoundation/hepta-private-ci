# cognitive.store: implementation design

Parent: `docs/modules/cognitive.store/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-store`.
Packages: `MEM-1-STORE`, `MEM-8-PRODUCTION-WRITER`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`append_event(event, expected_frontier, writer_fence) -> EventCommit`; `append_correction(original, successor, fence) -> CorrectionCommit`; `forget(source_scope, frontier, authorization) -> TombstoneCommit`; `open_snapshot(scope, requested_frontier) -> ReadSnapshot`. All mutations remain inside the one canonical cognitive writer; retrieval/Neuron/KG send intents rather than opening this writer directly.

## 3. State records and transaction design

Logical owner records: memory event (scope,event ID,revision,source/span references,verification,retention), knowledge fact (fact ID,source support,revision,validity), correction (old/new IDs,reason), tombstone (source range,cutoff,revocation lineage), asset metadata (content digest,media/range,redaction/preprocessor,retention). Index keys include scope+ID+revision and source digest. Large assets use the existing owner asset store, not inline ledger payloads. Append and local publication intent share one durable boundary.

## 4. Deterministic algorithm and scheduling

Authenticate scope and writer; validate referenced assets and source frontiers; perform predecessor CAS; append/canonicalize the existing durable format; fsync before publication acknowledgement; emit outbox updates to projections. Corrections and logical exclusion append records. Physical erasure/asset removal and derived-artifact revocation are separate tracked work; a tombstone alone is not full unlearning.

## 5. Capacity and performance profile

Pilot event metadata <= 256 KiB, transaction batch <= 256, bounded snapshot readers and retention per policy. Segment/rotation limits must preserve continuity and acknowledged-history anchors. Measure fsync, WAL/journal growth, reopen, compaction and tombstone traversal at maximum retained size.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- STORE-01: duplicate same-semantic event returns the prior commit; changed identity content conflicts.
- STORE-02: crash before/after sync and acknowledgement loss preserve anchored history.
- STORE-03: stale writer and competing writer cannot both advance a frontier.
- STORE-04: restoring a backup before a forget cutoff replays revocations before any read becomes visible.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 uses a real store/open_snapshot consumer with exact physical format and file/DB path receipts. HNMF engrams and KG remain projections. Rollback must validate current tombstone frontier and compatible readers; it must not revive earlier acknowledged deleted content.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

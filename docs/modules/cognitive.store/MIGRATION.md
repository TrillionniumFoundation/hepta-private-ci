# cognitive.store authoritative-ingress migration and rollback

This runbook closes the repository migration story for the current architecture. The normal cutover does **not** copy cognitive data into a second database. The durable owner remains the existing Agent-local `cognitive_1.sqlite3`; the migration changes which Rust module product/runtime code is allowed to use to open that owner.

Writable recovery of a suspect owner is a different operation: it never makes the suspect inode writable. It validates one retained cold image against an independently authenticated exact-current-cut anchor, requires an externally verified current production authority fence, writes those same verified bytes to a fresh private inode, quarantines the suspect source, atomically publishes the fresh inode at the canonical route, then reopens and rechecks the complete logical cut before returning a writer-capable store.

## Invariant

There is exactly one durable cognitive owner per Agent and exactly one product ingress:

```text
agentd / production writer host
        |
        v
codex_hepta_cognitive_store::open_authoritative
        |
        v
hepta-memory::CognitiveStore
        |
        v
cognitive_1.sqlite3
```

Recovery uses a separate canonical ingress:

```text
independent exact-current-cut anchor
              +
current externally verified ProductionAuthorityLease
              |
              v
codex_hepta_cognitive_store::open_authoritative_with_recovery
              |
              v
retained descriptor -> immutable cold bytes -> read-only verify
              |
              v
fresh private inode -> suspect quarantine -> canonical publish
              |
              v
reopen + exact anchor verification
```

`QualificationSemanticStore` and `AdmittedCognitiveStoreV2` are deterministic semantic oracles. They are not synchronized stores, shadow writers, backfill destinations, recovery destinations, or fallback databases.

Knowledge facts are not a separately writable second ledger. The durable authority is the immutable memory revision plus its revision-bound `kg_revision_fact_sets` projection. `CognitiveOwnerFrontiers.knowledge_facts` counts those bound fact sets. A projection can be rebuilt from the durable revision/source lineage; it cannot create an independent fact authority.

## Pre-cutover

1. Freeze new cognitive schema changes for the candidate.
2. Record the exact source SHA and candidate tree.
3. Run `python3 scripts/hepta_cognitive_store_authority.py`.
4. Run the focused Rust packages: `just test -p codex-hepta-cognitive-store -p codex-hepta-memory -p codex-hepta-agentd`.
5. Verify `codex-hepta-cognitive-store/tests/durable_authority.rs` reopens the same SQLite path and exact recovery anchor.
6. Verify writable recovery tests publish a fresh inode only under an accepted external fence, keep the logical cut identical, and make a denied fence leave the cognitive route unchanged.
7. Verify production-writer tests cover restart replay, lifetime single-writer exclusion, crash-after-send indeterminate state, and concurrent dispatch claim serialization.
8. Verify no product opener in `hepta-agentd` contains `CognitiveStore::open(`.
9. Retain a current independently authenticated recovery anchor where host policy requires rollback detection. The database must never self-authenticate its own backup.

## Normal cutover

The normal authority cutover is source-only because the physical owner and schema do not move.

1. Change product/runtime open calls to `codex_hepta_cognitive_store::open_authoritative`.
2. Keep the durable SQLite engine in `hepta-memory`; do not create or dual-write a new cognitive database.
3. Keep production writer creation behind `ProductionDurableWriter`, its external authority verifier, lifetime OS lock, lease generation, fencing token and durable occurrence journal.
4. Deploy one process generation at a time. A generation change fences the old Agentd before the new runtime is served.
5. Compare the post-restart `CognitiveRecoveryAnchor` with the pre-cutover current anchor when the host has an independent witness.
6. Verify memory, source, tombstone, knowledge-fact and knowledge-graph frontiers from one `lane_c_snapshot` transaction.

There is no count/hash backfill phase in this cutover: the façade opens the same physical database. Creating a second live database for a nominal migration would reintroduce the dual-authority problem this change removes.

## Fenced writable recovery

Use `open_authoritative_with_recovery` only when the normal owner cannot be trusted as a writable route and the host has an independently retained CURRENT `CognitiveRecoveryAnchor` plus a current `ProductionAuthorityLease` whose verifier proves the previous Agent generation/writer is fenced.

The implementation is deliberately two-phase:

1. Validate recovery owner/profile before filesystem admission; revocation wins immediately.
2. Bind the cognitive root, source database and sidecar identities with read-only descriptors and `O_NOFOLLOW`.
3. Reject any WAL, SHM or rollback-journal sidecar; no sidecar replay occurs.
4. Capture at most 128 MiB once from the retained database descriptor. The source pathname is not opened by SQLite.
5. Open those exact immutable bytes in a single-connection read-only in-memory SQLite image.
6. Validate registered schema, all bounded logical owner tables, source/tombstone/fact state, `quick_check`, foreign keys and full `integrity_check`, then require an exact match to the independent current-cut anchor.
7. Verify the external production authority fence.
8. Acquire an Agent run-root recovery-promotion lock. This lock is outside the cognitive root so acquiring it cannot invalidate the retained source-directory identity.
9. Materialize the already-verified bytes into a new `0600` file using `create_new` and `O_NOFOLLOW`; recheck that the retained source database and sidecar identities did not change.
10. Reverify the external fence immediately before publication.
11. Rename the suspect canonical source to a non-routable `.quarantine` name and atomically rename the fresh inode to `cognitive_1.sqlite3`; fsync the cognitive directory.
12. Open the fresh canonical owner through the normal durable path, recapture the complete logical recovery anchor, and require exact equality with the authenticated anchor.
13. Reverify the external fence before returning the writable store.
14. If reopen, anchor verification or final fence verification fails, quarantine the failed fresh inode and restore the original source route; do not claim recovery success.

The old direct `CognitiveStore::open_with_recovery` pathname-writer experiment remains fail-closed. It is not the canonical recovery path. The canonical route is fresh-owner promotion of the same verified cold image, which avoids both in-place repair and SQLite reconnect to the suspect pathname.

## Rollback

Rollback changes the caller routing, not the normal data format.

1. Stop/fence the candidate runtime; do not keep both runtime generations writable.
2. Retain the exact current recovery anchor before changing binaries.
3. Restore the predecessor binary only if it understands the same SQLite schema.
4. Reopen the same `cognitive_1.sqlite3` through normal verification when the canonical owner itself is trusted and current.
5. If rollback/restore involves a suspect, quarantined or older database image, do **not** use ordinary `open`. Require an independently authenticated exact-current-cut anchor and a current external production fence, then use the fresh-owner recovery route. An older valid backup that does not match the current anchor is rejected.
6. Compare owner/scope frontiers and the independent cut digest before resuming reads or writes.

A `.quarantine` file is forensic evidence, not a second owner. It is never product-routable and may be deleted only under the owner retention/privacy policy after the recovered canonical owner has passed external acceptance.

## Failure rules

- Never fall back from failed recovery admission to ordinary `open`.
- Never copy an old valid SQLite file over the current owner and call that recovery.
- Never write or repair the suspect source inode in place.
- Never run an in-memory V2 store as a production fallback.
- Never dual-write the semantic oracle and SQLite backend.
- Never infer external-effect success from queue admission or process completion.
- Unknown target outcomes remain durable `Indeterminate` and require status/reconciliation.
- A stale writer, stale generation, rejected/expired authority lease, reused intent with drift, broken revision lineage, tombstone resurrection or anchor mismatch is terminal for that attempt.
- A target-host power-loss result must come from target-host qualification; source code and PRAGMA values are not a hardware durability certificate.

## Qualification evidence

Repository source now contains the fresh-owner writable recovery mechanism, but repository completion and release remain separate claims. `productionImplementation=true` and `writableSuspectImageRecoveryImplemented=true` mean the source implementation exists and is wired to the canonical module API. `productExecutionProved` stays false until exact-head and synthetic-merge CI execute this candidate. Independent target-host filesystem/power-loss qualification, operator acceptance, activation, promotion and release remain separate evidence gates.

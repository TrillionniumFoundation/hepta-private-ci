# Cognitive store: technical and development guide

`codex-hepta-cognitive-store` exposes cognitive record semantics and the existing
durable owner's API. This guide describes source baseline `7673ea62`; adding it
does not qualify a new binary, persistence deployment, or production writer.

## Technical contract

| Compiled surface | Contract and source |
| --- | --- |
| `CognitiveStore` | In-memory current-head ledger; append/correction/tombstone and original-sequence retry semantics. [lib.rs:142](src/lib.rs#L142), [append:165](src/lib.rs#L165). |
| `AdmittedCognitiveStoreV2` | In-memory full revision histories, intent journal, exact snapshot key and writer fence. [v2.rs:298](src/v2.rs#L298), [append_admitted:361](src/v2.rs#L361). |
| `DurableCognitiveStore` and production writer types | Re-exports of `codex-hepta-memory`; the physical owner is its single `cognitive_1.sqlite3` database. No second database, migration set or writer is introduced here. [durable.rs:1](src/durable.rs#L1). |

`lib.rs` declares only `durable` and `v2` ([lib.rs:8](src/lib.rs#L8)).
The separate [production.rs:29](src/production.rs#L29) façade and
[production_tests.rs:23](src/production_tests.rs#L23) are not wired into that module
tree on this baseline. Their presence is not an exported API or reachable test;
whether that earlier design should be retained is a separate implementation decision.

For the current-head ledger, identical content returns the original commit
sequence. A changed existing head needs both expected and embedded predecessor
digests, the next revision and available sequence. New record IDs additionally
require capacity; a tombstone cannot resurrect.
Fallible preflight precedes publication. Receipts carry `AuthorityPosture::DENY_ALL`
([lib.rs:165](src/lib.rs#L165), [receipt:233](src/lib.rs#L233)).

V2 additionally requires a verified candidate, current snapshot vector and writer
fence, and a host-supplied `StoreAuthorityVerifierV2`. A digest alone grants no
write. Reusing an intent ID with changed semantics conflicts; an exact retry
returns its original receipt even after unrelated commits. Forgetting retains
terminal tombstones and advances deletion history. An exported checksum-bound
image must pass `reopen` validation; exporting an image does not save it to disk
([v2.rs:60](src/v2.rs#L60), [forget:515](src/v2.rs#L515), [export/reopen:711](src/v2.rs#L711)).

| Resource/failure boundary | Behavior |
| --- | --- |
| Current-head capacity | Nonzero caller limit, capped at 16,384 records; stale predecessor, revision/sequence exhaustion and resurrection fail before mutation. |
| V2 revision budget | Absolute cap 65,536; ordinary configured capacity at most 32,768, reserving deletion space. Intent journal cap is 65,536. [v2.rs:44](src/v2.rs#L44). |
| V2 snapshots | Lease at most 300,000 ms; pages at most 512 records. Scope/purpose/epoch/frontier mismatches fail; continuation after any cut change is rejected. [open_snapshot_page:618](src/v2.rs#L618). |
| Durable authority/recovery | Supplied by the actual `hepta-memory` owner and host composition, not the in-memory V2 verifier or an image digest. |

The compiled Agentd runtime imports `DurableCognitiveStore` as `CognitiveStore`
([runtime.rs:11](../hepta-agentd/src/runtime.rs#L11)). A configured recovered writer
supplies that same runtime; otherwise the ordinary store-open path is used
([runtime.rs:182](../hepta-agentd/src/runtime.rs#L182)). The production host requires
an independently authenticated current cut and opens the existing live-verifier
writer ([production_writer_host.rs:320](../hepta-agentd/src/production_writer_host.rs#L320)).
This is not evidence that deployment inputs are configured or native recovery passed.

## Development and verification

Start at [Cargo.toml](Cargo.toml), `src/lib.rs`, `src/durable.rs`, then `src/v2.rs`.
Changes to physical SQLite durability belong in the original `hepta-memory`
implementation; do not make the unwired façade a reason to add another writer.

From the repository root, this package selection preserves the original host
flags; set an external `CARGO_TARGET_DIR` for the development machine:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline -p codex-hepta-cognitive-store \
  --test-threads 2 --retries 0 --cargo-profile dev-small
```

Concrete test IDs (binary `codex-hepta-cognitive-store`) and source entry points:

- `tests::append_and_correction_are_predecessor_fenced` — [lib_tests.rs:51](src/lib_tests.rs#L51).
- `tests::retry_after_unrelated_append_preserves_original_commit_sequence` — [lib_tests.rs:180](src/lib_tests.rs#L180).
- `v2::tests::tombstone_uses_reserved_capacity_after_ordinary_capacity_is_full` — [v2_tests.rs:372](src/v2_tests.rs#L372).
- `v2::tests::paged_snapshot_rejects_continuation_after_store_cut_changes` — [v2_tests.rs:639](src/v2_tests.rs#L639).

Fixtures are local constructors in those test files, including controlled
verifiers and image/cursor tampering. They do not establish deployed authority,
real crash durability, or a reachable test for the unwired `production.rs`.
No Rust command was run for this documentation change. The package selection
does not replace the full 19-owner Desktop/Hepta qualification or its source tuple.

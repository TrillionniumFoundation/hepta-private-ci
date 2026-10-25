# Exact-current historical observation

This API reads the original cognitive database as an isolated historical image.
It does not restore a writer, a lease, a Root publisher, or a FinalUse grant.
The caller supplies the complete Current cut and revocation disposition from an
independently authenticated source. Recomputing the cut from the suspect SQLite
file and passing that result back is not authentication. A Root disposition of
Dirty, Publishing, Fenced, revoked, or unknown publication acknowledgement must
not be relabeled as `ExactCurrentCut` using a remembered last-good cut. This
storage API performs no Root administrative transition or acknowledgement repair.

## Developer entry points

- `CognitiveStore::open_read_only_recovery` retains the original fixed-file cold
  API. It does not follow a recovered-generation pointer.
- `CognitiveStore::open_active_read_only_recovery` follows the original private
  active-generation selector. A selected file which is missing, redirected,
  damaged, or inconsistent with Current fails admission; there is no fallback
  to the older default database.
- `RecoveredCognitiveReadOnly::retained_operation(lease_id, operation_id)` reads
  the original `ProductionRetainedOperation`: operation semantics, exact topic,
  exact payload bytes as UTF-8, and original `LocalOutcomeState`.
- `RecoveredCognitiveReadOnly::close().await` finishes pool shutdown explicitly.

The handle exposes no SQL pool, mutable store, writer conversion, dispatch,
re-signing, grant issuance, or outcome mutation API. It also retains the original
bounded `lane_c_snapshot` access/scope checks. A caller must discard the handle
and its projections if the trusted host revokes historical access later; the
admission decision is not a continuing live-authority check.

Lease and operation strings use the original ledger bounds and exact equality.
They are never trimmed, case folded, or mapped to another lease. The projection
verifies the original lease/event/outbox chains, pairing, operation semantic
hash, owner and admission bindings, and outcome state machine. The shared
pairing helper is also used by the existing live writer reader, which retains
its active-lease and current-fence checks. Historical observation intentionally
does not manufacture that live handle or require an expired historical lease
to become active again.

## Storage and identity boundaries

Both cold APIs require a cold database: **any WAL, SHM or rollback journal, including
an empty sidecar, is rejected**. Neither API checkpoints, recovers, migrates,
repairs, or opens the suspect source through SQLite. The original descriptor
inspection copies at most 128 MiB into a private, read-only SQLite memory image.
All registered logical facts and the schema must match the complete supplied
Current; integrity checking runs after schema/Current authentication. The memory
image is independent of later source changes.

The active entry point reuses the original no-redirection path and private
regular-file selector checks, then repeats selection after admission. It does
not create a recovery lock file or publish an active pointer. Descriptor and
metadata checks detect drift; they do not establish an atomic path snapshot.
An independently authenticated complete cut is required even when those checks
are stable. Unused physical bytes are not authority or part of the logical cut.

`CognitiveStore::open_active_wal_read_only_recovery` is the separate WAL-capable
entry point. It copies retained DB/WAL/journal descriptors into a fresh 0700
UUID directory created internally by codex-state outside the suspect root.
There is no caller-selected destination or active-generation publication. The
DB and each WAL/journal are bounded to 128 MiB; the bundle is at most 256 MiB.
Source SHM is retained for identity checking and is never copied or modified.

Only the disposable copy is opened by the original single-connection SQLite
recovery/checkpoint helper. That helper closes on success and error, truncates
the copied WAL, and converts the copy to DELETE journal mode. The result is then
copied into the same physically READONLY memory image; the private directory is
removed before the memory layer authenticates the full Current/schema followed
by integrity. Descriptor/selector drift, mismatch, corruption or unavailable
private temporary storage fails admission. No migration or source repair runs.

The owned recovery task continues its close barrier if its caller cancels the
await. Normal success/error paths close SQLite before removing the copy. A
runtime shutdown or panic during the close barrier conservatively leaves a
private orphan directory instead of deleting files beneath a SQLite worker.
No such orphan is an active generation or authoritative evidence. The observer
still requires an independently authenticated pre-failure Current; neither
replaying a WAL nor hashing the recovered copy provides that authority.

## HOS2 interpretation

An original delivery identifier `D`, including its old boot ID, is returned
unchanged inside the exact retained payload. `Indeterminate` remains
`Indeterminate`. Missing operation history is absence of evidence, not a
`NotSeen`, `NotApplied`, terminal success, or retry permission. In particular,
this API does not translate an unreachable old-boot HOS2 device into a live
new-boot target. Subsequent device observation belongs to the original device
contract; no second install follows from this historical read.

## Validation

The tests in `cognitive_store_recovery_active_read_only_tests.rs` use the original
writer and original writable recovery to create a real activated generation and
an admitted HOS2 operation marked Indeterminate. They compare the entire typed
projection, test wrong-lease/unknown requests, complete Current and revocation
refusals, empty sidecars, redirected selector and selected database, and compare
source bytes plus inode/mode/mtime/ctime before and after reads and refusals.
The default-file reader is checked independently to preserve its old semantics.
The fixture authority verifier is a test authority, not the deployed Root; these
host storage tests are not native G2 or reboot qualification.

The WAL test adds a real original-owner child, commits an additional source row,
retains its complete Current in an independent parent channel while the child is
alive, and then sends actual SIGKILL. The resulting nonempty WAL is required for
that cut. The old cold API refuses it, the new observer reads the unchanged old
operation/D/Indeterminate, and wrong Current, revocation and damaged WAL refuse
without changing source bytes or metadata. This is process-crash host storage
qualification, not physical power-loss or native G2 qualification. The state
layer also tests that UPDATE remains impossible after `query_only=OFF` and that
a replacement memory connection works after the source is deleted.

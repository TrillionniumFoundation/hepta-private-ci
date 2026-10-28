# V9 memory-image migration

This extension transfers actual cognitive database and model-artifact bytes
between independent storage roots and OS processes. Its currently qualified
transport profile is **same-host loopback TCP**. It does not establish physical
cross-host availability, confidential remote transport, or a production writer
ownership handoff.

## Source, destination, and authority

`MemoryCellMigrationPinV9::from_source` binds an actual owner snapshot and loaded
parameter bundle to the independently retained full cognitive recovery anchor.
The vector includes the owner, scope, memory-source cut, model generation and
bundle digest. The anchor covers the complete cognitive logical cut, including
deletion/revocation state; it is an integrity witness, not a grant.

`MemoryCellMigrationImageV9::capture` accepts quiesced regular file descriptors,
not arbitrary paths obtained from a network request. It records every relative
path, length, SHA-256 digest, and file mode, then frames the manifest and exact
file contents in one bounded payload. A capture is limited to 128 files and
32 MiB, including its header. Executable files, path traversal, duplicate or
unsorted paths, trailing bytes, and mismatched content are rejected. Source
descriptor length/mtime checks detect drift; callers must still establish a
closed, consistent source snapshot before capture.

`MemoryCellMigrationProviderV9` implements the existing provider-effect adapter.
The caller uses `ProviderEffectTaskFlowDriver` and
`AutomationStore::execute_authorized_taskflow_effect_async`; the TaskFlow owner
derives the logical effect key and binds the destination, exact payload, fence,
and final-use grant. This extension does not create production grants or change
the authorization boundary. Operator-configured Ed25519 peer identities sign
requests and responses, including the destination, payload digest and unique
request binding. Signatures provide integrity/authentication, not encryption;
the supplied transport therefore refuses non-loopback endpoints.

The receiver owns a private canonical directory and exclusive lock. Its
configured expected image is separate from the caller-supplied message. A
verified transfer returns a complete immutable image directory, not a writable
cognitive store, live federation capability, or selected model.

## Durable publication and recovery

The persistent transition is:

1. Verify the whole framed payload and bind the provider key to it. Save and
   fsync immutable `PAYLOAD` and a `Received` transaction record.
2. Materialize all files with their declared modes, verify their hashes, and
   fsync a `Prepared` transaction record.
3. Check the expected predecessor and atomically replace/fsync `CURRENT.json`.
4. Fsync the `Committed` transaction record, then acknowledge completion.

Atomic files use create-new temporary files, file fsync, rename, and parent
directory fsync. Startup resumes previously durable operations from their exact
retained payloads. Recovery validates journal keys/digests before constructing
file paths. A `CURRENT` manifest must also equal the manifest decoded from its
hash-bound retained payload; mutable metadata alone is insufficient.

The migration release generation is distinct from the model generation. A
successor must advance by one and name the prior payload digest, owner and
destination. Old transactions retain historical completion receipts after a
successor becomes current. Such receipts prove that a transfer completed; they
do not make an obsolete image current. A stale release under a fresh key cannot
replace the successor.

An ambiguous transport or filesystem failure returns `Unknown`. A failure may
occur after durable publication, so it cannot safely become a claim that the
effect was rejected. The existing TaskFlow uncertainty barrier prohibits blind
redispatch. Restart uses provider-owned status lookup and the existing observed
effect reconciliation API. Exact duplicates return the same acknowledgement;
same-key/different-payload lookups report a conflict.

A whole-directory rollback still requires an independently retained current
host witness. The migration store does not manufacture such a witness. This
profile assumes a private local filesystem with the documented locking,
rename and fsync behavior; power-loss behavior on other filesystems needs its
own qualification.

## Actual-process qualification

The Rust test is
`actual_memory_cell_v9_authorized_image_migration_recovery`. Its ignored receiver
and destination helpers are launched only as actual child processes by that
parent. Source owners, receivers and destination owners have distinct PIDs.

| Case | Required observation |
| --- | --- |
| Source capture | Real owner event, semantic and procedure cells compose to 29; source WAL is closed before capture. |
| Invalid grant | Existing final-use authority rejects it before any provider contact. |
| Receiver exits at `received`, `prepared`, `current`, `committed` | Real exit code 73; caller records uncertainty; receiver and TaskFlow stores reopen; status lookup reconciles success without redispatch. |
| Exact duplicate | Stable provider acknowledgement and byte-for-byte unchanged CURRENT. |
| Conflicting key | Different payload under the same key cannot publish; lookup reports the originally bound digest. |
| Corrupt content or reversed inventory | Actual TCP request is rejected and a subsequent lookup proves no transaction was published. |
| Successor and stale release | Generation 2 is published coherently; generation 1 cannot replace it or be opened as current; historical completion survives. |
| Destination activation and restart | Original source data/artifact paths are renamed away; the independent destination admits the full cold cut, verifies/selects the transferred signed artifact, opens the ordinary fixture owner and returns the same three-cell native result through actual Agentd control twice. |
| Old process identity | A client carrying the first destination spawn generation is rejected after restart. |

The destination fixture follows the existing Agentd lifecycle transitions
Starting, Running, Draining and Stopped and holds the ordinary exclusive owner
writer lock. Its artifact selector and final-use issuer use explicit fixture
keys. Its App Server readiness marker is a control-only fixture seam. The
single-class parameter fixture and fixed Apply resolver exercise migration,
versioning and native integration; this test makes no training-quality claim.
The destination fixture is not evidence for production writer-lease restoration
or cross-machine fencing.

## Evidence and accounting

Set `MEMORY_CELL_V9_MIGRATION_RECEIPT_PATH` to a new absolute JSON path. The test
retains that receipt and a sibling directory obtained with
`Path::with_extension("artifacts")`: `migration.json` produces
`migration.artifacts`. Archive both. The directory includes exact source image
bytes/manifests, every receiver's durable transaction/image root, child specs,
TaskFlow/fixture-authority evidence, and final destination cognitive/artifact
files. The receipt inventories every retained file by path, size, digest and
mode, together with actual native readouts and process lifecycle observations.

Provider and receiver counters count actual successful application reads and
writes, including length prefixes, signed JSON headers, payload contents,
responses, retries, duplicate checks, failed probes and status lookup. Endpoint
totals are two views of a transfer and must not be added as distinct network
traffic. They are **not TCP/IP wire bytes**, kernel retransmission counts or an
encryption-overhead estimate. Control traffic uses the existing metered Agentd
client. Child-process bootstrap and shutdown accounting includes actual stdin
commands and bounded stdout received through EOF, including source-fixture
shutdown. Specs are recorded separately as local file bytes.

The receipt retains complete parent wall time through child shutdown, per-child
lifetimes, and summed endpoint attempt durations. Attempt durations overlap
with parent/child lifetimes. An abruptly exiting receiver does not run its
attempt timer destructor; its recorded timer is partial and its complete
parent-observed process lifetime is retained separately. Local file inventories
and activation copy sizes are stocks/copy quantities, not inferred disk I/O or
memory residency integrals. The separate V9 lifecycle resource monitor supplies
its own sampled resource evidence and coverage limitations.

Validation status and the exact tested source commit belong in the V9 CI
receipt. This implementation document does not substitute for an executed test
result.

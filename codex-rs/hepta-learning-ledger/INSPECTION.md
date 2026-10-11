# Read-only causal ledger inspection

This LRN-1 read-port sub-slice adds `inspect_ledger(File, binding, max_records,
LedgerAnchor)`. It is an opt-in API of the existing ledger, not a second fact
store, writer, selector, or canonical wire protocol.

## Ownership and algorithm

The host supplies an independently opened, authorized read-only regular file
and an authenticated CURRENT external acknowledgement witness. The reader takes
a nonblocking shared lock. A live durable writer keeps its exclusive lock and
causes `Busy`; multiple independent readers can coexist. This initial interface
therefore reads closed segments or separately qualified immutable snapshots,
not an always-live mutable writer. It opens no path and acquires no credentials.

Writer recovery and inspection share `replay_frames`, including all size bounds,
header/frame checksums, canonical event decoding/re-encoding, sequence and causal
validation, and external anchor comparison. The HEPTLR01 bytes, original tests,
writer commit/sync ordering, tail repair and normal Drop unlock remain unchanged.
Only the writer may truncate an incomplete tail and sync recovered data.

Inspection never writes, initializes, truncates, repairs or calls sync. A partial
tail returns `IncompleteTail`. A complete suffix beyond the supplied witness
returns `UnwitnessedTail`, not an old-prefix snapshot: a later suffix may contain
a revocation, and a complete write alone does not prove its acknowledgement.
The host must reconcile through the owner and obtain the current witness before
retrying. Missing or changed acknowledged history rejects before any repair.
An invalid witness is never replaced by an unanchored fallback.

The shared lock is explicitly released on both success and rejection; the guard
exists only after acquisition. It cannot unlock a different owner's independent
handle when acquisition fails. As with the writer, cloned/already locked aliases
are unsupported inputs; tests simulate transient inherited descriptions only.
Locks fence cooperating processes, not hostile writes or privileged remounts.

## Snapshot and trust boundary

The returned `LedgerSnapshot` retains the canonical history, including logical
revocations. Consumers rebuild with `LearningLedger::from_snapshot` and use
`active_records` for eligible data. The snapshot is historical: it is not a
current-revocation service, signed dataset, authenticated independent evaluation,
or permission to install an artifact. Restore/use requires fresh host validation.
The independent witness must be retained outside the suspect segment and bound
to the same store, scope, purpose and generation. This API does not implement
that witness service. Logical exclusion is not physical or backup erasure.

## Tests and qualification

Eight added test functions cover OS read-only access, shared-reader/exclusive-writer
fencing, no reader repair, complete unwitnessed suffix rejection, missing/mismatched
anchors, corruption and input bounds, revocation projection, and Linux inherited-lock
lifetime on rejection. Existing core and durable regression tests are retained.
The dedicated ledger and cross-crate read-only workflows must compile, run standard
`just test`, lint and check formatting at exact source and actual-base synthetic
merge. Test source is not proof of execution. Target-host durability, latency,
identity separation, real-product consumers and longitudinal efficacy remain
separate requirements; no capability or completion flag is advanced.

# Actual competing-writer counterexample

The original 64-case v1 scope passed 62 cases, failed its real competing-writer
assertion and timed out another case. The v2 diagnostic retained that assertion
and printed the actual result: while synchronous metadata retirement was still
held, another original Notes writer returned `Ok(ProductionQueuedReceipt)` and
committed SQLite changes. All original retries, failure text, exit records,
helper commands, source deltas and exact retained binary hashes are preserved.

The read-only pool's BEGIN IMMEDIATE did not provide the intended mutual
exclusion. The historical 59/59 and 33/33 runs remain true observations of those
earlier fixtures, but a short pending check did not establish that safety claim.
Notes retirement, HOS2 retirement and pre-effect publication sharing this
barrier remain open. These records qualify no repaired barrier or device.

See [the manifest](publication.json) and
[the reopened module contract](../../NOTES_RECEIPT_RETIREMENT.md).

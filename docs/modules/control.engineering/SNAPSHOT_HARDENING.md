# control.engineering: snapshot and evidence hardening

Date: 2026-09-28. Owner: developer-productivity. Deputy: architecture.

This is a scoped supplement to [BOUNDED_OWNER_CONTRACT.md](BOUNDED_OWNER_CONTRACT.md),
[TECHNICAL.md](TECHNICAL.md), and [IMPLEMENTATION.md](IMPLEMENTATION.md), not an
acceptance receipt. The authoring baseline is
`54a20e3f03230fc28fd8a54df74f7b5fc82a9494` (tree
`873841f0b49a0bac5990223eafa0d9724a102a2d`) in PR #1175.

## Preserved boundaries

The persistent fact owner remains SQLite v10 `EngineeringStore`; ordinary callers
remain on `EngineeringControlProduct`. No persistent table, second result ledger,
executor, authorization cache, production flag or external service is introduced.
Existing tests and assertions are retained. The current signed, revision-bound
renewal implementation is preserved, including historical replay without renewal
of expiry or authority and current signature/revocation checks.

The earlier prose review's three named replay failures and runtime class were not
established for this owner. This change does not invent an outbox/dispatcher path
to match that prose or claim those unverified failures were reproduced. The actual
worker lifecycle and durable integration queue remain the integration surfaces.

## Runtime delta

### Snapshot-pinned capacity calibration

A foreign connection can commit after the initial `data_version` sample but before
the first main-database read pins the snapshot. Previously a requested calibration
could compare new owner counts with old TEMP counts and permanently quarantine a
legitimate foreign commit before the final version check.

The monitor now samples the version again after pinning, before examining cache
validity or declaring drift. A changed version discards only its own transaction,
invalidates its generation and retries. Post-pin commits are still checked after
ending the snapshot. Three attempts remain the hard limit; continuous churn is
`capacity_observation_changed`, not permanent corruption. Caller-owned transactions
are neither finished nor published as reusable cache generations.

SQLite type affinity is not a strict counter contract. REAL and TEXT values are
now rejected instead of silently converted with `int()`. Missing or malformed
projections latch quarantine. Temporary negative integer counters after foreign
claim creation remain permitted until refresh, so derived observations cannot
block a legitimate primary-state settlement. Actual drift still quarantines.

### Byte-bounded audit metadata and streaming payloads

All metadata lengths now use BLOB byte lengths. Embedded NUL tails cannot pass a
TEXT character-length check and then force oversized identifiers into Python.
Anchor lookups return a boolean match, and automatic cut discovery returns a digest
only when it is a 64-byte TEXT value. Metadata type and timestamp checks occur
before payload fetch. Malformed JSON integer conversion becomes a typed failure.

After event and encoded-byte budgets pass, one indexed, LIMIT-bounded payload cursor
streams the admitted interval instead of issuing a query per event. Canonical JSON,
contiguous sequence, predecessor, event ID, recomputed digest and fixed read-cut
checks remain mandatory. Complete-suffix requests still reject rather than truncate.
The same read transaction protects admission and verification. These are bounds on
values crossing the SQL/Python boundary, not guarantees about SQLite internal I/O,
Python decoded-object RSS, or full-checkpoint creation cost.

## Qualification delta

The existing read-only collector now records commit, tree and dirtiness before and
after every command and at completion. A clean newly committed tree is still the
wrong candidate. Observed identity drift stays failed even if a later command
restores HEAD. Checks between command boundaries do not constitute a sandbox or
proof against transient in-command changes followed by restoration.

A successful command exit is insufficient: a bounded, well-shaped unittest report
must contain a positive integer test count, a boolean successful result and no
failures/errors/unexpected successes. Skips and expected failures do not establish
full qualification. Missing, malformed and oversized reports retain failed evidence
rather than aborting collection. Earlier logs are rehashed after later commands;
missing, replaced or symlinked logs cannot satisfy the integrity check. Independent
acceptance, production acceptance and release authority remain separate and false.

## Regression and execution inventory

`test_owner_snapshot_regressions.py` adds 12 tests through the real product/owner:
pre-pin/post-pin foreign commits, bounded continuous churn, malformed/missing TEMP
counters, NUL-tailed metadata, storage-class/timestamp violations, typed JSON failure,
outer-transaction preservation and single-query append-safe paging. These tests are
registered in the ordinary runtime-regressions plan and full unittest discovery.
Their execution on the complete repository is NOT claimed by local probe results.

`test_candidate_evidence_integrity.py` adds 15 tests using real temporary Git
repositories and subprocesses. The command plan is replaced with isolated collector
fixtures, not with product success. The existing seven collector tests are unchanged.
Local execution of these 22 collector tests passed on Python 3.13.5/Linux, exit 0.
The new 15 tests against the original collector failed, exit 1 (nine assertion
failures and six errors, including missing new diagnostic fields).

A separate local SQLite diagnostic loaded the modified audit/capacity modules with
a minimal fixture owner and real WAL connections: 19 probes passed, exit 0. That
fixture is NOT EngineeringControlProduct, does not exercise authorization, and is
not a second production implementation. It does not establish the 12 product tests,
full module tests, typing, lint, coverage, strong sandbox or target-host behavior.
The local evidence manifest records exact file blobs, commands, scope and log hashes.

## Remaining final-candidate gates

The full source-head and fixed-base synthetic merge must still execute the normal
read-only collector and all applicable repository gates. Its existing 80 percent
coverage gate, typed boundaries and document checks are not weakened. The canonical
implementation map must still be refreshed/checked against the final source;
this scoped supplement is not a replacement for that map or a complete-mapping claim.
`STATUS.json` is not edited to translate local diagnostics into product execution.

Full checkpoint creation, external-writer cache rebuild/calibration and renewal
history lookup retain the documented cold-path scans. External fencing/revocation,
immutable audit, real key custody, native consumer/deployment, recovery/rollback,
operator acceptance and independent semantic review require actual receipts from
their respective owners. None is fabricated or enabled by this patch.

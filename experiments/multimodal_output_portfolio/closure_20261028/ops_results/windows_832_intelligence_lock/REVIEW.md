# Evaluated-shadow ledger fixtures: respect the real owner lock

Two test files change. Production ledger locking, append, recovery, witness,
trust verification, and evaluated-shadow code remain untouched. No new
production API, dependency, or Bazel target is added.

## Observed failure and cause

Workflow 40661665726, job 122730593546, reported 68 passing and four failing
intelligence tests. All four failed at fs::read while a LedgerWriter still
owned the file, with Windows error 33 (ERROR_LOCK_VIOLATION). The adjacent
INPUT_FAILURES.json preserves the parent's exact bounded excerpts and source
SHA; it is not the complete job log.

DurableLedger and LedgerWitnessStore each own a LockedFile. Its existing
File::try_lock protects independent handles; Windows prevents byte-range reads
and writes through another handle even in the same process. Those failures
show the test violated the lock lifetime, not a reason to relax the writer.

Primary API reference:
https://learn.microsoft.com/en-us/windows/win32/fileio/locking-and-unlocking-byte-ranges-in-files

## Lifecycle repair

The existing recovery setup is reused through a test-only helper. Tests capture
the validated snapshot and, where a record has been acknowledged, the existing
append or witness anchor. They drop the writer, compare the actual ledger and
witness bytes, and reopen using the ordinary production recover constructors.

Newly created empty fixtures explicitly use LedgerRecovery::Unacknowledged.
This is necessary because the API correctly rejects Acknowledged(sequence=0).
Once a record is acknowledged, every reopened fixture uses the retained
Acknowledged anchor; no suspect file is used to manufacture a replacement
anchor and no failed anchored recovery is retried unacknowledged.

The four original semantic tests retain their checks: authenticated Decision
contents, exact idempotent replay receipt and pipeline, semantic drift refusal,
ten invalid-evidence cases with no port calls, stale authority refusal, wrong
predecessor conflict, capacity refusal, and unchanged durable bytes. The byte
comparison now includes the independent witness. Existing remaining port,
slow-path, abstention, and segmented-ledger tests remain enabled.

## Explicit platform corruption cases

The old combined conflict/capacity/I/O test is split. Conflict and capacity
continue to run on every platform. Unix retains the original independent
handle truncation while the writer is live, followed by exact Corrupt and then
Poisoned results from the owner API.

The Windows case performs a real authenticated append, retains the confirmed
anchor, and opens an independent file handle while the owner is live. It
requires both a raw read and an overlapping write to fail with error 33. After
closing those handles it verifies the actual ledger and witness bytes are
unchanged.

It then removes the acknowledged record after owner exit while preserving the
original valid header. Reopening with the retained anchor must return exactly
AcknowledgedHistoryMissing. The final byte assertions verify recovery did not
repair away that loss or rewrite the witness. The original header length comes
from the freshly created closed fixture; no private format constant is copied.

The test deliberately exercises documented byte-range write denial while the
owner is live. It does not assume that every possible filesystem mutation,
memory-mapped write, or privileged operation is fenced by the lock. In
particular, active-owner SetEndOfFile behavior is not asserted. This preserves
the production contract's stated scope.

Each supported platform gains one test relative to the original combined case:
Unix live-corruption or Windows mandatory-I/O-and-history-loss. The observed
Windows count of 72 should become 73 if no other test source changes; CI must
establish the actual enumeration and result. No platform suite is skipped.

## Validation

The scoped just test and just fix commands both returned 101 before compilation
because this sparse checkout lacks codex-rs/aws-auth/Cargo.toml. Full commands
and logs are in VALIDATION.json. The repository's scoped formatter succeeded
on exactly the two changed test files, and git diff whitespace checks passed.
No compile, Windows execution, or Unix execution success is claimed. The prior
six-file Windows fix manifest was rehashed and remains unchanged.

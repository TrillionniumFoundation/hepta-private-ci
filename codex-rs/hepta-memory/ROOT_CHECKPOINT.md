# Original CognitiveStore protected checkpoint

This stage integrates the original checkpoint closure identified by
`ROOT_CHECKPOINT_SOURCE.json` into the same CognitiveStore and production writer.
It introduces no parallel effect ledger. The schema 17 Objective sender tables
are original-owner request-retention records in that same database.

## Commit and recovery boundary

`state/src/sqlite.rs` installs the owner callback on every connection, including
replacement connections, at SQLite's actual commit hook. Connection checkout
first coordinates protected Dirty invalidation. A stale or uncertain Current
claim therefore cannot coexist with another successful local writer commit.
The callback is bounded and nonblocking; it neither performs SQLite I/O nor
constructs external authority.

The original `CognitiveCommitGate` is shared by every clone of one recovered
owner. An uncertain publication or dropped checkpoint attempt permanently fences
that generation. A new facade cannot reopen it. Recovery still requires the
independently retained authenticated exact cut and publisher-generation fence;
the in-process gate is not a substitute for either.

`bind_protected_checkpoint` is accepted only for the sole exclusively recovered
store, before a writer or read-side clone exists. It verifies the exact initial
cut, closes the previous SQLx pool, and binds the coordinated writer pool and a
physically READONLY observation pool. The observation pool permanently refuses
commits and rolls back its serialization transactions. It cannot be repurposed
as a writable connection after the normal owner is fenced.

On ordinary binding failure after sole ownership is established, the integration
awaits SQLx pool closure before releasing the original recovery guard. A rejected
shared-store bind must not close another caller's pool. This error cleanup does
not make externally cancelled initialization or shutdown cancellation-safe;
trusted orchestration must await these operations to completion.

## Original Objective sender

The restricted sender retains the exact original envelope and its complete
identity before returning one non-cloneable local send ticket. Recovery returns
inspection/recording capability without minting another unused send ticket.
Independent checkpoint acknowledgement covers the committed owner cut. A lost
checkpoint acknowledgement is Unknown and fences the owner, rather than being
turned into permission to resend or reconstruct a Current claim locally.

This API supplies no signer or network transport. Objective admission remains
with the original Agentd Objective owner. It is separate from FinalUse effect
authority and from the desktop's own client delivery marker. The latter only
prevents accidental transport repetition and is not an authoritative ledger.

Schema migration is part of the verified original store schema. Existing state
must not be opened and re-hashed to fabricate a new authenticated Current cut;
production upgrades require the original protected migration/recovery workflow.
Fresh initialization is an explicit trusted-host operation, not normal recovery.

## Development and checks

Use `just test -p codex-hepta-memory --lib` to cover exact-cut recovery, readonly
observation, implicit and explicit commit-hook refusal, publication loss,
cancellation fencing, retained Objective identity, and real writer crashes.
State API changes also require the applicable `codex-state` tests. After tests,
run scoped `just fix` and `just fmt`. New schema sources remain in Bazel's
migration compile-data glob. Qualification fixtures and old source reports are
not production authority and must be reported separately from actual Root runs.

The integrated memory/state library run passed 563 tests, with 10 intentionally
skipped qualifications, using Rust 1.95.0 and ordinary ext4 SSD temporary files.
It includes actual writer-process termination, protected read-only polling,
lost-publication fencing, and both exclusive/shared initialization cleanup
regressions. The protected-peer fixture in these tests is not a deployed Root
service; that separate service integration has its own qualification stage.

# Shared SQLite owner

`codex-sqlite` contains the original SQLite connection, commit-guard, read-barrier,
descriptor-bound recovery and Root material-copy/publication implementations
previously compiled inside `codex-state`. The production files have one source
location here. `codex-state` reexports the same public types, so existing state
callers and Hepta storage use the same concrete `SqliteConfig` and recovery
guards. `codex-hepta-memory` depends directly on this shared owner; its legacy
`codex-hepta-cognitive-store` adapter continues through the same Memory owner.

State-runtime database migrations, repair policy and telemetry remain in
`codex-state`. Its crate-private `RuntimeSqliteConfigExt` calls these original
connection methods. The six public database paths and the metadata path order
are unchanged. No dependency version, workspace feature, SQL schema, migration,
connection option, file permission or Root/UID admission rule changes here.

## Preserved boundaries

The writable legacy pool retains WAL/NORMAL, incremental auto-vacuum, five
connections and the original five-second busy timeout. Authoritative evidence
retains WAL/FULL, foreign keys, every-connection commit hooks and the original
checkout coordination. Observation pools remain read-only with rejecting commit
hooks. The read barrier remains a separate lock-only connection whose commit is
always refused, including cancellation handling.

Recovery still binds the original retained descriptors and complete file
identities. Path-based source reopen remains disabled; the descriptor-VFS
entry points continue to return their original fail-closed outcomes. The
physical Root owner-copy and publication implementation, including its locks,
directory checks, staged sync and unchanged original selection, moves intact.
The bundled SQLite minimum version assertion is enforced in this crate too.

## Validation and build scope

The five original SQLite test modules move with the owner, preserving their
module names, cases and assertions. Their shared temporary-name helper is the
original test-only implementation. Full state-runtime tests still belong to
`codex-state`. Run both packages; a test selection limited to `codex-state` no
longer exercises the relocated SQLite tests. The ignored Root tests retain
their actual Root/protected-directory requirements, and the two controlled
child helpers are invoked by their original parents only.

This source extraction requires real Cargo and Bazel lock regeneration, the
original state/SQLite/Memory regressions, and a new measurement using the
unchanged native build profile. It does not itself establish a smaller binary,
native execution, persistent CPU control, authenticated recovery across boots
or production qualification.

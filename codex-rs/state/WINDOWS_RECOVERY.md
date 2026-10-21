# Windows retained SQLite recovery

This implementation extends `codex-state`'s existing recovery owner. It does not
create another SQLite writer, ledger, authority issuer, or replay capability.
The cognitive owner still authenticates the exact independently retained current
cut, holds its exclusive store fence, validates the recovered schema and
integrity, and controls publication. Filesystem identity is not proof of current
application state.

## Source admission

`SqliteConfig::bind_existing_recovery_database` opens an existing private parent
with native `FILE_OPEN` and `OBJ_DONT_REPARSE`. It never creates a missing source
or repairs its owner or permissions. Database, WAL, SHM and rollback-journal
names resolve relative to that retained directory handle. Source files are
read-only and deny write and delete sharing for the complete guard lifetime;
guard clones share the original retained handles.

Every retained object is bound to its volume and 128-bit file ID, kind,
attributes, link count, size/allocation, creation/write/change timestamps, and
exact validated current-user owner and DACL. The original private-state owner
continues to reject unsafe effective access and unsupported ACL forms. Access
time is excluded because reading a source is permitted. Missing sidecars must
remain absent. A failure to establish any required information is
`Indeterminate`; unsupported filesystems do not get a path-only fallback.

Revalidation may perform a native identity-only lookup of the original parent
or a relative child. Source bytes always come from the original retained file
handles; SQLite never opens a source filename or descriptor pseudo-path.
Existing direct path-based inspection/writer APIs remain `Unavailable` even
when identity validation succeeds. They would require a separately qualified
SQLite VFS.

## Bounded recovery images

Materialization reads the database and any WAL/journal through retained handles
into an immutable bundle: 128 MiB per file and 256 MiB in aggregate. SHM is
identity-bound but is not copied. The complete source set is revalidated after
reading and before any destination creation. Target files are native
`FILE_CREATE` children of the retained directory with the original private
creation descriptor; existing destinations are never overwritten. Each copy
must actually synchronize, followed by a writable directory handle's
`sync_all`. Failure remains failure. Cleanup deletes only copies for which this
attempt retains the creation handle, never a re-resolved filename.

A sidecar-free cold database may also be deserialized into the existing single
connection, read-only in-memory SQLite image. Reconnection uses the same copied
bytes. It does not reopen the original path or supply a current-cut witness.

The Windows cognitive-store producer creates a fresh private directory and
initial database with the existing explicit current-user creation descriptor.
Existing objects must already satisfy that owner's policy; admission never
re-owns or loosens them. Existing source sidecars are independently checked and
remain rejected if their identity or private ownership is unsuitable.

## Development and qualification

The normal full `codex-utils-path`, `codex-state` and `codex-hepta-memory` suites
remain owning gates. Unix recovery algorithms and their tests are retained.
Windows cases exercise real private handles, clone lifetime, same-size writes,
byte-identical replacement, every sidecar, missing paths, active writers,
hardlinks, junctions, attribute and private-ACL drift, bounded copying,
create-new collisions and exact cleanup, and SQLite read-only reconnection.

`tests/windows-recovery-controls/run.py` additionally requires a native Windows
positive run and two production-only reversions. Removing source sharing denial
must permit the actual write/replacement and fail its designated assertion.
Removing the retained snapshot comparison must allow an actual metadata change
and fail its designated assertion. Compiler errors, timeouts, other failures,
missing observations or wrong counts cannot qualify a negative control. Every
lane restores the exact starting source and index.

The fixed proposal workflow generates formatting and lockfile postimages only
inside project CI, preserving exact source SHA/tree, commands, exit codes,
complete logs, file hashes and a generated tree. Linux runs the original Bazel
lock update/check/repeat/comparison. Windows runs the real owning suites and
native controls. Both platforms run the owning `just fix -p` recipes after the
full suites and preserve every resulting postimage for review. A generated
proposal does not qualify the input HEAD. Its
postimages require review, commit, and all original platform, formatting,
authority and acquisition gates. At source handoff, these Rust/native results
are pending; local checks cover only Python gate logic and patch integrity.

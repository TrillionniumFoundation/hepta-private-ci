# Windows retained SQLite recovery

The Windows backend binds inspection to live filesystem handles. It does not
establish an authenticated current cut, restore a production writer, or issue a
Root authorization. `open_immutable_recovery_pool` and
`open_identity_bound_durable_evidence_pool` still return `Unavailable` after
identity validation because there is no qualified live descriptor VFS.

## Supported source and identities

The first implementation admits a local fixed NTFS drive only. It refuses UNC
and mapped network drives, alternate streams, device names, unknown filesystem
identity support, missing/deleted objects, all reparse points, and unsupported
security descriptor forms. Each directory component is opened individually with
`NtCreateFile` relative to a retained directory handle. The database, WAL, SHM,
and rollback journal retain their own real handles; missing sidecars are checked
again relative to the same verified home.

Every present object records the volume serial and full 128-bit `FileIdInfo`,
creation/write/change times, allocated and logical lengths, link count,
attributes, and the complete owner/DACL descriptor. A regular file must have one
link. The effective thread token takes precedence over the process token. The
owner must match the effective token user/default owner; grants to foreign
principals are refused. System and Administrators are the native privileged
boundary, analogous to the Unix root boundary. A Creator Owner entry is accepted
only as an inheritance template. A null/missing DACL never qualifies.

Revalidation compares retained handles and new relative opens. It also rewalks
the original drive-to-home chain and compares held ancestor identities. Path
spelling, length, timestamps, or a hash never substitute for the immutable file
ID. Last-access time is deliberately excluded because inspection can update it.

## Images and failure behavior

Cold opening reads bytes from the retained database handle into a separate
read-only SQLite memory image. It refuses every present sidecar. Recovery-copy
materialization reads the retained database/WAL/journal into a bounded bundle;
SHM is inspected but never copied. The original limits remain 128 MiB per file
and 256 MiB per bundle. Only the new private copy may replay SQLite journals.
Both platforms use the same image validation and independent cut requirements.

Missing identity/security information, drift, or a failed native flush remains
`Indeterminate`/`Unavailable`. Opening a directory handle is never treated as a
durability acknowledgement. This implementation requests and checks the actual
flush; it does not replace it with a no-op.

## Development and acceptance

Implementation is split into `sqlite_recovery_windows.rs` (rooted handles),
`sqlite_recovery_windows_identity.rs` (full snapshots),
`sqlite_recovery_windows_security.rs` (effective owner/DACL), and
`sqlite_recovery_io.rs` (retained descriptor I/O). Shared image rules remain in
`sqlite_recovery_image.rs`. Windows uses the existing `windows-sys` 0.52 source;
the Cargo dependency edge and Bazel resolution must stay synchronized.

Seven native tests cover unchanged retained handles, same-byte replacement after
restoring mutable metadata, extra hard links for every component, appearing
sidecars/content drift, parent replacement/junctions, foreign read grants, and a real read-only image
connection replacement after the source changes.
The declared Windows workflow also reruns the original fourteen protected-owner
cases without retries or relaxed assertions. Cross compilation is a build check;
only the native runner's exact-source results qualify Windows behavior. The
first official pre-backend run at `3afe4c6` retained 49 actual failures and must
not be described as green. New-backend native acceptance is pending.

Authoritative platform contracts:
[relative NtCreateFile opens](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile),
[128-bit file identity](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info),
[handle security](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo),
[actual flushing](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers).

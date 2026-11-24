# Explicit creation ownership for private SQLite files on Windows

This staged change addresses the observed native file-owner mismatch. It does
not qualify database pathname identity, ancestor confinement, a writer fence,
or a complete current-cut recovery proof. The existing unavailable recovery
entry points remain unavailable. Native Windows qualification is required before
calling the proposed VFS operational.

## Source and implementation boundary

`upstream-source.json` records the exact original libsqlite3-sys 0.39.1 crate
archive, upstream commit and each imported file hash. Its SQLite source is 3.54.1.
The source import is a separate commit from the extension.

`sqlite3/hepta_owner_vfs.c` implements one narrow C API:

```c
int sqlite3_hepta_win32_owner_vfs(const char **out_name);
```

It captures the calling thread's effective `TokenUser`, copies its SID into an
immutable policy and builds an explicit protected owner-only security descriptor.
The returned VFS is named and non-default. Repeated calls for the same SID reuse
it. At most 64 policies are retained for the process lifetime on the Windows
process heap; neither SQLite shutdown nor a custom SQLite allocator can free
memory still referenced by VFS files or SHM nodes. Registration failures free the
unregistered context and leave the output null. Capacity or permission failure
does not select the default VFS.

The stock WinVFS instances have no policy. They retain their creation attributes,
temporary-file selection, locking, sharing, WAL, and deletion behavior. Mixing a
stock and private connection with the same cached SHM node is rejected; the code
does not create a second lock domain for the same filename.

The small Rust wrapper returns the retained C string. System SQLite and SQLCipher
do not implement the extension and return `SQLITE_NOTFOUND`. Only real Windows
bundled builds compile the C extension and link Advapi32. No global syscall hook,
process token change, default-DACL change, worker impersonation or post-creation
ACL repair is used.

## Creation, reuse and deletion

- `winOpen` covers DB, WAL, journal and temporary files. Creation supplies the
  explicit descriptor and validates the returned handle before SQLite uses it.
- Both SHM opens in `winOpenSharedMemory` pass the same policy into
  `winHandleOpen`, including its read-only fallback. Cached SHM reuse requires the
  same policy and validates the existing shared handle.
- Validation rejects another owner, extra or broad ACL entries, null ACLs,
  multiple links and leaf reparse objects. The accepted ACL shapes match the
  existing private SQLite file contract. Existing files are not repaired.
- `xDelete` can bypass `xOpen`; the private VFS opens and validates its deletion
  handle, then sets disposition on that handle. Cached SHM cleanup carries the
  node's own VFS policy. Stock deletion still uses the original system call.
- Private `DELETEONCLOSE` opens require `EXCLUSIVE`, so validation failure cannot
  delete a pre-existing unqualified file. Upstream temporary opens already use
  both flags. Temporary paths remain upstream-selected; this does not assert
  that they are confined to the private database root.

## Validation status

The source-pinned db23 native diagnostic established that a file created through
ordinary `fs::write` can have an owner different from the effective `TokenUser`.
That ordinary operation does not use this VFS and cannot be repaired by it. The
strict rejection is retained as negative evidence. Positive qualification must
create files through the actual opt-in SQLite backend.

At this implementation stage, formatting and diff checks have run. Native tests
for DB/WAL/SHM/temp, read-only opens, same-owner reuse, mixed SHM policy, stock VFS
behavior, and unmodified rejection of existing wrong-owner/broad-ACL objects are
being added as a separate stage. No native VFS pass is claimed here.

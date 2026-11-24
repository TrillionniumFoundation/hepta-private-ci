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

Formatting, diff checks and an independent actual-source MSVC Rust `--tests`
typecheck passed. The typecheck found and resolved three Rust compilation errors;
it did not compile, link or execute the Windows C backend.

Eight native tests now cover DB/WAL/SHM/temp, read-only SHM recreation, same-owner
reuse, mixed SHM policy, unchanged stock VFS selection, and unmodified rejection
of existing wrong-owner/broad-ACL objects through the actual VFS functions. A
same-user thread-token control duplicates the current token only on a dedicated
test thread, verifies registration/reuse, restores the original thread state
with RAII and checks restoration. This does not qualify a different account or
distinguish thread-versus-process SID selection from results alone; that selection
also depends on the source audit. Wrong-owner fixtures first observe the actual
owner and may use an OS-authorized owner group. An unavailable attack fixture is
an explicit qualification failure, not a skipped or weakened assertion.

The source remains a non-workspace path dependency. Adding it as a workspace
member would unnecessarily activate unrelated SQLCipher/bindgen features under
workspace-wide `--all-features`. Instead, `native-probe` is an independent locked
package that depends on the real vendored crate with `bundled` and directly
references its actual test source. It has no copy of the C implementation. Its
15-package resolved graph uses the existing pinned versions and was checked with
`cargo metadata --locked --offline` for the MSVC target. The production workspace
lock and broader SQLx consumer graph remain separate qualification requirements.

The Windows workflow runs this probe before heavier consumers and uploads its
source/lock binding and complete log immediately. `probe_receipt.py` rejects a
zero-test or partial pass and requires all eight cases, the original timeout and
retry defaults, and unchanged tracked source. Existing primitive and consumer
steps continue after a probe failure; no positive requirement is removed.

No native C/VFS pass is claimed until that real Windows probe succeeds.

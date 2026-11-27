# Explicit creation ownership for private SQLite files on Windows

This staged change addresses the observed native file-owner mismatch. It does
not qualify database pathname identity, ancestor confinement, a writer fence,
or a complete current-cut recovery proof. The existing unavailable recovery
entry points remain unavailable. The eight-case Windows C/VFS probe passed at
source `804ac018433ff08dfd195e93eed936394baf5053`; the qualification scope and
reproducible source binding are recorded below.

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

Formatting and diff checks passed. An independent actual-source MSVC Rust
`--tests` typecheck passed for the vendored wrapper and native test modules. It
found and resolved three Rust compilation errors; it did not compile, link or
execute the Windows C backend or the broader SQLx consumer graph.

Eight native test cases are defined for DB/WAL/SHM/temp, read-only SHM recreation, same-owner
reuse, mixed SHM policy, unchanged stock VFS selection, and unmodified rejection
of existing wrong-owner/broad-ACL objects through the actual VFS functions. A
same-user thread-token control duplicates the current token only on a dedicated
test thread, verifies registration/reuse, restores the original thread state
with RAII and checks restoration. This does not qualify a different account or
distinguish thread-versus-process SID selection from results alone; that selection
also depends on the source audit. Wrong-owner fixtures first observe the actual
owner and may use an OS-authorized owner group. An unavailable attack fixture is
an explicit qualification failure, not a skipped or weakened assertion.

The read-only case opens the main database read-only and permits writable SHM
recreation. It does not force the separate OS access-denied branch that retries
SHM with read-only access; policy propagation through that branch is supported by
source review, not by a claimed native branch execution.

The source remains a non-workspace path dependency. Adding it as a workspace
member would unnecessarily activate unrelated SQLCipher/bindgen features under
workspace-wide `--all-features`. Instead, `native-probe` is an independent locked
package that depends on the real vendored crate with `default` and `bundled` and directly
references its actual test source. It has no copy of the C implementation. Its
17-package lock uses the existing production-pinned versions and was checked with
`cargo metadata --locked --offline` for the MSVC target. The production workspace
lock and broader SQLx consumer graph remain separate qualification requirements.

The Windows workflow runs this probe before heavier consumers and uploads its
source/lock binding and complete log immediately. `probe_receipt.py` rejects a
zero-test or partial pass and requires all eight cases, the original timeout and
retry defaults, and unchanged tracked source. Existing primitive and consumer
steps continue after a probe failure; no positive requirement is removed.

The first native attempt, run `45451454733` at source
`051be3cda3aad7a145830884a45999f2e549278f`, failed before C compilation or test
execution. Disabling the vendored crate's default features omitted `pkg-config`
and `vcpkg`, although its upstream build script still typechecks code using both.
The probe now enables the same seven SQLite features as the production graph:
`bundled`, `bundled_bindings`, `cc`, `default`, `min_sqlite_version_3_45_3`,
`pkg-config`, and `vcpkg`. Its independent lock retains production versions,
including pkg-config 0.3.32 and vcpkg 0.2.15. Locked MSVC-target metadata passes;
that metadata is not a native C pass. Artifact `14947777845` preserves the failed
build log, false qualification receipt and exact source binding; its ZIP SHA256 is
`58b5b9ef18ade1ad71b471f4a0836655bcddcd9244bd8bb3fc62232c08bb3e2f`.

## Recorded Windows C/VFS qualification

The original Windows run [45458365304](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45458365304)
at source `804ac018433ff08dfd195e93eed936394baf5053`, tree
`a7c03f0857f64d3644c019113ab9c37ae7e7d644`, compiled the actual bundled
Windows C implementation and ran all eight native cases: **8 passed, 0 skipped**,
exit 0. The test build took 10.42 seconds and the eight-case execution took
1.542 seconds; these are observations of this run, not a performance benchmark.
No retry or flaky-test result appeared in the native log.

[native-804ac0-receipt.json](native-804ac0-receipt.json) records the complete test
names, seven actual SQLite features, source identities and qualification limits.
GitHub artifact `14952131334` is 10,212 bytes with SHA256
`5ebc0adf80f4f06d0a475fe444762e587e6ae05704fa1243aea28e700006b8b0`.
The native log SHA256 is
`bc19dac031430d96c619644f80c7570df7901ffd6f85dbe725554a86164b543c`.
The artifact contains the original log, native receipt, exact source head,
compiler version, dependency metadata and independent probe lock.

All 16 source inputs in the original native receipt were independently checked
against `git show <804 source>:<path>`. For each text blob, LF normalization
followed by Windows CRLF conversion produces the exact native receipt digest;
the repository receipt retains both the Git-blob and Windows-checkout digests.
This distinction avoids treating checkout line endings as an input change.
The tracked checkout remained clean. The artifact and log bytes were hashed
independently as well; the receipt is a record of those checks, not a new test run.

The earlier 051 build failure above remains part of the history. After the
feature repair, a separate locked, offline Linux check at source
`41af7ab4d29018d46d2052b4790dd0347e02f356` also compiled the real upstream build
script and Linux bundled C successfully. That Linux check did not execute the
Windows backend or qualify the SQLx consumer graph.

The eight Windows cases qualify only this isolated VFS probe. They do not qualify
different-account impersonation, force the OS access-denied read-only SHM fallback,
establish ancestor confinement or a current-cut writer fence, or establish the
broader SQLx, Matrix SDK or H4 power-loss contracts. Consumer results require their
own source-bound logs; a successful C probe alone does not supply them.

## Explicit SQLx consumers

`SqliteConfig::open_private_read_write_pool` and
`SqliteConfig::open_private_durable_evidence_pool` select the registered VFS before
SQLx starts any worker connection. Their ordinary state/evidence settings match
the existing generic methods. The generic writable, durable and read-only
methods keep the stock backend. Registration failure is propagated and never
retried with the stock VFS.

The private cognitive constructor, v2 migration fixture, recovery candidate
creation/reopen, automation constructor and the `hepta-matrix-store` business
SQLite constructor opt in explicitly. The Matrix SDK
`ClientBuilder::sqlite_store_with_cache_path` encrypted cache does not use this
VFS; this change does not extend its existing Windows `create_private_directory`
policy or qualify that cache's private-owner/ACL contract.
The already-private recovery checkpoint helper selects the same VFS. Cold-image
source fixtures also use the private API. Generic evidence/authbus/operations
paths are not reclassified as private by this change. Existing directory, object
identity and recovery checks remain separate requirements; in particular the
unavailable identity-bound and immutable recovery openers remain unavailable.

The opt-in H4 harness inspects a live cognitive writer with a separate read-only
connection. It uses `SqliteConfig::with_private_creation_owner` to share the
writer's policy while preserving its existing read-only, single-connection and
five-second timeout settings. The helper only selects the Windows VFS; it does
not validate a directory or claim H4 physical power-loss qualification. The
normal `--lib` consumer tests do not compile the H4 example, which requires
`qualification-cognitive-write`; the two SQLx cases exercise the shared helper's
worker behavior separately. The qualification-only `product_database` importer
remains outside this change: its
Windows directory/owner checks need an independent implementation, and changing
its VFS alone would not establish its stated private-snapshot contract.

Two additional state tests exercise actual SQLx workers: multiple simultaneous
private pool connections with live DB/WAL/SHM validation and close/reopen, and a
private read-only connection with rejected writes. Both inspect the actual VFS
pointer through a locked SQLite handle and remain part of the normal Windows
consumer step. Their results belong to the separate consumer qualification;
the eight-case native receipt does not establish their outcome.

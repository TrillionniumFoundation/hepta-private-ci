# Fleet rename metadata witness

This is a test-only diagnostic candidate. It is not a permissions fix, and no
Rust build or native execution has qualified it.

## Retained failure

At source `97ab00451799667faebac2c455a1e3176ebc90cb`, complete Intel and ARM
macOS 15.x artifacts each report 37 Fleet unit cases passing and four failing.
All four failures are at `install.rename` with OS error 13. Later cleanup
`mode.set_permissions` errors with OS error 2 are secondary. The actual
`darwin-sandbox` test commands were distinct, non-cached actions. Successful
XML generation is not a successful test execution.

Two separate Darwin 25.6 controls succeeded in renaming both 0555 and 0700
staging directories, including a synthetic sandbox with the same broad
file-write policy structure. Those controls do not reproduce the CI OS,
filesystem, actual generated sandbox profile, or fixture object state. They
do not justify changing production mode values or publication order.

## Candidate boundary

Only `cfg(all(test, target_os = "macos"))` builds observe an already failed
rename, before the existing cleanup changes modes or removes the staging tree.
The original rename is attempted exactly once. Its original `Result` and I/O
error are returned without reconstruction or wrapping. Existing cleanup,
durability calls, mode values, assertions, and deadlines are unchanged.

The observer performs at most three `symlink_metadata` calls and three
`canonicalize` calls, for fixed staging, final, and source-parent roles. It
records file type, mode, uid/gid, device/inode/link count, typed I/O errors,
hashed path spellings, and canonical parent relationships. Destination
`NotFound` is kept distinct from access denial; it is not reduced to `exists`.
Paths, contents, directory entries, and environment values are not printed.

The record explicitly describes a sequential, non-atomic snapshot after the
failed syscall. Metadata is not an effective-access check and does not reveal
ACLs, filesystem type, sandbox policy decisions, or the process effective uid.
No new dependency or unsafe code is introduced to obtain those extra fields.
Canonicalization resolves the fixed paths; it is not recursive directory
enumeration. There is no new process, sleep, wait, permission change, rename
retry, or additional file-content read.

The diagnostic writes at most 8192 bytes through one best-effort stderr write.
A short/failed write is not retried and does not replace the original error;
missing or incomplete diagnostic output is not interpreted as a successful
observation. Successful renames produce no new output. Normal dependency
builds, including Fleet used by Supervisor or Agentd, do not inherit this
crate's `cfg(test)` and therefore do not emit this diagnostic.

The generic Bazel macro already includes `src/**/*.rs`; Cargo uses the explicit
test-only module. Cargo manifests, BUILD declarations, and both production
locks remain unchanged. Actual macOS execution of the original four cases is
still required to obtain the missing object-state evidence. This candidate
does not establish the reason for their permission failures.

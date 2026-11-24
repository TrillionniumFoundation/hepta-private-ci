# Windows private storage: contract and qualification boundary

Status at source preparation: **native Windows execution pending**. Rust formatting
and a source review are not runtime qualification. The exact integrated commit,
toolchain, API errors and test results must come from the Windows workflow artifact.

## Scope

The prior `hepta-prompt-registry` and `hepta-contracts/final_use_store` implementations
returned `UnsafeStateDirectory` for every non-Unix operation. This candidate supplies
a bounded Windows backend through `codex-utils-path::windows_private`. Their
`forbid(unsafe_code)` declarations remain intact; their Unix storage implementations,
serialized schemas, admission checks, nonce semantics and authority checks are
unchanged. Unsupported platforms continue to reject storage.

This is distinct from fixing test fixtures that opened a directory with ordinary
`File::open`, or flushed a copied SQLite file through a read-only handle. Those
fixtures now request an appropriate handle and execute the real flush operation.

## Native contract

| Requirement | Mechanism | Failure behavior |
| --- | --- | --- |
| Bound the root to an opened object | `NtCreateFile`, absolute local disk path, retained handle, no delete sharing | Reject relative, UNC and device namespaces; directory rename cannot rebind the owner |
| Reject redirection | `OBJ_DONT_REPARSE` on every lookup; file-only `FILE_OPEN_REPARSE_POINT`; exact-handle attributes and kind check | Reject reparse roots, reparse ancestors and reparse children |
| Private owner and access | Effective token user, `GetSecurityInfo` on the same handle, protected DACL containing exactly one owner allow ACE with file-all-access | Reject null, broad, inherited or unfamiliar ACLs; never repair an existing object's ACL |
| Safe creation | Explicit owner-only security descriptor supplied at `NtCreateFile` creation | No permissive create-then-chmod interval |
| Bind every child lookup | Single bounded leaf name and `OBJECT_ATTRIBUTES.RootDirectory` | Reject path separators, parent traversal, alternate streams and non-regular/multi-link files |
| Atomic replacement | `SetFileInformationByHandle(FileRenameInfoEx)` with `REPLACE_IF_EXISTS` and `POSIX_SEMANTICS` on a validated source, relative destination under the retained root | Propagate unsupported-version and native errors; no classic-rename, path-copy or delete fallback |
| Real persistence barrier | File `sync_all`, then the retained directory's actual `sync_all` | Never substitute success or a no-op; the prompt owner retains post-rename poisoning |
| Exclusive ownership | Existing OS `File::try_lock` on the private lock file | A concurrent writer is rejected; kernel releases the lock on process exit |

Only **local NTFS with persistent ACLs** is accepted. A volume GUID is required
from the same handle, also rejecting drive-letter mappings to network shares.
The initial directory handle
must successfully flush before authoritative files are created. Each child open
and explicit directory flush revalidates the retained root's private ACL. Existing
Windows directories with conventional inherited grants to Administrators or SYSTEM
are deliberately not silently migrated; the preexisting implementation did not
offer a Windows authority store. This is a narrow owner-only policy, not a general
Windows ACL evaluator.

Directory opens use explicit directory access rights and only
`FILE_DIRECTORY_FILE | FILE_SYNCHRONOUS_IO_NONALERT`. The `NtCreateFile` reference's
closed directory-option list does not include `FILE_OPEN_REPARSE_POINT`; that flag
is now confined to regular-file opens. Every lookup still sets `OBJ_DONT_REPARSE`,
and all returned handles undergo the same reparse/kind and owner/DACL checks.
No failure is swallowed. The general `OBJECT_ATTRIBUTES` contract documents the
no-reparse flag, while the user-mode function page lists fewer attributes; the
actual supported composition must therefore be established by native tests on
the runner, not by inferring a universal cross-version guarantee.

## Executable checks

The normal GitHub Actions workflow
`.github/workflows/hepta-windows-durable-fixtures.yml` runs:

1. Nine `codex-utils-path` native tests: real writable-directory flush; atomic
   replacement with an old reader still seeing old bytes; reopen and ACL checks;
   exclusive writer lock; root/ancestor and child junction rejection; hard-link,
   traversal and alternate-stream rejection; broad-DACL rejection without repair;
   retained-root rename rejection; a one-character rename target with a complete
   native information-buffer header.
2. Two private-registry tests: reopen with the same snapshot and writer exclusion;
   a fault injected after a real rename must poison the owner and force reopen.
3. The existing intelligence/agentd/authbus directory and schema fixtures.
4. Existing prompt-delivery and prompt-runtime consumers, exercising the real
   prompt and final-use owners rather than a mock private-storage implementation.
5. Scoped Clippy fix/check, with a dirty source diff treated as a CI failure.

All filesystem objects and ACL mutations in the added tests are synthetic and
confined to newly created disposable test directories. No real user credential
store, service configuration or existing account ACL is accessed or modified.
Junction tests use the ordinary native `mklink /J` command and do not request
privilege changes or modify sandbox environment variables.

Failures in one group do not prevent independent groups from reporting their
results. Artifacts retain the exact source commit, `rustc -vV`, command outputs and
OS error codes. A failed native primitive is a blocker, not a reason to skip an
assertion. Successful execution demonstrates behavior on that runner; it does not
simulate power loss or certify every Windows version, filter driver or device.

## Remaining boundary

SQLite recovery remains separately fail-closed on Windows:
`state/src/sqlite_recovery.rs` does not yet implement the Windows retained
database/WAL/SHM/journal snapshot guard, and `sqlite_recovery_image.rs` does not
materialize a Windows recovery image. The canonical-path fixture correction does
not close that gap. This patch does not turn those unsupported paths into success,
weaken their checks, or claim a complete Windows memory-recovery implementation.

## Primary API references

- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)
- [OBJECT_ATTRIBUTES](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes)
- [Directory access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants)
- [GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
- [FILE_RENAME_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info)
- [FILE_RENAME_INFORMATION extended flags](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information)
- [FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)
- [Directory handles](https://learn.microsoft.com/en-us/windows/win32/fileio/obtaining-a-handle-to-a-directory)
- [GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)

These references describe individual API contracts. The workflow is required to
verify their actual composition, including a writable NTFS directory handle and a
relative rename. No Microsoft Q&A answer is used as a substitute for the API
reference or as an unconditional crash-durability guarantee.

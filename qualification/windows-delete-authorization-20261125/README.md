# Windows deletion authorization: bounded native qualification

This candidate adds tests, not an execution backend. The existing 40 refused
execution attempts and production availability guards remain unchanged. The
base is the public #7070 source `04235def3c18aad1ba5044d84ddd17494cc646ec`, tree
`3b9c343468a9a3abecffbb22b0c1b20d462bc5a2`.

## Preregistered questions and counts

There are **4 Rust tests, 18 deletion matrix cells, and 1 combined controlled
write positive/outside negative scenario**. Cells are not distinct Rust tests.

1. Twelve cells distinguish target `DELETE` from parent `FILE_DELETE_CHILD`:
   two token modes, file/empty-directory objects, and neither/target/parent
   capability grants. Both tokens use the same single restricting capability
   SID; the creation flags differ only by `WRITE_RESTRICTED`. The actual
   resulting restriction list is read back. The alternative deletion route is
   removed from the normal-identity ACL when testing one route in isolation.
2. The combined scenario requires real writes, reads, file and directory
   creation and deletion inside the controlled domain, and unchanged outside
   bytes/namespace after rejected outside write/create/delete calls.
3. Four full-restriction cells separately give the target or parent a NULL
   DACL. The other normal-identity deletion route is removed. The preregistered
   expected result is successful deletion, demonstrating a limit of a token
   alone. A NULL DACL is explicitly distinguished from an empty DACL.
4. Two cells lower the derived token and both parent and target to Low
   integrity, read their labels back, and attempt real deletion with NULL
   DACLs. Successful deletion would show why Low integrity alone does not
   protect an already-Low outside object.

The helper's `Dacl::Identity` fixture uses an explicit **WD (World) ACE** so the
normal access check permits the selected mask. WD is never a restricting SID.
The capability list contains no user, logon or World SID. An already-restricted
source token is rejected rather than assuming its restriction-list intersection.

## Safety and interpretation

All ACL/label changes apply only to newly owned temporary children. DACL and
label installation/readback use the same handle; setup handles are closed
before fresh `DeleteFileW`/`RemoveDirectoryW` operations. Files are not readonly
and directories are empty. No previously granted DELETE handle performs the
operation. A thread-local RAII guard restores impersonation, checks that the
thread again has no impersonation token, and only then permits fixture cleanup.
Every deletion cell checks the actual result and resulting namespace.

The controlled scenario uses thread impersonation in the test process. It does
not qualify arbitrary child-process startup, loader reads, ambient handles,
reparse or hard-link topology, an unrestricted filesystem namespace, or Windows
weight publication. No account, system directory, service or installed sandbox
is changed. A finite successful ACL domain cannot discharge the NULL-DACL or
Low-object counterexamples or justify removing the existing guards.

Possible general enforcement still needs a separately demonstrated OS boundary,
such as a correctly mediated broker/minifilter or an isolated filesystem/VM;
this test does not implement or claim any of those mechanisms.

## Evidence status before native execution

The final two test files were checked with Rust 1.96.0 against the actual
`windows-sys` 0.52.0 API in an isolated 27-external-package graph, all package
identities/checksums matching the production lock. MSVC `cargo check --tests`
and strict Clippy both exited zero. This is compile-only evidence, not Windows
execution or a full workspace build. The first check's E0308 integer-type error
and unused import warning are retained in the private evidence history; both
were corrected before the final checks. No native result is claimed here.

The native gate uses the actual repository test/support files through a Rust
`#[path]` module. It will record exact source/tree, source bytes, all four tests
and all 18 deletion-cell receipts. Failed expectations remain failures; there
is no skip, fallback, automatic retry, disabled sandbox check or ACL repair of
an existing object. Source execution and real CI merge identities are recorded
separately.

## Primary contracts

- [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [DeleteFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilea)
- [NULL and empty DACLs](https://learn.microsoft.com/en-us/windows/win32/secauthz/null-dacls-and-empty-dacls)
- [Mandatory integrity control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
- [Security information and required rights](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information)

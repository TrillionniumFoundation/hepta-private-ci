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

The isolated probe has a dedicated nextest configuration because repository
overrides naming unrelated workspace packages are invalid in a single-member
graph. The controller checks its timeout and JUnit configuration against the
repository defaults exactly; the local profile inherits those defaults and
retries are explicitly zero. No existing repository profile is modified.

## First native execution and fixture correction

Normal workflow run `45630787762`, exact head
`047d7d8bccf848fd5435243fd86ecaa24c431e6c`, ran all four tests once:
one passed, three failed, zero skipped and zero retried. Strict native Clippy
passed. The combined controlled-write/outside-denial scenario passed. The three
deletion groups failed while opening an owned object for DACL installation,
with OS error 5, before any completed deletion-cell receipt. They establish no
deletion outcome. The original artifact `15031295237` is 5,520 bytes, SHA-256
`df3c8a80d895fe446301ab00a7860c5fa2ea61a5876249b55d7b70e5a0ec8d4e`.

The next fixture configures each parent before creating its child, then installs
and reads back the child's exact final policy. This prevents parent installation
from changing an already-existing child's inherited ACL during setup. All final
policy masks, token flags, deletion expectations and namespace assertions stay
unchanged. The old error omitted the failing path, so ACL propagation is a source
hypothesis, not an independently observed cause of that failure. New context
records the exact object and checks the original thread identity before setup.
The revised source still requires its own native result.

## Second native execution and unchanged-policy diagnosis

Run `45633358720`, source `b920292eae6999bfaf51febf6efc0c7e0a4317ae`,
ran all four tests once: two passed and two failed, with no skipped or retried
cases. The controlled-write scenario and both Low/NULL-DACL deletion cells
passed. Fifteen deletion cells completed: ten normal-policy cells, three
NULL-DACL cells and the two Low cells. Native strict Clippy passed.

`Full + Directory + Target` failed its original allowed/absent assertion:
`RemoveDirectoryW` returned OS error 5 and the directory remained. The final
NULL-parent/directory cell also returned OS error 5, without an operation label
in that version. Its exact stage is not inferred. Artifact `15030733251` is
5,907 bytes, SHA-256
`e0990616a26c289fcaab8c749318c3d28b300f55d17f5713c295918f45b5c305`.

The next diagnostic leaves every ACL mask, token flag, deletion API, expected
result and original gate unchanged. Under the same token and fixture ACL, it
only opens and closes the two affected existing directories with four explicit
access masks: DELETE alone, and combinations with SYNCHRONIZE and
FILE_READ_ATTRIBUTES. Each is observed in synchronous and overlapped modes,
before the original deletion and, if it fails, afterwards. All successful
handles must close before deletion. No DELETE_ON_CLOSE, I/O, namespace or ACL
mutation is performed by the diagnostic. At most 32 opens are added.

These observations will distinguish authorization for a handle from behavior
of the original path-based API. They are not a claim about that API's internal
implementation. The original failure expectations remain failures if reproduced;
this diagnostic cannot qualify the matrix merely by printing observations.

## Third native execution and descriptor authorization diagnostic

Run `45635681589`, exact source `74d4170593e5161d93fe903f5e1ddc960316727d`,
again ran all four tests once: two passed, two failed, no skips or retries, and
the same fifteen deletion cells completed. All 32 new `CreateFileW` observations
returned OS error 5, including DELETE-only overlapped opens before and after
each failed deletion. The added error context identifies the NULL-parent /
directory failure as `RemoveDirectoryW`, rather than fixture cleanup. Artifact
`15032403983` is 6,184 bytes, SHA-256
`1fa6bc68ed937fd2f32e82fefc76837aed5166192b2b6130531c6ad9258c99bd`.
These observations do not establish a particular hidden access mask inside
`RemoveDirectoryW`.

The next diagnostic asks a separate authorization question without changing
the original policy. For the same two failed directory scenarios, the original
thread identity opens parent and target with READ_CONTROL and all sharing,
queries OWNER, GROUP and DACL through that handle, and closes the filesystem
handle. The returned descriptor allocation remains alive during the checks.
Exact DACL bytes and control flags are recorded; owner and group must be present
for AccessCheck but their SID bytes are not logged. No SACL query, privilege
adjustment, ACL change or filesystem write is added.

Inside the existing restricted-token impersonation scope, OpenThreadToken with
TOKEN_QUERY obtains the actual current impersonation token. OpenAsSelf only
selects the identity used to authorize that query handle; it does not substitute
the process token. The diagnostic records this token's privilege LUIDs and
attributes, then performs AccessCheck for DELETE and MAXIMUM_ALLOWED on each
descriptor using the file-object generic mapping. Buffers and privilege counts
are bounded. The API result, authorization status and granted mask are separate
fields; an API error fails the diagnostic as unknown authorization, never as
an ACL denial.
No token is duplicated or changed. The query handle is dropped before the
existing opens and deletion; the original impersonation restoration remains.

There are at most **16 AccessCheck observations**: two scenarios, before and
after a repeated deletion failure, two descriptors, and two requested masks.
They are neither new tests nor completed deletion cells. The four test
identities, all original token/ACL masks, 32 open observations, delete calls,
namespace assertions, zero-retry setting and 18-cell qualification gate remain
unchanged. API failures or repeated original failures do not qualify the matrix.

AccessCheck evaluates the captured descriptor and token. It does not establish
path traversal, sharing, current object identity, mandatory-integrity behavior,
filesystem semantics or a race-free snapshot. Comparing its result with the
unchanged path operations can narrow the cause, but cannot by itself prove a
safe launcher or discharge the original 40 refused-execution guards. This source
change has no native result until its own exact source is executed.

## Primary contracts

- [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [DeleteFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilea)
- [NULL and empty DACLs](https://learn.microsoft.com/en-us/windows/win32/secauthz/null-dacls-and-empty-dacls)
- [Mandatory integrity control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
- [Security information and required rights](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information)
- [AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck)
- [OpenThreadToken](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openthreadtoken)
- [GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)

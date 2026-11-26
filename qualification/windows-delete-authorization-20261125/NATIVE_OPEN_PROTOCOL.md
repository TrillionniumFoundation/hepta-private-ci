# Fixed Win32 and absolute NT open observations

## Scope fixed before implementation

Base: `45f6619775f9ccbef031a0c2940912394d5559bf`. This is one independent
diagnostic test with four fresh, owned directory fixtures and exactly eight
open attempts. It does not alter the four original tests, their eighteen
deletion cells, the six LIST observations, any production execution guard,
or the original twenty-minute job and zero-retry settings. The original
matrix remains unqualified when any original assertion fails.

The hypothesis concerns the Win32 and NT call layers. The documented inputs
below do not prove that both wrappers issue an identical internal kernel
request. In particular, requested access is distinct from granted access,
and descriptor-only AccessCheck is distinct from path-based I/O authorization.

## Fixtures and fixed permissions

All four use the existing Full restricted token constructor, including its
same capability-only restricting SID check and unchanged privilege flags.
`FA` means the existing FILE_ALL_ACCESS mask. `WD` is the existing World
identity ACE in this synthetic fixture, not a new identity or authority.

| Scenario | Parent DACL | Target DACL |
| --- | --- | --- |
| Target | WD: FA without FILE_DELETE_CHILD | WD: FA; capability: DELETE |
| NullParent | Explicit NULL DACL | WD: FA without DELETE |
| NullTarget | WD: FA without FILE_DELETE_CHILD | Explicit NULL DACL |
| Neither | WD: FA | WD: FA |

Parent policy is installed before target creation. The existing same-handle
setter verifies the entire DACL bytes. No ACL is changed between the paired
opens. Every original-identity descriptor/attribute observer closes its
filesystem handle before impersonation; no parent handle supplies authority
to either open. The existing RAII token restoration and ERROR_NO_TOKEN
confirmation remain in force. Cleanup occurs only after observations and
restoration, using the original identity on these owned fixtures.

## Exactly two calls per fixture

1. CreateFileW: explicit DesiredAccess is DELETE only; OPEN_EXISTING;
   FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE;
   FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT |
   FILE_FLAG_OVERLAPPED; NULL security attributes and no template handle.
2. NtCreateFile: the same explicit DELETE and share mask; FILE_OPEN;
   FILE_OPEN_FOR_BACKUP_INTENT | FILE_OPEN_REPARSE_POINT; an absolute local
   drive NT path of the form `\??\C:\...`; RootDirectory is NULL and object
   attributes contain only OBJ_CASE_INSENSITIVE (not a parent capability).
   No FILE_DIRECTORY_FILE, FILE_NON_DIRECTORY_FILE, synchronous-I/O option,
   DELETE_ON_CLOSE, new privilege or extra requested access is supplied.

Only an existing absolute local drive fixture path is accepted; relative,
UNC, device, dot/parent, embedded-NUL and excessive-length inputs fail.
The native name is length-delimited UTF-16. The absence of a native type
selection flag is deliberate: the documented FILE_DIRECTORY_FILE compatible
option list does not include FILE_OPEN_REPARSE_POINT. Existing ordinary
directory metadata is independently checked before and after the calls.

Every successful handle is queried with NtQueryObject(ObjectBasicInformation)
for its actual GrantedAccess and then explicitly closed. Query failure is
logged as unknown and fails the diagnostic, without reopening or adding
rights. Failed opens have no GrantedAccess evidence. Native NTSTATUS is
logged separately from RtlNtStatusToDosError; no reverse mapping is inferred.
NtCreateFile's documented terminal return is used. An unexpected pending
return is a protocol error: no completion/grant is inferred and the isolated
test process records only a best-effort fixed message (no panic-on-error print
macro or propagated I/O error) and unconditionally aborts, so no stack
buffer potentially still used by I/O is unwound. This exceptional path is
incomplete; normal per-handle cleanup is not claimed for an aborted process.
For a nonzero, nonnegative terminal status with a valid returned handle,
take RAII ownership before logging, query and close that actual handle, then
fail as unknown/incomplete. A raw negative status never establishes ownership
of an unspecified output handle. Only STATUS_SUCCESS qualifies as native
success in this fixed diagnostic.

The NULL-target pair is the required successful control; each success must
contain DELETE in GrantedAccess. Neither is the required access-denied
control. Target and NULL-parent results are observations, not assertions
that a previously failing positive now works. Unexpected status, invalid
handle, query failure or close failure makes the diagnostic incomplete.

## Observation integrity and accounting

Within a pair, use one token.run scope. Compare token identity, semantic
token privilege entries, integrity level and mandatory policy before/after;
do not compare structure padding or volatile allocation/accounting fields.
Capture complete self-relative OWNER/GROUP/DACL/LABEL descriptor bytes on
both objects outside impersonation and require exact before/after equality.
No owner/group SID is printed. Record equality and descriptor sizes, plus
the existing synthetic DACL and authorization observations. The target must
still exist, remain an empty ordinary directory, and have unchanged observed
attributes and label. This diagnostic never invokes a deletion API.

Use a separate `native_open` integration target, without filtering the
original library or LIST target. The controller retains every command's
real exit status, runs the independent observation after original failures,
and validates exactly one diagnostic test, eight distinct observations,
four invariants and no skips/retries. Original verifiers and assertions stay
unchanged; diagnostic completion cannot override an original failed gate.

## ABI and dependency evidence

Use the existing pinned windows-sys 0.52.0 official generated declarations
for NtCreateFile, OBJECT_ATTRIBUTES, IO_STATUS_BLOCK, NtQueryObject and
PUBLIC_OBJECT_BASIC_INFORMATION. The five explicit added feature gates are
Wdk_Foundation, Wdk_Storage_FileSystem, Win32_System_IO, Win32_System_Kernel
and Win32_System_WindowsProgramming. This is a manifest
change, not an unchanged pin: record dependency identities and run the
repository's actual Bazel lock-update/check requirements. No hand-copied
struct layout substitutes for the dependency gate.

Primary contracts, checked before implementation:

- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)
- [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [RemoveDirectoryW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-removedirectoryw)
- [NtQueryObject](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntqueryobject)
- [RtlNtStatusToDosError](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-rtlntstatustodoserror)
- [IO_STATUS_BLOCK](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_io_status_block)
- [windows-sys 0.52.0 generated WDK file APIs](https://github.com/microsoft/windows-rs/blob/0.52.0/crates/libs/sys/src/Windows/Wdk/Storage/FileSystem/mod.rs)
- [windows-sys 0.52.0 generated object APIs](https://github.com/microsoft/windows-rs/blob/0.52.0/crates/libs/sys/src/Windows/Wdk/Foundation/mod.rs)

This protocol is not a claim of Windows filesystem confinement, safe native
subprocess execution, successful deletion, or completion of the existing
production WRITE_RESTRICTED blocker. The unsafe external-delete result and
the Full-token directory positive failures remain separate facts.

## Candidate qualification boundary

Source preparation and dependency metadata do not execute these Windows
APIs. The original 45f result remains two passing and two failing matrix
tests with fifteen completed deletion cells. Its separate LIST diagnostic
completed all six observations; the added LIST bit did not resolve either
directory positive failure. The new eight-open result is pending until its
own exact-source Windows run. A successful diagnostic will mean observation
completion and its stated controls only, not that the original gate passed.

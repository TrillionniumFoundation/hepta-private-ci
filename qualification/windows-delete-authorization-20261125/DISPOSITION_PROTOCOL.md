# Fixed DELETE-only handle disposition contract

This independent contract follows the actual 10fb open-only result. It does
not replace or qualify the original Win32 deletion matrix. All original
four tests, 18 deletion cells, LIST observations and 20-open observations
remain unchanged, including their failures. Product ACLs and the 40 guarded
execution attempts are outside this candidate and remain unchanged.

## One test and four fresh owned empty-directory fixtures

Run one separately named integration test exactly once, with four scenarios
in this order: Target, NullParent, NullTarget, Neither. Use the same Full
restricted-token constructor and exact parent/target policies as the 10fb
native-open test. Finalize the parent ACL before child creation. Do not add
SYNCHRONIZE, READ_ATTRIBUTES, LIST, privileges, inherited handles or a parent
handle to the restricted operation. No auxiliary-rights experiment is part
of this protocol.

Original-identity observers capture full OWNER/GROUP/DACL/LABEL bytes and
ordinary-directory attributes before impersonation, close their handles,
and verify the empty namespace. The restricted operation opens the absolute
local NT path with DELETE only, NULL RootDirectory, FILE_OPEN, all three
share flags and the unchanged `0x00204000` options. NtQueryObject must return
the expected complete extent and GrantedAccess exactly DELETE before the
handle may be used. A denied open has no granted-access observation.

For Target, NullParent and NullTarget, use that same verified handle for one
NtSetInformationFile call: FileDispositionInformation (13), a bound SDK
FILE_DISPOSITION_INFORMATION with DeleteFile=1. Then close that handle once
with NtClose. Do not query/reopen it after marking. After impersonation is
restored, the target must be absent and the parent must remain an empty
ordinary directory with unchanged full descriptor and label. Both metadata
observations reject readonly/reparse objects; ordinary parent attributes are
recorded before/after rather than assumed immutable across child deletion.

Neither must fail at the open with STATUS_ACCESS_DENIED, leave the target
present and empty, and never attempt disposition. An unexpected successful
Neither open is queried and closed, reported as a failed control, and is
never used to delete. Its full target descriptor/metadata must stay unchanged.

Semantic token identity, enabled privileges, integrity and mandatory policy
are compared within the same impersonation interval before and after the
operation. All original-identity query handles are closed before it. Cleanup
only runs as the restored original identity after the observation; no ACL
repair or alternate deletion attempt is part of the tested operation.

## Terminal status, errors and lifetime

Only exact STATUS_SUCCESS is a complete positive result. NtCreateFile
informational success with a valid handle takes ownership, queries and
closes it, then fails the contract. Query failure or an unexpected grant also
closes and fails, without marking. Native error status and mapped Win32 error
are recorded separately; no error is converted into a passed observation.

For NtSetInformationFile, record its returned NTSTATUS and the IO_STATUS_BLOCK
separately. Both terminal statuses must be exact success. Close is required
even after a terminal disposition failure; its own raw status is retained.
An incomplete close is a failed contract, not a retry or another close.
The code closes before formatting the mark result, so the CLOSE log line
precedes MARK even though the API order is mark then close. NtClose is not
used as a wait for pending I/O or as proof of completion by itself.

A returned STATUS_PENDING from open or disposition is outside this bounded
protocol. The fixture performs one fixed best-effort stderr write and aborts
the isolated test process without unwinding the active buffers or handle.
It does not wait, add synchronization authority or infer completion from the
initialized IOSB sentinel. Failure and process termination remain visible to
the original nextest gate and the always-upload artifact step.

## Accounting and interpretation

The existing job remains 20 minutes and zero retries. Keep the original
four commands byte-for-byte; append one `just test --test native_disposition`
command with the same nextest profile, one test thread, output policy and
zero-retry setting. The strict Clippy command already covers all targets.
The new parser requires one exact binary/test PASS, zero skips, four ordered
open records, three successful mark/close pairs, and four complete scenario
contracts. Unknown, missing, duplicate, mismatched or denied positive records
fail. It records this contract separately and never sets the original matrix
qualification result.

If this succeeds, it establishes actual deletion through a DELETE-authorized
native handle on these owned fixtures, while the original pathname API
result remains unchanged. It neither traces Win32's internal request mask
nor repairs WRITE_RESTRICTED outside deletion or arbitrary child-process
filesystem confinement. If it fails, keep the exact open/query/mark/close/
namespace phase and original status; do not broaden permissions or choose
another API to obtain success.

## Fixed primary contracts and bindings

- [NtSetInformationFile](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntsetinformationfile):
  class 13 requires a DELETE-opened handle and permits only close after marking.
- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile):
  the existing explicit access, path, sharing and open options are retained.
- [NtClose](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntclose):
  closing does not itself guarantee that all I/O has completed.
- Microsoft windows-sys 0.52.0 supplies NtCreateFile, NtSetInformationFile,
  NtQueryObject, NtClose, FILE_DISPOSITION_INFORMATION, IO_STATUS_BLOCK and
  the FILE_INFORMATION_CLASS integer type through already enabled features.
  The SDK binding omits the class-13 name, so its typed value is taken from
  the official NtSetInformationFile table, not the unrelated Win32 enum.

At source preparation there is no native result for this contract. The prior
10fb result remains 2 passed / 2 failed in the original matrix.

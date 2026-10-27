# Retained private artifacts on Windows

## Development and callers

`private_file_identity_windows.rs` and its private security module are the one
canonical State recovery predicate for complete Windows filesystem identity.
`private_artifacts_windows.rs` provides the retained directory/file backend;
`private_artifact_directory_windows.rs` contains its private native operations.
State recovery, Operator acceptance and Shadow qualification consume this same
backend. Cargo dependencies flow into `codex-utils-path`, never back into State.

| Caller | Operations | Authority that remains with the caller |
| --- | --- | --- |
| State `sqlite_recovery_io` | Private new output, real directory barrier | Recovery guards, acknowledged identities, indeterminate disposition |
| Operator `durable_windows_artifacts` | Read/hash, private new/replace, sidecar lock | Signers, body/nonce/replay, original receipt and policy |
| Shadow `durable_windows` | Private directory bootstrap, write/read/verify/barrier | Qualification dossier, observer and current-generation policy |

Use `just fix -p codex-utils-path -p codex-state -p codex-hepta-operator-acceptance -p codex-hepta-shadow-qualification --target x86_64-pc-windows-gnu --locked`
for scoped static checking. Execute native tests through `just test`; a cross
check cannot qualify Windows directory durability. Dependency edits require the
actual repository-root `just bazel-lock-update`, even if the resulting module
lock is unchanged. Do not edit generated locks to manufacture agreement.

## Technical contract

`WindowsFileId` holds the volume serial plus all 16 file-ID bytes.
`PrivateFileIdentity` additionally holds kind, link count, allocation/length,
timestamps, attributes and the exact validated owner/DACL descriptor. Public
borrowed-`File` inspection reads facts about that same object; its opaque result
cannot construct any writer. State retains its full snapshot comparisons and
maps inspection failures to the original indeterminate result.

`RetainedPrivateDirectory::open_existing` requires a canonical absolute fixed
local NTFS path. It retains every ancestor and the final directory, rejects
reparse objects and replacement aliases, obtains an actual read/write directory
handle with BACKUP_SEMANTICS and OPEN_REPARSE_POINT, and compares complete
volume/128-bit identity and validated descriptor before granting its limited
child operations. Existing owner/security is never changed or repaired.

`create_new` creates exactly one absent leaf under a retained existing parent,
with an explicit current-user owner and protected current-user-only inheritable
DACL supplied atomically at creation. It verifies the created identity and
original ancestry, and flushes the parent before acknowledging creation. It
never adopts an existing incompatible directory. Callers must arrange an
explicit new private root; a pre-existing public temporary directory is not an
admitted artifact store.

The canonical predicate preserves the original State effective-token owner
policy and trusted System/Administrators boundary. Every foreign nonzero allow
ACE, null/invalid DACL, unrecognized ACE or malformed SID/span is refused.
CreatorOwner is accepted only as an inherit-only template. File reads require
an ordinary non-reparse one-link file. Full metadata equality remains required
across immutable reads; directory mutation compares the stable full ID and
exact security descriptor while allowing its expected child-list timestamps to
change.

Names are single ordinary checked UTF-16 components. Separators, ADS, NUL,
trailing dot/space, dot traversal, DOS device names, and normalized replacement
aliases are refused. New files use exclusive NT creation relative to the held
directory, an atomic private descriptor, exact write/readback, real file flush
and then a real original-directory flush. Replacement uses a newly created
sibling and a native handle-relative rename, followed by the same barrier and
current-path identity check. Failure after any effect stays a failure; no
implicit cleanup, replay or receipt success is inferred.

`PrivateFile` owns a private `File`, opaque identity and retained parent. It
exposes bounded read/stream, verification and a real sync request. Read-only
construction cannot become a writable-directory capability. Neither public
type exports a raw FD/HANDLE, `AsRawHandle`, `Write`, writable port or an adopt
function. Sidecar lock handles deny other writers and deletion until dropped;
existing lock files receive the same owner/DACL/one-link checks.

## Native evidence and limits

The original diagnostic run 40412971928 collected actual native results on
Windows with Rust 1.96.0: ordinary `File::open(directory)` failed with error 5;
a BACKUP_SEMANTICS read handle opened but real flush failed with error 5;
read/write BACKUP_SEMANTICS plus OPEN_REPARSE_POINT opened and flushed the same
full-128-bit-identity/private-DACL directory. Original State directory sync also
succeeded. Its overall diagnostic receipt remains failed because the old parser
rejected actual singular Nextest output and did not capture source-after facts.
A passing collector test alone does not establish that each tested mode worked.

This supports the selected native access mode, not a claim that all Operator,
Shadow, inherited SSHSIG, sandbox helper or power-loss cases pass. Those require
actual original-case execution on the new exact clean source. Physical power
loss and hostile administrator isolation are not qualified by these fixtures.

## Junction fixture

`native_reparse_directory_is_refused_before_child_effect` keeps its original
case identity and all admission, no-child-effect and cleanup assertions. Its
fixture now creates one absent private scratch directory and uses the native
`FSCTL_SET_REPARSE_POINT` mount-point contract. The bounded buffer contains the
actual canonical target in UTF-16, including its NT substitute name. The same
held handle must return the entire tag/offset/length/target buffer through
`FSCTL_GET_REPARSE_POINT`, retain the original volume/full 128-bit ID and
owner/DACL, and resolve through
the OS to the original target before the admission checks begin. This is a real
junction, rather than a symbolic link or a mock filesystem observation.

The test-local control codes are the Windows SDK `CTL_CODE` definitions for
`FILE_DEVICE_FILE_SYSTEM`, functions 41 and 42, `METHOD_BUFFERED`, and
`FILE_ANY_ACCESS`; the mount-point tag is `IO_REPARSE_TAG_MOUNT_POINT`. Existing
`windows-sys` features already provide `DeviceIoControl`, so the fixture adds no
dependency or production API. See Microsoft's [mount-point buffer contract](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_reparse_data_buffer)
and [setting a reparse point](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_set_reparse_point).

Prior native runs that failed at `cmd /c mklink` syntax remain failures before
the backend assertions. Removing that command parser does not establish a
passing native result: the new exact source still requires the original case
to execute on Windows. A GNU cross check only checks Rust types and lints.

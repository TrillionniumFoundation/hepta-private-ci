# Native Windows OpenSSH controls

`src/windows_openssh_tests.rs` adds four Windows-only controls for the shared
native backend. Its module declaration is supplied by the production backend
change; this independent test commit does not add a substitute backend or edit
the original caller, parser, Cargo dependencies or original 91 test IDs.

Each case creates a fresh private scratch directory and disposable Ed25519 key
with the existing real OpenSSH fixture helpers. `sign_private_fixture` creates
the private signature before filename signing, verifies original full file ID
and DACL, and retains the original LF SSHSIG bytes. The statement includes NUL,
CRLF and a non-UTF-8 byte. Neither statement, signature nor allowed-signers bytes
are normalized. No private key bytes are read or logged.

The small JSON policy is only a canonical private-file custody input with an
externally supplied digest. It is not a deployed Root/operator policy, human
session, model authorization, device signer or authority grant.

The controls require these actual outcomes:

1. Strict Rust and the installed native System32 OpenSSH child both accept the
   exact same original bytes.
2. Changing one body byte makes strict Rust refuse. Calling the native backend
   directly must also reach an actual child exit failure, with the unique typed
   `AcceptanceError::Invalid("native OpenSSH SSHSIG verification failed")`.
3. A wrong namespace must reach that same actual-child rejection, after a valid
   baseline pair has already passed.
4. After capture and a successful baseline, a real kernel DACL update removes
   `FILE_WRITE_DATA` from the scratch policy's existing allow ACEs. The full
   Windows file ID stays equal, while the descriptor differs and remains
   canonical/private. Verification must refuse with the specific retained
   owner-policy-changed error. No existing external file or ACL is repaired.

Early unsupported APIs, missing OpenSSH, pipe errors, wrong image/token/PID or
timeouts cannot satisfy the body/namespace negative cases. These are additional
controls; original failed runs and original test IDs remain intact.

The original test-only commit had no backend. The combined source wires these
controls to the production backend. They are explicitly ignored by default so
the original package-wide 26-case selection remains identical. A separate exact
filter with `--run-ignored ignored-only` must select all four, once each, with zero
retries. The combined clean source must pass repository formatting/lint/build
checks and run these cases on real Windows. Linux/GNU cross compilation and
parser-only results supply no native qualification.

Further actual Windows controls remain necessary for unrelated-client PID
rejection, cancellation/timeout cleanup and EOF/worker retirement. They should
exercise actual pipe connections and the spawned child HANDLE, not mocked PIDs,
metadata-only records or synthetic file descriptors.

## Production contract

`windows_openssh.rs` is the single Windows backend shared by Operator trust and
G5. Both callers first retain the original strict Rust SSHSIG verification;
native verification is an additional independent check. Unix retains its
original inherited-descriptor path. Windows uses its own actual child/pipe
contract and does not claim Unix inherited descriptors.

The owner captures the original externally pinned policy as a canonical
`PrivateFile`, its full identity and owner/DACL, and the effective user/owner
token SIDs. The retained policy must still verify before and after each native
operation. No policy ACL is repaired and no new policy or signing authority is
created. Statement, signature and allowed-signers bytes retain their original
bounds and are written unchanged. The fixture producer uses its precreated
private filename; it never repairs stdout CRLF or a generated signature.

`windows_openssh_image.rs` obtains System32 through `GetSystemDirectoryW`, not
PATH or a caller environment variable. It holds the installed OpenSSH image
read-only without write/delete sharing and verifies full 128-bit file identity
and owner/DACL before and after use. Its OS-image integrity predicate is
separate from private-file custody: only SYSTEM, Builtin Administrators and
TrustedInstaller may own/write/control the system image; foreign grants are
limited to read/execute. Unknown ACL forms fail closed. The actual child HANDLE,
PID, image full identity and TokenUser/TokenOwner must match before any bytes
reach either pipe. This does not authorize a process merely because its pathname
or tool version matches.

`windows_openssh_pipe.rs` creates two unpredictable, first-instance, local-only,
non-inherited, single-client pipes with the original private policy descriptor.
The canonical private owner/DACL predicate checks each real pipe object. It
checks the actual connected client PID against the retained live child before
writing. Original bytes are written exactly, flushed until consumed, then
disconnected to supply EOF. Only the already-closed-client error 233 after an
exact write and successful flush is accepted. A parent-cancelled lane that never
connected is separately typed; it cannot satisfy signature consumption or a
successful verification. A naturally failing child can leave the allowed-signers
lane unused only after it consumed the signature and the body write succeeded.
Timeouts, identity/PID failures and other I/O errors never become the specific
cryptographic-rejection result.

The native operation has a five-second deadline. It does not modify any original
Nextest deadline or retry setting. Stdin and both pipes have scoped workers. On
normal exit, timeout or error the parent retains/reaps the real child and aborts
pipe I/O before joining workers. Overlapped state and buffers remain alive until
actual completion/cancellation. Unwinding repeats owned cleanup; an error is not
published as success. No raw HANDLE, writable process port or adopt-existing-file
API is exported. Real Windows EOF, cancellation, client PID and worker-retirement
qualification remains required for each exact clean source.

## Independent transport controls

Two additional ignored cases use a real installed OpenSSH child whose original
stdin stays open, and bind its actual kernel image, token, HANDLE and PID. The
unrelated-client case connects from the real test process, starts a one-byte
native overlapped read before the server attempts any data, requires the exact
client-PID refusal, and checks that read is still incomplete with zero bytes
before disconnect. It then collects the actual cancellation/EOF completion.
The other case uses the original five-second deadline for a real pending native
connect, requires its precise timeout, then reaps the real owned child through
production cleanup. Neither case uses a supplied PID or fake BoundChild. These
are independent client/connection/cleanup controls; they do not qualify a whole
backend timeout with a client blocked in FlushFileBuffers.

The separate Windows collector preserves exact 4/4/2 scopes for runner lifetime,
dual SSHSIG and transport. It rejects unknown, missing, duplicate, skipped or
non-PASS cases, including LEAK, and duplicate/unknown summary items. It records
the exact clean head/tree, native compiler/runners, System32 tool hash, protected
source and actual before/after observations even on failure. The unchanged
original driver and scope remain separate and must retain the original 91 IDs.

## Actual 0ba5 result and successor limits

The actual Windows [run 40460595505](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40460595505)
used clean `0ba5adf28de1dd60010e2cc42bbf454cc435d195`, tree
`043e60046d19e716ec3b454e63e9c9a383332b13`. Its unchanged original91 had
83 PASS, 7 FAIL and 1 LEAK. The separate legacy-refusal3+3 and private-artifact9
passed. The new runner4 selected zero tests because their exact names omitted
`runner_client`; the collector refused that count drift. The new crypto4 and
transport2 failed at real OpenSSH fixture filename signing before reaching the
native backend. None of those six failures qualifies a native verifier result.

The filename signer reported `Cannot open ...statement.sig: Broken pipe`.
[Win32 OpenSSH's writer](https://github.com/PowerShell/openssh-portable/blob/v9.5.0.0/contrib/win32/win32compat/fileio.c#L304)
uses `FILE_SHARE_WRITE` for `O_WRONLY`. The fixture's held `GENERIC_READ` observer
conflicts with that writer's sharing choice. The successor retains a
metadata-only `READ_CONTROL | FILE_READ_ATTRIBUTES` observer with read/write
sharing and no delete sharing, preserving full identity/DACL checks across the
original filename write. It does not repair an ACL or rewrite signed bytes.
The error mapping is consistent with this mechanism; the successor still needs
actual native execution to validate the repair and reach the backend controls.

The original elevated command body passed but Nextest reported LEAK. Its root
cause remains undetermined; waiting for the retained runner's real exit does
not identify every external holder of Nextest's capture pipes. Test builds now
record only parent/retained-runner PIDs, standard-handle type and inherit flags
at creation/exit cuts. They read no environment, command body, credentials or
pipe content and do not redirect stdio, duplicate handles or change process
cleanup. A separate exact reexecution of that original case requests successful
output for diagnosis. Its result is not added to original91 or new4+4+2, and a
LEAK remains nonpassing. Merely suppressing capture output is not a fix.

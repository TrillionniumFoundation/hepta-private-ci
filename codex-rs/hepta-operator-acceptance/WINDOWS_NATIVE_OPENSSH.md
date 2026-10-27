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

This test-only source is prepared independently before the production backend
is combined. It is not runnable in its base tree because that tree intentionally
has no `windows_openssh` production module. The combined clean source must pass
the repository formatting/lint/build checks and run these cases on real Windows.
Linux/GNU cross compilation and parser-only results supply no native qualification.

Further actual Windows controls remain necessary for unrelated-client PID
rejection, cancellation/timeout cleanup and EOF/worker retirement. They should
exercise actual pipe connections and the spawned child HANDLE, not mocked PIDs,
metadata-only records or synthetic file descriptors.

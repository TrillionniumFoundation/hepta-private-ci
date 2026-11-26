# Preserve the mapped apply-patch failure cause

Base: `752eae654d24345b0999a5b151250a2a60dbcd8e`.

The preserved Windows workspace-root failures report `Failed to write file` for
allowed patch targets, followed by a missing-file read. That outer message does
not identify the underlying filesystem error. The correctly rejected `.git`,
`.agents`, and `.codex` paths remain separate policy controls. No ACL, account,
credential, backend, or path explanation has been established for the failed
allowed writes.

The current local sandboxed filesystem path has these error boundaries:

1. `fs_helper::map_fs_error` converts filesystem errors into JSON-RPC errors.
   `PermissionDenied` and `InvalidInput` both become code `-32600`; the error's
   display text becomes the message.
2. `sandboxed_file_system::map_sandbox_error` maps code `-32600` to a new
   `io::ErrorKind::InvalidInput`. Other helper preparation or launch failures
   can reach the same caller through their existing JSON-RPC mappings.
3. `apply-patch::apply_hunks_with_options` writes the outer `anyhow` display
   context to tool stderr. If it finds an underlying `io::Error`, its existing
   borrowed-error conversion copies the kind and display text into a new error.
   This conversion does not preserve a structured OS error code.
4. `ApplyPatchRuntime::run` previously discarded that mapped typed error when
   extracting the unchanged committed delta.

Only the fourth boundary changes: the existing `Err` arm retains `(error, delta)`
long enough for one warning when the existing tracing subscriber enables it.
It formats the mapped error into a fixed 2048-byte stack buffer. A full buffer
stops formatting with its normal write error; neither a formatting error nor
truncation changes the original result. The log records whether formatting
completed, the stored byte count, a lossy-UTF-8 flag, and the bounded prefix.
At most eight existing error-chain entries are inspected for a typed mapped
`io::Error`, whose kind and optional OS code are logged as mapped fields.

The prefix before tracing's escaping contains at most 2048 original bytes.
Splitting a multibyte character at the buffer edge can add replacement-character
bytes in the lossy display; the flag makes this explicit. Subscriber escaping
and fixed event metadata can further increase the rendered line size. No entire
error display string is allocated before truncation. Formatting and chain
inspection perform no added filesystem I/O, await, request, retry, or sleep.
Their bounded operation count is not a guaranteed wall-clock deadline.

`mapped_raw_os_error=None` describes this already transformed error. It does not
prove that the original OS had no code, identify an OS failure, or reveal which
Windows backend actually executed. A textual OS code in the retained message
must be distinguished from a typed OS code and from a traced kernel operation.

The original tool stdout/stderr, success/failure and exit-code calculation,
delta accumulation, output-based sandbox classification, escalation behavior,
all permissions, and every test assertion remain unchanged. The warning is a
diagnostic, not an allowed-write fix or a sandbox qualification. Only static
source checks have run for this candidate; no new native test or CI run has
been requested.

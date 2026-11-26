# Actual legacy child token observation

This candidate adds observations to the existing legacy writable-root deletion
test. It does not change token construction, ACLs, process creation flags,
command arguments, the five filesystem actions, deadlines, or assertions.
The original production-token test remains separate and unchanged.

## Evidence motivating the observation

At the preceding source cut, strict Clippy completed successfully while both
selected native tests failed. The legacy case retained all three files that it
expected to delete. Its child emitted five `Access is denied.` messages.
Existing readbacks showed capability ACEs on the three writable roots and their
files, while ordinary Users ACEs did not grant file DELETE or parent
DELETE_CHILD. Those snapshots described the parent and objects; they did not
establish the launched child's enabled or deny-only groups. No ACL or token
change is justified by those snapshots alone.

## Fixed boundary and lifetime

The existing test uses the non-TTY legacy path. The public
`unified_exec/mod.rs::spawn_windows_sandbox_session_legacy` wrapper awaits the
same-named implementation in `unified_exec/backends/legacy.rs`. That backend
body has no await and returns Ready in the same poll. Its synchronous creation
chain is `spawn_legacy_process` → `spawn_process_with_pipes` →
`create_process_as_user` → `CreateProcessAsUserW`. The input writer's
`spawn_blocking` occurs after that process creation call returns.

The test wraps only its existing spawn future. A private thread-local observer
is installed immediately before each call to `Future::poll` and restored before
either Pending or Ready returns. Drop also restores the previous observer on
unwind. The registration never crosses an await. Its `Rc` state is not Send.
A nested registration marks both observations as overlapping. A missing hook,
multiple hooks, or overlap is reported as unknown. A future change that moves
creation to another thread must therefore produce an unknown observation;
there is no fallback to a parent token or a process found by PID.

Immediately after successful `CreateProcessAsUserW`, a `cfg(test)` hook reads:

1. The actual input `h_token`, using its existing query access.
2. The actual returned `pi.hProcess`, using one `OpenProcessToken` request for
   TOKEN_QUERY only. An owned query handle closes on every return path.

The original token, process and thread handles retain their original owners.
There is no duplication, elevation, privilege adjustment, impersonation,
process suspension, new launch, delay, retry, or requested access beyond
TOKEN_QUERY. The child continues running while these bounded reads occur.
The existing five-second wait remains in its original location; the diagnostic
adds synchronous query overhead before the existing waiter starts and is not
a claim of zero timing perturbation. No new waiting budget is introduced.

## Fixed facts and bounds

Both snapshots require a primary token. They read TokenType, TokenUser,
TokenOwner, TokenGroups, TokenRestrictedSids, TokenPrivileges,
TokenIntegrityLevel and TokenMandatoryPolicy. Each query uses one size probe
and one data call, a maximum 64 KiB aligned buffer, checked array and SID
bounds, and at most 64 array entries. There is no TokenStatistics or structure
padding comparison.

Raw SIDs remain in memory solely for role classification and exact comparison.
Output contains generic role names, raw group attributes, counts, privilege
LUIDs and attributes, integrity RID and mandatory policy. No SID text or bytes,
PID, credentials, environment, paths, or command contents are emitted.
Unknown identities use the role `other`; a restricting SID is not claimed to
be a particular fixture root merely from that label or from its count.

One `HEPTA_LEGACY_SPAWN_TOKEN` record identifies the launch-input and actual
child-primary snapshots independently. It records the poll and hook counts,
overlap, and field comparisons. The complete line is capped at 16 KiB including
prefix and newline. Each error string is capped at 256 UTF-8 bytes. Query,
shape, count or serialization failure produces unknown, without replacing the
original spawn result or filesystem assertions. Output failure can leave a
missing record and must not be treated as successful observation.

Raw privilege-attribute equality includes usage-record bits. A difference in
those bits alone is not proof of changed authorization. Equality of queried
fields is not kernel I/O tracing or proof of confinement. Neither an observed
child token nor a later passing fixture can close the independent
WRITE_RESTRICTED parent-delete escape.

## Primary contracts and execution scope

- [CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)
  documents the launch token and returned process-handle access.
- [OpenProcessToken](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocesstoken)
  documents the original process handle, token access check, and close duty.
- [GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation)
  documents TOKEN_QUERY and returned-buffer bounds.
- [TOKEN_GROUPS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_groups)
  documents enabled and deny-only group attributes.
- Bindings remain the existing Microsoft windows-sys 0.52.0 dependency and
  features. No manifest, lock, workflow, selector, toolchain or command changes
  are part of this source candidate.

This is an unexecuted diagnostic candidate. Formatting and source verification
do not establish Rust compilation or Windows behavior. Any later native
qualification must retain the original two tests, first nonzero exit, zero
retries, twenty-minute job budget and original failure evidence, and separately
check that the new observation is complete without promoting it to a fix.

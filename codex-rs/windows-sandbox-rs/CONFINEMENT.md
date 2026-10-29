# Windows filesystem confinement boundary

## Observed failure

The native Windows CI job `122780464727` recorded both forms of the deletion
failure: a capability-token impersonation test could delete an outside file and
directory despite denied writes, and a real `cmd.exe` launched by the direct
legacy backend deleted the outside fixture and a protected `.git` directory.
Those outcomes are isolation failures. An ACL-construction assertion or a
Linux build cannot qualify Windows filesystem confinement.

Microsoft documents that deletion may be authorized by either `DELETE` on the
target or `FILE_DELETE_CHILD` on its parent. It also documents that
`WRITE_RESTRICTED` applies restricting SIDs only to write-access checks, while a
fully restricted token requires both the ordinary and restricting SID checks.
Consequently, preserving ambient read access with the legacy token does not
establish a deletion boundary under arbitrary parent ACLs. Removing
`FILE_DELETE_CHILD` from a capability allow ACE does not remove rights supplied
by other identities in a parent ACL.

- [DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
- [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [File access rights constants](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants)
- [Token information classes](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)

## Launch API contract

- `spawn_windows_sandbox_session_legacy`, `run_windows_sandbox_capture`, and
  `run_windows_sandbox_capture_with_filesystem_overrides` reject managed
  restricted-filesystem profiles, including read-only profiles. The shared
  rejection precedes environment rewriting, creation of `CODEX_HOME` or logs,
  capability SID provisioning, ACL mutation, token creation, and child spawn.
- `spawn_windows_sandbox_session_for_level` requires the elevated broker for
  every managed filesystem session, including read-only. Existing managed
  networking checks still reject an incompatible requested level. Broker
  errors propagate; there is no direct-token fallback.
- Core capture honors an explicit unelevated configuration by returning the
  unsupported error before setup. Explicit elevated capture uses only the
  broker. Callers that formerly invoked the legacy capture API must choose the
  elevated API and provision its helper binaries and identity.
- Explicit disabled or externally managed policies retain their existing
  routing outside this sandbox. The restricted-filesystem APIs do not acquire
  a new unrestricted bypass.

## Low-level token and ACL contract

`create_workspace_write_token_with_caps_from` now creates a fully restricted,
capability-only token from a fresh, unfiltered base. A native
`TokenHasRestrictions` query rejects existing filtered tokens before creation;
omitting the flag does not establish that an inherited write-only restriction
mode has been cleared. A caller must grant every required read and execute
right through a supplied capability, as well as granting writable roots.
Broad ambient identities and another root's stale capability are insufficient.
This is an incompatible tightening of that low-level API, not a replacement
process launcher: executables, DLLs, devices, registry objects, IPC, and runtime
dependencies would all need an explicit access model before such a launcher
could be supported. The identity-inclusive elevated token constructors retain
their existing behavior; they require their own native acceptance evidence.
The constructors continue enabling `SeChangeNotifyPrivilege` for directory
traversal, so this is not a claim that all traversal is ACL-restricted.

Deny-write ACEs contain the specific data, append, attribute, extended
attribute, `DELETE`, and `FILE_DELETE_CHILD` rights. They omit generic-write
bits and the shared `READ_CONTROL`/`SYNCHRONIZE` rights so a write carveout does
not also deny ordinary reads. Microsoft documents the shared generic-read and
generic-write synchronization mapping, and the possible split of generic
inheritable ACEs into effective and inherit-only entries. Native repair tests
continue to require complete rights, recursive scope, precedence, preserved
reads, denied writes, and idempotence after ACL storage.

- [File security and access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
- [ACE inheritance rules](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules)

## Qualification gates

The legacy rejection tests inspect actual DACL ACE bytes before and after both
public capture forms and PTY/non-PTY sessions, check that an absent code home
remains absent, preserve outside fixture contents, and check that a command's
child marker was never produced. A separate fixture denies ACL modification
and verifies rejection precedes even that attempted setup operation.

The previous positive process tests now execute the broker. They retain actual
output, exit code, cancellation, terminal I/O, and descendant-lifecycle checks.
Their lifecycle markers live in declared writable workspaces, not the broker's
credential directory. The deletion acceptance test requires successful
deletion in the workspace, `TEMP`, and `TMP`, while preserving outside content
and `.git`. Unsupported rejection is not counted as passing that test.

A second broker test gives the owned outside sibling explicit inheritable
Everyone `DELETE` and `FILE_DELETE_CHILD` grants and a low mandatory label. It
reads back the native labels on the sibling, file, and directory. The child
reports its own integrity SID with `whoami`, and a level below low cannot
qualify this case. This makes a successful refusal evidence for the filesystem
policy rather than a low-to-medium mandatory-integrity barrier. The broker's
identity-inclusive token retains Everyone in its restricting list, so this
separate case remains a required gate even if ordinary outside ACLs pass.

Native Windows results on the candidate commit are required to close the broker
confinement and ACL-repair blockers. If the broker also permits outside
deletion, that blocker stays open; this legacy rejection does not establish
broker safety. The existing unsupported ConPTY `cmd.exe` tests remain explicitly
ignored and are not counted as qualification evidence.

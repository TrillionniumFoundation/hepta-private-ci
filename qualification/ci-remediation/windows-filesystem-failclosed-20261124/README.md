# Windows managed filesystem execution: fail-closed draft

This change refuses an unqualified execution capability. It does **not** restore
the legacy Windows sandbox or qualify the dedicated-account backend. It must
not be reported as a passing Windows execution matrix.

## Evidence and reason for refusal

The original native Windows job ran against source
`07c8994f2402a58f6b59eb648c801fc40c6e2b96`:
[run 45104012523, job 137461937853](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45104012523/job/137461937853).
In `workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces`,
the outside write and create operations returned `PermissionDenied`, while
outside file and directory removal succeeded. The real legacy command test
also removed the outside file and protected `.git` directory. These are observed
execution failures, not deductions from an ACL display.

The shared token constructor uses `WRITE_RESTRICTED`. Windows documents this
flag as restricting the write-access check. The documented `FILE_GENERIC_WRITE`
mapping does not include `DELETE` or `FILE_DELETE_CHILD`, and deletion/rename can
be authorized by either the target's delete right or the parent's delete-child
right. Restricting only ordinary writes is insufficient for the requested
filesystem policy.

Read-only tokens use the same constructor. The elevated runner also uses that
constructor, adding the dedicated account, logon, and Everyone identities to
its restricting set. Its IPC protocol brokers spawning and I/O; it has no
filesystem-operation authorization protocol. Its different account can reduce
default access, but neither the source nor the existing native evidence
qualifies isolation under broad outside ACLs. This draft therefore refuses
both execution backends, including read-only profiles.

## Guard coverage

The common error is `std::io::ErrorKind::Unsupported`, converted into `anyhow`
without becoming a sandbox-policy denial. Existing Core capture code maps a
launch error to `CodexErr::Io`; the orchestrator retries only `SandboxErr::Denied`.
The executor-native spawn and wrapper paths propagate the error. The private
selector retains its pure backend-planning and configuration-checking behavior;
the public dispatcher refuses execution before calling that selector. Selecting
an elevated backend in a plan does not qualify or execute that backend.
This no-retry conclusion is based on source review. The new tests stop at the
Windows library API boundary; no real Core orchestrator no-retry regression has
been executed for this draft.

| Entry or path | Check before side effects |
| --- | --- |
| `spawn_windows_sandbox_session_for_level` | First statement, before route planning or backend dispatch |
| Direct legacy session | First statement of the legacy backend, before spawn preparation |
| Direct elevated session | First statement of the elevated backend, before account/setup preparation |
| Legacy capture, with or without overrides | First statement of the shared capture implementation |
| Elevated capture | First statement of its implementation |
| Legacy preflight | Before capability files or ACL installation for managed profiles |
| Setup refresh and extra read grants | Public managed-profile wrappers, before read-root collection; shared implementation also retains its guard |
| Elevated setup | Shared setup implementation, before directories, ACLs, or an elevation request |
| Account acquisition or refresh | Before marker loading, reconciliation, or account setup |
| World-writable ACL preparation | Before scanning or installing capability denies; the TUI uses a separate read-only warning scan |
| Direct command-runner IPC request | Before hiding the account profile, obtaining tokens, or creating the child |
| Five public token factories and the internal read-only convenience factory | Shared primitive, before `CreateRestrictedToken`, privilege changes, or default-DACL updates |

Independent low-level ACL utilities remain available for explicit ACL operations
and their tests. Explicit administrator provisioning is not an execution path
and remains separate: `run_elevated_provisioning_setup` and the setup helper's
`win::main`/`real_main` can still modify directories, accounts, and ACLs when
explicitly invoked. This change does not refuse every setup operation. Those
administrative paths cannot bypass the launch or token checks. Configuration
parsing and the no-op preflight for non-managed profiles keep their existing
behavior. No setting is rewritten to disabled or elevated execution.

## New native regressions and current validation

The four refusal tests in `filesystem_isolation_tests.rs` exercise 34 public
execution/preparation calls plus six token-factory paths, covering read-only
and workspace-write profiles, both explicitly selected backends, direct backend
APIs, and TTY/non-TTY sessions. The native fixture supplies a command that would
write a marker and remove only fixture-owned objects if it were launched.

Each public call must return the specific `Unsupported` I/O error. After each
call, the original file contents, protected directory, directory listings, and
native DACL security-descriptor bytes must match the initial fixture. The marker
and previously absent Codex home must remain absent. The source places the guard
before the first mutation; the native state checks are its regression coverage.
Unexpectedly returned token handles are owned and closed before the test fails.

### Actual original-head native result and preparation fix

The original head `79b1ef2a39ea587247f593c4f44d6d7e9b9dd5f2` did execute
on Windows in [run 45429499868, job 138609508679](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45429499868/job/138609508679).
The GitHub merge checkout has the same tree as that head. Three of the four
new cases passed; `automatic_preparation_refuses_before_acl_or_account_setup`
failed because the previously absent Codex home already existed. Therefore the
original run did **not** complete the required 40 checked entry attempts.
`native-79b1-receipt.json` and the normalized first unit-execution excerpt preserve
the exact source binding, counts, failure, and original raw byte hashes. The
excerpt only normalizes line endings and trailing whitespace; its own hash is
recorded separately. Reprinted failure
tails are not additional executions.

The extra-read-roots wrapper collected helper read roots before reaching its
shared refusal guard. That collection called `create_dir_all` for the helper
binary directory. The follow-up puts the same guard in both public refresh
wrappers immediately after successful managed-profile resolution, before any
root preparation. The existing non-managed no-op and shared inner guard remain.
No cleanup after an unauthorized mutation is substituted for prevention.

The four original cases and all their error, byte, namespace, DACL, and no-child
assertions remain. Each case now also checks its actual successful refusal-call
count (8, 16, 10, and 6 respectively) and emits that count only after its final
state checks. All four must pass to establish the 40-attempt qualification.

Executed for this follow-up: repository `just fmt` and `git diff --check`.
The follow-up's native execution is still pending. A passing refusal subset will
not restore managed execution or make the complete Windows matrix pass.

Later planning and read-only UI follow-ups, including their distinct source and
native qualification boundaries, are recorded in [READ_ONLY_UI.md](READ_ONLY_UI.md).

## Preserved requirements and expected CI impact

The original token, desktop, ACL, backend-selection, and process-lifecycle tests
are unchanged. In particular, the original outside-delete assertions and the
ACL repair expectation `(false, true, false)` are neither deleted nor weakened.
No additional skip or ignore is introduced.

The following tests or scenarios cannot currently reach their old positive
execution requirements because the guard refuses their token or launch:

- All three token tests, including the partial-delete ACL repair test. The
  independent ACL repair change remains separate and is not requalified here.
- The two desktop tests that require a restricted token.
- Backend-selection tests that expect a usable token backend, automatic
  elevation, or the previous diagnostic precedence.
- Direct legacy/elevated command output, TTY, cancellation, descendant lifecycle,
  and ACL-setup-failure scenarios that require a managed process launch.
- Windows Core/app-server scenarios that depend on those managed shell launches.

These are explicit remaining functionality blockers. They must not be hidden by
changing the old tests to accept a weaker sandbox or by presenting a filtered
run of the new refusal tests as complete CI. Generic process-driver and direct
ACL tests which do not create the blocked token remain independently testable.

## Minimum remaining capability work

Re-enabling execution requires an independently qualified boundary for read,
write, deletion, and rename. A full restricted token would also need precise
read/execute grants and compatible startup without broad identity SIDs bypassing
the restriction. A broker must rely on an OS boundary that denies direct target
access; interception or command filtering alone does not supply that boundary.

At minimum, native qualification must include ordinary and already-low-integrity
outside objects with broad ACLs, target-delete and parent-delete-child variants,
protected descendants of writable parents, and allowed-root positive controls.
It must define unsupported filesystem/security-descriptor cases, preserve the
original permission policy, and verify the complete invocation and retry paths.
Low integrity alone is not a path allowlist. No alternative backend is invented
or claimed to be implemented in this refusal change.

## Primary references

- [CreateRestrictedToken flags and the two access checks](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [File access rights and generic mappings](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
- [DeleteFileW: target DELETE or parent DELETE_CHILD](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
- [Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
- [NULL and empty DACLs](https://learn.microsoft.com/en-us/windows/win32/secauthz/null-dacls-and-empty-dacls)
- [Chromium Windows sandbox architecture and limits](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/design/sandbox.md)

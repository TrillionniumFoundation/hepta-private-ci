# b9 DELETE recheck: both original boundaries actually failed

Status: **OPEN**. This review changes documentation and source/evidence pins
only. It neither modifies the original deletion assertions nor adds a weaker
sandbox, a skip, account/host-root ACL mutation, or a fallback.

## Exact execution

Source `b9afe1f469ad12c5cd520af0ecef4c8e22f295ed`, tree
`c00dc49a3cf072e594737c437f18e6c70fd36b0d`. The normal Windows main run is
`45585341998`, job `139107875542`. Its checkout merge is
`276d0c1425f266bc2ad8b6024a0468ff58e2384d`, with ordered parents
`[07c8994f2402a58f6b59eb648c801fc40c6e2b96, b9afe1f469ad12c5cd520af0ecef4c8e22f295ed]`.
The complete merge tree equals the source tree. `b9-receipt.json` binds the raw
job and unmodified excerpt, and `b9-source-pins.json` pins every reviewed file.

| Original test | Actually reached controls | Actual violation |
| --- | --- | --- |
| `token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces` | Allowed workspace/temp creates and deletes completed; outside read succeeded; outside overwrite and create returned `PermissionDenied`. | Outside file and directory removal returned success. The result was `[PermissionDenied, PermissionDenied, None, None]`, not four denials. |
| `unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots` | A real `cmd.exe /d /c` child exited 0; workspace, TEMP and TMP files were removed as required. | Outside file was absent and the protected `.git` directory was absent. Required outside contents and directory-presence assertions failed. |

The second case is a new actual child-process execution result relative to the
older 804 evidence, where its shared lock was already poisoned. The b9 wrapper
reported 55 passed, 2 failed, 2 existing ignored and 92 filtered. Later
postconditions after each failing assertion were not reached. The source/raw
does not contain a per-open kernel trace that distinguishes target DELETE from
parent DELETE_CHILD for each successful removal; both are possible authority
paths and neither may be omitted from the contract.

## Policy and call graph

The token case deliberately installs broad logon/World inheritance only inside
its owned temporary fixture. The two allowed roots receive distinct capability
SIDs; the outside root has a different stale capability. It is testing the
documented outside-read/inside-write contract under ordinary broad grants, not
relying on missing helper binaries, unknown root aliases or an absent capability.

The child case uses `PermissionProfile::workspace_write()`, resolves its one
workspace root, and supplies absolute, distinct TEMP/TMP roots. Its intended
policy permits these writes, permits ordinary outside reads, and preserves the
outside file and read-only `.git` carveout. These are existing accepted managed
permissions, not an unsupported-policy error accidentally ignored by the test.

| b9 source under `codex-rs/` | Enforcement path |
| --- | --- |
| `protocol/src/models.rs::PermissionProfile::workspace_write` | Builds managed workspace-write permissions with restricted networking; temporary-root entries are enabled. |
| `windows-sandbox-rs/src/resolved_permissions.rs::writable_roots_for_cwd` | Materializes root and read-only subpath rules; maps TEMP/TMP to absolute Windows roots. |
| `windows-sandbox-rs/src/allow.rs::compute_allow_paths_for_permissions` | Produces allowed roots and existing read-only carveouts. |
| `windows-sandbox-rs/src/spawn_prep.rs::prepare_legacy_session_security` | Creates root capability SIDs and calls the workspace restricted-token factory. |
| `windows-sandbox-rs/src/token.rs::create_token_with_caps_from` | Workspace excludes broad restricting identities, but still sets `WRITE_RESTRICTED`; readonly/elevated variants include broader identities. |
| `windows-sandbox-rs/src/acl.rs::ensure_allow_write_aces` | Already removes capability `FILE_DELETE_CHILD` grants; retained mask includes descendant DELETE. |
| `windows-sandbox-rs/src/spawn_prep.rs::apply_legacy_session_acl_rules` | Installs allowed-root and carveout ACEs; it does not create a private kernel namespace or intercept all file operations. |
| `windows-sandbox-rs/src/elevated/ipc_framed.rs::Message` | Only spawn, readiness, stdio, resize, exit/error and termination; no file-open/delete/rename authorization protocol. |

Thus the earlier capability-identity and capability-parent-mask improvements
are already present in the failing source. The independent same-handle deny-ACE
repair does not turn a write-only restricting-token check into a complete
filesystem authorization mechanism.

## Why this is not a fixture-only correction

[CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
limits the restricting-SID check to write access when `WRITE_RESTRICTED` is set.
The [file generic-write mapping](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
does not include DELETE or FILE_DELETE_CHILD. The
[DeleteFile contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
allows target or parent authority. The actual four-operation result agrees with
that mismatch; no new native flag experiment was performed in this recheck.

Removing broad identity ACEs from the outside fixture, or installing additional
denies there, would remove the adversarial condition being tested. Broadening
the writable policy would change its requested meaning. Accepting `Unsupported`
instead would test refusal rather than its original positive execution control.
None is a legitimate correction of these fixtures.

Removing `WRITE_RESTRICTED` and keeping only capability SIDs also makes ordinary
outside reads depend on capability ACEs absent from this fixture and arbitrary
existing host files. Adding World/user/logon to recover those reads also admits
matching DELETE grants. Restricting SID entries have no per-SID read-only mask.
This is a source/API feasibility argument, not a claim of another native run.

## Missing primitive and bounded implementation decision

For an arbitrary child process the boundary must reject every unauthorized
direct filesystem mutation, including target/parent delete, disposition,
rename, links and inherited-handle paths, while admitting the original read and
allowed-write controls. It must remain valid over changing names and objects.

The current token/ACL path does not supply that primitive. A complete broker
needs a separately enforced OS restriction on direct target access; adding file
messages or user-mode API interception to the existing process runner is not
sufficient. A kernel filter requires deployed/signed driver and process/volume
policy plumbing. A separate-kernel backend requires provisioned isolation and
verified host mappings, plus command/stdio/lifecycle integration. None of these
dependencies is present or qualified in this source. No host changes are made
by this review to manufacture such a dependency.

[NULL DACLs](https://learn.microsoft.com/en-us/windows/win32/secauthz/null-dacls-and-empty-dacls)
and [already-Low integrity objects](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
must remain explicit domain concerns. A scan of current ACLs or lowering the
child's integrity does not prove a path allowlist for all future objects. These
are documented design limits, not newly executed b9 counterexamples. An
AppContainer/LPAC backend would require its own resource provisioning and native
compatibility proof; it is not implemented by removing one token flag.

Under the current no-account/host-root-ACL-change constraints, no bounded token
or fixture edit has been established that preserves the complete original
contract. The safe available action is to retain the independent #7070 refusal
candidate, preserve these two original failing tests, and keep functional
Windows managed shell execution OPEN until a real enforcement backend exists.
The #7070 four refusal cases/40 entry attempts and its six pure-planning cases
must never be reported as recovery of this functional capability.

The separately qualified `utils/path-utils/src/windows_private*.rs` APIs can
restrict trusted Rust checkpoint I/O to retained, validated object handles and
bounded names. They are useful for a native WSP parameter transaction, but do
not intercept arbitrary syscalls issued by an AI-generated shell command.

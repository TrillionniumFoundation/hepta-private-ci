# Windows DELETE confinement remains OPEN

This is a read-only source and evidence review, not a sandbox repair or a new
native execution result. The audited source head is
`db517a89a5698fc15a6eb4c0fec76cc06cedc4db`; the actual failure is from
`804ac018433ff08dfd195e93eed936394baf5053`. All six audited files were fetched
from the exact public GitHub head and matched the review worktree byte for byte.
Their blob IDs and SHA256 hashes are in `source-pins.json`.

No production code, account, existing ACL, sandbox policy, assertion, timeout,
or approval rule was changed by this review. In particular, passing the native
private-storage/operator tests does not qualify arbitrary child-process
filesystem isolation.

## Actual failure, including the execution boundary

The original Windows job is
[138713957842](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/jobs/138713957842).
Its original log is 1,651,377 bytes, SHA256
`1cfd2bd1344ec601b8095aaefa9ae70806df4193b772670047efbe3604d0ea5c`.
`receipt.json` binds the unmodified contiguous excerpts in `original-excerpts.zip`
to original line ranges. The archive preserves original CRLF bytes without
formatting changes.

`workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces`
failed with this four-element result:

| Operation outside the allowed roots | Actual result | Required result |
|---|---|---|
| Overwrite existing file | PermissionDenied | PermissionDenied |
| Create new file | PermissionDenied | PermissionDenied |
| Remove existing file | Success (`None` after `.err()`) | PermissionDenied |
| Remove existing directory | Success (`None` after `.err()`) | PermissionDenied |

The test had already read the outside file successfully and exercised allowed
workspace/temp creates and deletes before reaching this assertion. Later
postcondition assertions did not execute after the panic. The separate legacy
child-process delete test at this head failed on an already-poisoned shared test
lock: this review does not count that as a second executed delete exploit.

## Exact implementation points

| Source under `codex-rs/windows-sandbox-rs/src/` | Relevant behavior |
|---|---|
| `token.rs::create_token_with_caps_from` | Always sets `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`; workspace legacy excludes broad restricting identities, while readonly/elevated paths retain them. |
| `token.rs::create_token_with_caps_user_and_additional_restrictions_from` | Adds the dedicated token user; the common helper also includes logon/World when identity inclusion is selected. |
| `token.rs::create_token_with_caps_from` final configuration | Enables `SeChangeNotifyPrivilege`; there is no new filesystem namespace or path-aware kernel policy here. |
| `token_tests.rs::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces` | Preserves the outside-read positive requirement and all four outside mutation negatives under broad inherited identity grants. |
| `acl.rs::WRITE_ALLOW_MASK` / `ensure_allow_write_aces` | Omits `FILE_DELETE_CHILD` from capability grants and grants descendant `DELETE`; this does not remove independently inherited identity rights on outside parents. |
| `unified_exec/mod.rs::select_windows_sandbox_backend` | Routes write/path-restricted requests to the elevated runner and describes it as authoritative filesystem mediation. That description is not established by the implementation below. |
| `elevated/ipc_framed.rs::Message` | Protocol contains spawn, readiness, stdio/output, resize, exit, error and terminate; it has no per-file authorization/open/rename/delete mediation. |
| `bin/command_runner/win.rs::spawn_ipc_process` | Creates the same restricted-token family, then launches the child. Being a privileged process launcher does not itself mediate subsequent filesystem syscalls. |

## Why bounded token/ACL edits do not close this contract

The [DeleteFile contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
permits deletion through either the file's DELETE right or its parent's
DELETE_CHILD right. The observed negative test exercises the latter alternative.
Fixing idempotent deny-ACE installation does not remove that independent path.

[CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
documents that WRITE_RESTRICTED applies restricting SIDs only to write checks;
without it, both the normal and restricting SID checks must authorize access.
Restricting SID attributes must be zero and provide no per-SID read-only mask.
Removing this flag while retaining capability-only SIDs also rejects the test's
ordinary outside read, whose ACL lacks those capabilities. Reintroducing
World/user/logon for reads can also authorize DELETE through a broad matching
ACE. Neither tradeoff preserves all of the original assertions.

A [NULL DACL](https://learn.microsoft.com/en-us/windows/win32/secauthz/null-dacls-and-empty-dacls)
does not provide the normal discretionary barrier. Lowering ordinary token
[integrity](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
only adds a relative integrity constraint; an already-Low outside object is
not thereby a forbidden workspace path. These are documented design limits,
not newly executed native counterexamples in this review. Scanning present
ACLs cannot prove the property for future objects or close namespace races.

AppContainer/LPAC is a different, meaningful OS primitive, but is not a
drop-in flag fix for the existing contract. Its official
[launch specification](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
requires package/capability authorization, a profile, and process attributes.
Unprovisioned ordinary outside reads remain a compatibility gap; no such backend
is currently implemented here. The AppContainer-specific medium-integrity
capability rule must not be confused with an ordinary Low-integrity token.

## Three implementable architecture directions and their missing prerequisites

| Direction | Required enforcement | Missing qualification or implementation |
|---|---|---|
| Actual file broker with an OS-denied target | Kernel restrictions must first deny direct unauthorized file operations; the broker uses retained, validated directory/file handles and minimum access for permitted operations. | Existing IPC only launches processes. Arbitrary CLI compatibility, loader resources, direct-syscall refusal, inherited handle containment, NULL-DACL/Low-object domain limits, namespace races and broker request authorization need implementation and native proof. API interception alone is not the boundary. |
| Filesystem minifilter | A deployed OS filter enforces the process policy on opens, writes, delete/disposition, rename, hard links and section/mapping paths, with object identity and volume coverage. | No signed/installed filter or policy service exists in this repository; OS support, driver deployment, process attribution, cancellation, race handling and the complete operation matrix remain prerequisites. This review installs nothing. |
| Isolated-kernel execution backend | Run commands in a VM/container with a separate kernel; expose only the declared read-only inputs and writable workspace surfaces. | Provisioning, attested effective mappings, lifecycle/stdio integration and malicious path/link/handle tests are absent. A configuration file or an available VM product is not proof that this runtime uses it. No host account or root ACL is modified. |

The Chromium design explicitly distinguishes the broker's policy service from
compatibility hooks, and records security-descriptor assumptions. The reviewed
document is blob `665d7640624e23901cafad9726022cc2df6a2dc7` at
[docs/design/sandbox.md](https://chromium.googlesource.com/chromium/src.git/+show/main/docs/design/sandbox.md),
especially the target/broker responsibilities and sandbox-restriction caveats.
Its design cannot be transferred by merely renaming the existing launcher.

Microsoft's [minifilter guidance](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/filtering-i-o-operations-in-a-minifilter-driver)
and [Windows Sandbox overview](https://learn.microsoft.com/en-us/windows/security/threat-protection/windows-sandbox/windows-sandbox-overview)
describe possible OS mechanisms; neither is evidence of their implementation or
availability in Hepta's current executor.

## Independent WSP scope

A trusted Rust parameter API can validate a bounded edit plan and restrict its
own I/O to retained checkpoint handles, exact tensor bounds, preimage hashes,
transactional candidate publication, verification and rollback. That useful
contract does not require granting an AI-provided arbitrary command host-wide
filesystem access. It remains separate from the OPEN legacy shell confinement
contract, and its evidence must not be used to claim the latter is closed.

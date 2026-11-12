# Windows elevated deletion containment

## Result and compatibility boundary

This candidate refuses elevated sandbox execution before client preparation,
ACL/capability persistence, token construction, or native child creation.
It returns ElevatedWindowsSandboxIsolationUnavailable; it does not manufacture
a successful effect or retry through unrestricted execution.

**This is containment, not restored Windows functionality or completed isolation
qualification.** Both readonly and workspace-write elevated token factories use
the same affected implementation, so both now refuse. The existing legacy
refusal is unchanged. No qualified replacement for the existing ambient-read
contract was found in the inspected source.

The original deletion matrix, its outside reads and inside positive controls,
every other existing Rust test, the original 19 Windows regression groups, their
167 cases, deadlines, retry policy and failure semantics remain unchanged. The
five new library admission cases run as an additional first group; an additional
native command-runner test covers the internal child-entry boundary. A refusal
does not count as successful execution of any original operation. The original
elevated deletion test is expected to continue failing until functionality is
implemented and requalified.

## Exact retained original observation

| Identity | Value |
| --- | --- |
| Evidence commit | 21df04700aa885aef72b70962f270b966a112de6 |
| Workflow / attempt | 43062473474 / 1 |
| Job | 130668671332, Windows/MSVC Bazel shard 2/4 |
| Workflow head | d0f6507e08f7f5c5855f5164d07c049a34d1a6d9 |
| Actual checkout | a49776ffdea3547ed407a710bb19e93377b29535 |
| Merge base-side parent | 96038ccf0660154fac143ba6cbe4be81e00813e8 |
| OS | Windows Server 2025, 10.0.26100 Datacenter |
| Runner image | windows-2025-vs2026, 20261103.298.1 |
| Candidate parent | ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80 |
| Candidate parent tree | 27651abb15e269c427c75f28f92a3bd1cd9d191f |

The [original header](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/21df04700aa885aef72b70962f270b966a112de6/qualification/memory-cell-mem8-ci-followup/v17/blocking-d0f-recovered/raw/job-130668671332.log.utf8.part-001)
pins the checkout and runner. The [original failure log](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/21df04700aa885aef72b70962f270b966a112de6/qualification/memory-cell-mem8-ci-followup/v17/blocking-d0f-recovered/raw/job-130668671332.log.utf8.part-002),
Git blob 8d1fd93e15f9cce3a7fcf371c8c164d5e6246154, records
legacy_refuses_before_elevated_four_cell_delete_boundary failing. Its physical
outside-root readback is:

| Permission cell | File pending / links | Directory pending / links |
| --- | --- | --- |
| Neither | 0 / 1 | 0 / 1 |
| TargetOnly | 1 / 0 | 1 / 0 |
| ParentOnly | 1 / 0 | 1 / 0 |
| Both | 1 / 0 | 1 / 0 |

The complete matrix appears twice in the retained job output with identical
paths, file identities, ACLs and observations after removing the log timestamp.
These are duplicate printed evidence, not two independent executions.
The failing libtest partition reports 84 passed, 1 failed, 1 ignored and 103
filtered; other partitions are separate scopes.

The original checkout and candidate parent have identical blobs for token.rs
(dbf1460422b93823d1e2fe7ad763be448a97bcbc), the native runner's win.rs
(146d5290e35bfb3b926a1e7a53c7345c5598b0b9), and the unchanged delete matrix
(27ce698e8b13eede4325a769164a2e6bdcba3271). This establishes applicability to
these exact sources. It does not identify every deployed installation or
attribute the defect to the MEM patch.

## Mechanism and callers

Microsoft documents that [restricted tokens](https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens)
require both the normal-SID access check and a restricting-SID check to grant
access. A restricting SID is an alternative matching ACE within that second
check; adding a capability SID does not require that specific SID to match.
The inspected elevated constructor includes the dedicated user, logon and
Everyone identities alongside capability SIDs.

[CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
documents that WRITE_RESTRICTED applies restricting SIDs only for write access.
[DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
documents the alternative target-DELETE and parent-delete-child authorization
routes. Those contracts, the actual broad identity list and the original native
readback support containment. Merely selecting a dedicated account or removing
one flag does not establish the requested complete read/write/delete contract.

The guarded actual call chain is:

- Public elevated capture alias to elevated_impl::run_windows_sandbox_capture_for_permission_profile.
- Public session selector and direct elevated session to unified_exec/backends/elevated.
- Internal elevated preparation to spawn_prep::prepare_elevated_spawn_context_for_permissions.
- Native runner spawn_ipc_process, before profile hiding, token acquisition,
  null-device ACL changes, cwd-junction creation or child launch.
- Both public dedicated-account readonly/workspace token factories.

The runner's existing error path sends ErrorStage::SpawnChild and returns
before SpawnReady or Exit. Provisioning APIs, default configuration and raw
general-purpose Win32 process helpers are unchanged; they are not promoted to
qualified sandbox substitutes.

## Validation and next acceptance

Source checks confirmed unique first-statement guards at all six entry points,
unchanged original regression-group objects and policy, and a distinct six-case
admission inventory (five library cases and one binary case). These are source
checks, not native passes.

At preparation time the managed executor disconnected and was reported
unavailable. Local just fmt, just test --locked -p codex-windows-sandbox,
scoped lint, and native Windows execution are **NOT_RUN**. Exact GitHub CI on
this candidate must be read separately; prior passes cannot transfer. The
existing Windows workflow remains enabled and preserves every original failure.

Closing the functional P0 requires actual execution under a filesystem
isolation mechanism that preserves the required reads and inside mutations
while protecting outside objects under all original permission cells. Loader,
IPC, descendants, cold setup/recovery and full platform acceptance remain
separate requirements. No merge, deployment or production adoption is claimed.

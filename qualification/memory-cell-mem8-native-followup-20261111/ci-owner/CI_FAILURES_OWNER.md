# Owner PR #5972: blocking CI failure attribution

## Scope and source identity

Read-only review of the three requested failed jobs in [blocking-ci run 43024095323](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43024095323), attempt 1. No rerun, source edit, or new CI invocation was performed. Other running/cancelled checks were not treated as passing evidence.

- PR head: `2e0f6ff4525a02143f700dee70309ef9b6169398`.
- Current PR base: `9bd2f589debdba4a93baa363817c3669cb103721`.
- Actual Windows checkout: merge `ddc505e2e9025e4994aa73d30a507de1c632a63e`, tree `2e3cb076a7e6b5bc83c9ffde2c28c7052b00715b`.
- Merge parents are exactly the current PR base and PR head above. The merge has the same seven changed owner-patch paths recorded in `pr-5972-files.json`.
- The independent native qualification base `189711e3563ea13a5328d52e99a286f082045b98` is a different source identity. Its native results do not certify this later merge.

Evidence: `run-43024095323.json`, `run-jobs-snapshot.json`, `merge-ddc505e2.json`; both Windows checkout logs explicitly print the merge and its two parents.

## Findings

| Job | Observed failure | Attribution supported by the retained evidence |
|---|---|---|
| [Blob size policy, 130534279170](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43024095323/job/130534279170) | Fence resident service exits before readiness; error code `local_control_inventory_unavailable`. | Infrastructure setup failure before checkout. Blob comparison and size checks were skipped; this is not a blob-size rejection of the seven-file patch. |
| [Windows Bazel shard 4/4, 130534450487](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43024095323/job/130534450487) | Final failed test-log output is the existing hard-link apply-patch test in `core-all-test`, internal shard 13/16. Earlier failed-attempt output also contains one remote-environment case and one subagent-hook case. | The failing test files are byte-identical to the current PR base. The hard-link assertion changed between 189 and that base; it was not introduced by this owner patch. No same-source baseline run was performed here, so this is source attribution, not proof that every observed failure reproduces without the patch. |
| [Windows Bazel shard 2/4, 130534450558](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43024095323/job/130534450558) | Two ordinary-host delete-matrix controls fail, followed by three `legacy Windows sandbox process test lock poisoned` failures. | The two primary assertions fail before their subsequent restricted-sandbox operations. The source is inherited unchanged from the current PR base. The three lock errors are downstream failures, not three independent capability regressions. |

### Blob policy: no repository test ran

`job-130534279170.raw.log` records Fence `ActiveState=failed`, `ExecMainStatus=1`, then `local_control_inventory_unavailable`. Checkout, comparison-range setup, policy tests, and changed-blob checks are all skipped in the steps record. The later missing local `check-clean-worktree` action and unavailable Fence mount evidence follow the missing checkout/setup; neither establishes a source-code defect.

### Shard 4: exact cases and failure boundaries

The persistent hard-link case is:

```text
suite::apply_patch_cli::apply_patch_cli_preserves_existing_hard_link_outside_workspace
```

At `core/tests/suite/apply_patch_cli.rs:1218`, the Windows branch requires both exit code 1 and the specific message `restricted filesystem write requires a file with exactly one hard link`. The actual tool output has exit code 1 and generic `Failed to write file ...\\hard-link.txt`. This diagnosis assertion fails in the printed attempts and final failed-test log. The subsequent assertions reading the outside and workspace files were not reached in this test path, so this failure must not be relabelled as verified boundary success.

The earlier internal shard 1/16 failed-attempt output also records:

- `suite::remote_env::deferred_executor_spawn_agent_inherits_ready_step_environments::test_case_1_v1`: Wiremock expected four matching requests, observed zero.
- `suite::subagent_notifications::subagent_stop_replaces_stop_and_skips_internal_subagents`: expected at least two entries in `subagent_stop_hook_log.jsonl`, observed one.

The final failed-test-log group prints the hard-link case. The retained log contains existing Bazel attempt records; this audit did not initiate another attempt. Both earlier cases remain observations from this run, not demonstrated owner-head regressions.

### Shard 2: host controls and poisoned lock

Primary cases:

```text
token::tests::legacy_workspace_capability_refuses_all_four_native_delete_routes
unified_exec::tests::delete_permission_tests::legacy_refuses_before_elevated_four_cell_delete_boundary
```

The first fails at `token_tests.rs:444`: ordinary-host file and directory deletion in the `Neither` cell returned no error, where the test expects `PermissionDenied` / Windows error 5. The second fails at `delete_permission_tests.rs:71`: the ordinary-host cmd control physically deleted both objects in that cell, where the test expects them to remain. Logs report enabled `SeBackupPrivilege` and `SeRestorePrivilege`; this is relevant observed host context, not a fully established causal explanation. Both failed assertions precede the later restricted-sandbox operations in their respective source paths.

The other three failures are explicitly `PoisonError` while acquiring the shared legacy process-test mutex:

```text
unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit
unified_exec::tests::legacy_non_tty_refuses_before_elevated_cmd_emits_output
unified_exec::tests::legacy_non_tty_refuses_before_deny_read_setup
```

The previously discussed outside-delete case, `unified_exec::tests::legacy_refuses_before_elevated_delete_is_limited_to_writable_roots`, is explicitly **ok in this run**. These failures must not be equated with that older failure solely from their Windows/delete terminology.

## Exact source comparisons

All six paths below have equal Git blobs in the current PR base and tested merge. The full SHAs and refs are retained in `source-comparisons.json`.

| Path | Current base = tested merge | Also identical to independent 189 base? |
|---|---|---|
| `codex-rs/core/tests/suite/apply_patch_cli.rs` | `a41fc531be015f02aa5f7aef58b16cd4db2e0ada` | No |
| `codex-rs/core/tests/suite/remote_env.rs` | `f696a10caaeff2a1ce731f830d9006cf96383c2a` | Yes |
| `codex-rs/core/tests/suite/subagent_notifications.rs` | `3b429cac96b5f0bc21dc2121ae65de5477020e07` | Yes |
| `codex-rs/windows-sandbox-rs/src/token_tests.rs` | `1f16623dbea1b021a6b67d5e52ff9f90973d5d26` | No |
| `codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs` | `5e33c4fbea42cf69fcd5e8da2bbbef0943fdd31f` | No |
| `codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs` | `913096ca90dced2efa4aa4e3366193e3a6761b50` | Yes |

The owner patch only changes episodic read validation and its tests in `hepta-agentd` / `hepta-memory`. The located failure sites and controls are outside that delta. This gives no direct evidence that the owner guard caused these failures, while also not proving the entire merge equivalent to the independently qualified 189 source.

**CI remains blocked.** The defensible classifications are pre-checkout infrastructure failure and failures in current-base-inherited test paths. Calling all Windows failures “known 189 baseline failures” or marking the owner PR globally green would exceed the evidence.

## Retained original logs

The GitHub tool returns decoded log text. These files retain that returned content reencoded as UTF-8, including its BOM and original newline sequences; no claim is made that they are the original compressed transport bytes.

| File | Bytes | SHA256 |
|---|---:|---|
| `job-130534279170.raw.log` | 3,859 | `19c2bbce05df19c8c7f8c920b18d8668dce791e078ebcbe042265d398d3f84c5` |
| `job-130534450487.raw.log` | 717,582 | `fbdf600480fc5477d162ec9be5afce945f7d99c177487de42b4804400167bdd1` |
| `job-130534450558.raw.log` | 527,005 | `2a6e9e0189b045a97b9eba24e7f611d477a29916bccd5f69b3c41b891b3817db` |

Each job also has its original decoded-log JSON and step summary. Source excerpts preserve the precise assertions used for attribution. `EVIDENCE_MANIFEST.json` inventories the local evidence files.

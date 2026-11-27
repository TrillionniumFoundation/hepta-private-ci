# Windows four positive elevated failures: fixture causality review

## Finding

A private fixture cannot resolve these four observed failures while preserving the current production admission and the original positive calls. At exact source `6cbad406a4a203201edc0e103c1377d3664e3fbe`, `require_elevated_filesystem_isolation()` takes **zero arguments** and its complete body is `Err(ElevatedWindowsSandboxIsolationUnavailable.into())`. It performs no path, owner, DACL, environment, or feature inspection.

All four tests call the explicit elevated wrapper in `unified_exec/mod.rs:196–235`, which forwards to `unified_exec/backends/elevated.rs`. That backend's first statement, line 134, calls the unconditional guard. The return precedes permission resolution at line 143 and `prepare_elevated_spawn_context_for_permissions` at line 148. The original `.expect` then fails at test lines 298, 970, 1165, or delete-matrix line 171. There is no fixture-sensitive branch on the observed call path.

## Original contracts remain necessary

| Test | Positive behavior retained |
| --- | --- |
| `elevated_non_tty_cmd_forwards_env_output_and_exit` | The real command emits its supplied environment marker and reports exit 23. |
| `legacy_non_tty_refuses_before_elevated_cmd_emits_output` | Legacy refusal preserves fixture bytes; the separate explicit elevated command emits the original marker and exits 0. |
| `legacy_refuses_before_elevated_delete_is_limited_to_writable_roots` | Legacy refusal preserves fixture and home; elevated execution deletes workspace/TEMP/TMP files, keeps the outside file byte-equal, and keeps protected `.git`. |
| `legacy_refuses_before_elevated_four_cell_delete_boundary` | Ordinary host control verifies all four native deletion routes; elevated execution deletes allowed objects and preserves all outside-root matrix objects with the original ACLs. |

The fourth test already uses explicit **protected DACLs**, not uncontrolled inherited matrix permissions. `DeleteMatrix::new` independently grants or denies target `DELETE` and parent `FILE_DELETE_CHILD` to Everyone for Neither, TargetOnly, ParentOnly, and Both. It compares complete ACL bytes between the host and restricted matrices and observes the original host command's physical deletion results. Replacing those grants with private-only ACLs would alter the security challenge. Merely adding an outer private directory cannot affect the earlier unconditional admission return.

This establishes the cause of the current errors; it does not certify later fixture behavior that execution never reaches.

## Why prior fixture work does not close this failure

The three source fixtures from PR #6798 are present in `6cb`. Two synchronize their test bodies around a shared production named mutex; the shadow directory-flush fixture creates a real private directory before invoking path-dependent private-state validation. Those fixes address actual fixture ownership or scheduling prerequisites. They change neither the four positive elevated tests nor their unconditional production admission. PR #6798 is itself still open/draft in current API metadata; its source changes have been incorporated into the audited source independently.

The Windows-on801 prepared candidate changes only three AppContainer diagnostic sources and one observation workflow. Its metadata records the Rust subtree unchanged. It supplies child/profile observations, not a qualified filesystem isolation implementation or a route admitted by the original positive sandbox API. No unknown diagnostic/native job was queried or executed here.

## Current execution evidence

Direct source job [136829413586](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44898577556/job/136829413586) executes all 11 declared process groups, 77 selected cases, with zero retries: 73 pass and these four fail. Combining its disjoint selections with the owners job gives 19 groups and 175 unique cases: 171 pass, four fail. The aggregate explicitly reports `FAIL_DECLARED_WINDOWS_SCOPE`. The same four failures appear in current synthetic-merge Bazel Windows shard 2; that merge has the same source tree.

No fixture or production files were edited, no tests were executed, and no admission, positive assertion, timeout, or C2D persistence code was changed. The structured report records exact source paths, lines, hashes, contracts, and both source/merge execution identities.

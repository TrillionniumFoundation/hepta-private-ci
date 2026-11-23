# Original #7021 Windows shard 4 final results and retries

| Original run (attempt 1) | PR head | Prospective merge tested | Shard summary |
| --- | --- | --- | --- |
| [#7021 Windows job 137575118379](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45139490724/job/137575118379) | `4de33d145135dc2018b013f39b9ad8903e3a4208` | `8f8bceff9c84e77fad567fde6e95f57692fe5dbe` | 122 passed, 2 failed, 47 skipped of 171 |
| [#7016 c12 Windows job 137573328593](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/job/137573328593) | `c12ee03f3185d5a13949faca54f066dfd634e509` | `ae404b2935fa0b7ea39bf09ef1016917a507f6d5` | 121 passed, 3 failed, 47 skipped of 171 |

The numbers below count distinct archived executions of each Rust case, including its terminal execution. Collector reprints of the same file are counted once.

| Exact Rust case | #7021 | c12 |
| --- | --- | --- |
| `suite::windows_sandbox::windows_elevated_does_not_create_missing_workspace_metadata` | failed 3/3 | failed 3/3 |
| `suite::windows_sandbox::windows_elevated_enforces_deny_read_and_protects_setup_marker` | failed 3/3 | failed 3/3 |
| `suite::windows_sandbox::windows_elevated_unified_exec_enforces_managed_deny_reads` | failed 3/3 | failed 3/3 |
| `restricted_tokens_select_stable_routes_and_cleanup` | failed 1/1 | failed 1/1 |
| `exec_server_resumes_detached_session_without_killing_processes` | passed 1/1, executable 6/6 in 0.68 s | failed 1/1, executable 5/6 in 6.32 s |
| `suite::subagent_notifications::multi_agent_v2_spawn_sends_agent_message_to_child::test_case_2_plaintext` | failed first, passed retry | passed 1/1 |
| `suite::remote_env::deferred_executor_spawn_agent_inherits_ready_step_environments::test_case_1_v1` | passed 1/1 | failed first two, passed third |

The two terminal #7021 Bazel failures are `//codex-rs/core:core-all-test` and `//codex-rs/network-proxy:network-proxy-windows_stable_ingress-test`. All four terminal Rust failures occur under the same names in c12. The new observed failure *attempt* on #7021 was the plaintext replay check in core internal shard 3. The first attempt reported `plaintext function-call metadata should survive replay` at `core/tests/suite/subagent_notifications.rs:1949:9`. The subsequent run of that exact case passed. The seven failed core target attempts comprised one in internal shard 3, three in shard 7 and three in shard 15, among 21 core executions. These counts use different units from the four terminal Rust cases. The separate [diagnostic run](native-full-shard.md) retained the earlier intermittent detached-session issue.

Both original compact artifacts report complete observed scope. All 22 (#7021) and 24 (c12) materialized log/XML pairs passed their individual SHA-256 and length checks against the publisher's manifests. The final test archives independently contain the same four and five terminal Rust failures, respectively. In the #7021 compact package, the first and final shard-3 text logs have SHA-256 `04658622616e590e1998a18276cf818c231310c66320f19a67ff0dcfbf3602e0` and `c097d77fdd2c1950c0daad9bec237c54bc7082fa1b09c7ebb5237343642a7fe7`.

| Publisher artifact | SHA-256 |
| --- | --- |
| [#7021 final test logs](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45139490724/artifacts/14802244409) | `f28e282161da9d137cfb4154ed550a2f0861595e0da72af567b1bb8befb39642` |
| [#7021 complete attempt records](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45139490724/artifacts/14802244419) | `6e7c196b42bd541d0021725c289ab71f2bcdf00b566573dbb7ad42c74ed54d01` |
| [c12 final test logs](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/artifacts/14802049282) | `1f4f551c88fd1b1d221b101663e680502f061f6b919e7aca72b2b358ece47e01` |
| [c12 complete attempt records](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/artifacts/14802682568) | `5fd5a3fffc67aa553c30c8facf8179dfedea2b7acc93679684bac10062af3162` |

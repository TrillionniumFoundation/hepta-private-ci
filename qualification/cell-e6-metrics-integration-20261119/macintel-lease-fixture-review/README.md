# Mac Intel cognitive fixture failure: read-only diagnosis

The new head `8240292307116aa4063f7c63d8cdf48a0e8ef773` was tested at prospective merge `41efe113b0becba5234af5c0de197c31bb5a4581`. Its Mac Intel job 136202215451 passed `hepta-agentd-unit-tests` in 115.6 seconds, but failed `hepta-agentd-cognitive-write-qualification-test` in 2.7 seconds. This is not an overall Mac pass.

The failed test minted a local qualification lease with `minted_at.as_secs() + 1`. At this particular wall-clock phase the residual lifetime was only 52 ms. Opening the bound compact executor happened after 263 ms of monotonic elapsed time; the unchanged product lease guard rejected it as expired. The log records a wall-clock observation 212 ms after the expiry boundary.

This happened before the test appended its H7 start/terminal records, before its intended two-second wait, and before its final quarantine assertion. That later behavior was not validated by this failed execution. The source control flow establishes what was not reached; no separate database inspection was performed.

Exact GitHub file reads, with recomputed Git blob SHA-1 and SHA-256, show byte-identical `runtime_tests.rs`, `local_lease_outbox.rs`, `local_compact_executor.rs`, and `logical_turn_registry.rs` at 238, d1d, 824, and merge41. `runtime_tests.rs` is Git blob `fb2459cbdb6f9d774858cc795cc2d9de406d76f4`, SHA-256 `098d5535c136f987c6ee3f27cb1ea2ab65e4c172e908d1c725dbbe4a1bcaceb3`.

The new `material_tempdir` is private to a different test module. This cognitive fixture uses its own `tempfile::tempdir` and canonicalization. The Bazel cognitive target filters `runtime::tests::qualification_`, which does not select the six material tests. There is no observed direct helper call path causing this failure.

The relevant product path is `open_local_compact_executor_bound` → `LocalCompactExecutor::open_bound` → `verify_current_in_transaction` → `ensure_current_active`. The final check rejects `now >= expires_at` as `StaleFence("local lease has expired")`. The observation is consistent with this pre-existing fixture timing window and the unchanged expiry guard. It does not establish a helper-induced product regression.

Run 44710897181 is completed with failure. Linux and Windows Clippy passed. The four ARM `macos-15` jobs were cancelled with `runner_id=0` and no runner name; they supply no ARM execution evidence. The cancellation cause has not been established. No rerun or cancellation was requested by this reviewer.

All raw source responses and the full original Mac Intel job log are retained in the archive and indexed by hash. This review performed zero model calls, training updates, native replays, Cargo invocations, or remote host jobs. It did not change code, lease lifetimes, assertions, workflows, or refs.

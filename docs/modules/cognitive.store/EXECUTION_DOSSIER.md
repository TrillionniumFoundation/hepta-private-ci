# cognitive.store execution dossier index

Generated from `CURRENT_STATE.json` and `QUALIFICATION_PLAN.json`; this is not a pass receipt.

Both lanes use the same frozen source and base. The merge lane verifies ordered parents
and recomputes the merge tree. Every command has an exclusive record and bounded log.

| Required record | Working directory | Command | Minimum observed tests |
|---|---|---|---|
| `workspace.json` | `codex-rs` | `cargo metadata --locked --format-version 1 --no-deps` | 0 |
| `boundary.json` | `.` | `python3 scripts/verify_cognitive_store_boundary.py --output $RUNNER_TEMP/cognitive-boundary-receipt.json` | 0 |
| `implementation-map.json` | `.` | `python3 scripts/cognitive_store_map_verify.py --expected-sha $TESTED_SHA --expected-tree $TESTED_TREE` | 0 |
| `map-regressions.json` | `.` | `python3 scripts/test_cognitive_store_map.py -v` | 12 |
| `manifest-regressions.json` | `.` | `python3 scripts/test_cognitive_qualification_manifest.py -v` | 11 |
| `plan-binding-regressions.json` | `.` | `python3 scripts/test_cognitive_plan_binding.py -v` | 39 |
| `shared-exec-regressions.json` | `.` | `python3 scripts/test_hepta_ci_exec.py -v` | 15 |
| `shared-exec-deadline-regressions.json` | `.` | `python3 scripts/test_hepta_ci_exec_deadline.py -v` | 9 |
| `shared-exec-output-regressions.json` | `.` | `python3 scripts/test_hepta_ci_exec_output.py -v` | 21 |
| `api-probe-regressions.json` | `.` | `python3 scripts/test_cognitive_store_api_probe.py -v` | 12 |
| `status-drift.json` | `.` | `python3 scripts/cognitive_store_status.py --check` | 0 |
| `module-inventory.json` | `.` | `python3 scripts/check-rust-module-inventory.py codex-rs/hepta-cognitive-store/src` | 0 |
| `host-bootstrap.json` | `.` | `python3 tools/cognitive-store-host-bootstrap/test_bootstrap.py` | 1 |
| `expired-bootstrap-cli.json` | `.` | `python3 tools/cognitive-store-host-bootstrap/test_expired_cli.py` | 1 |
| `lifecycle-owner-receipts.json` | `.` | `python3 tools/cognitive-store-host-bootstrap/test_lifecycle.py -v` | 32 |
| `archive-dependencies.json` | `.` | `python3 tools/cognitive-store-host-bootstrap/prepare_archive_env.py` | 0 |
| `archive-publication-boundary-tests.json` | `.` | `$RUNNER_TEMP/cognitive-archive-venv/bin/python tools/cognitive-store-host-bootstrap/test_archive_publication.py -v` | 21 |
| `lifecycle-final-use-tests.json` | `.` | `$RUNNER_TEMP/cognitive-archive-venv/bin/python tools/cognitive-store-host-bootstrap/test_lifecycle_final_use.py -v` | 12 |
| `recovery-report-regressions.json` | `.` | `python3 scripts/test_cognitive_store_recovery_report.py -v` | 21 |
| `archive-protocol-tests.json` | `.` | `$RUNNER_TEMP/cognitive-archive-venv/bin/python tools/cognitive-store-host-bootstrap/test_archive.py -v` | 45 |
| `publication-observation-tests.json` | `.` | `$RUNNER_TEMP/cognitive-archive-venv/bin/python tools/cognitive-store-host-bootstrap/test_publication_observation.py -v` | 35 |
| `observation-boundary-tests.json` | `.` | `$RUNNER_TEMP/cognitive-archive-venv/bin/python tools/cognitive-store-host-bootstrap/test_observation_boundary.py -v` | 17 |
| `archive-owner-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-memory --test cognitive_archive_owner signed_archive_restores_real_correction_and_tombstone_history -- --ignored --exact` | 1 |
| `format.json` | `codex-rs` | `cargo fmt --package codex-hepta-cognitive-store --package codex-hepta-memory --package codex-hepta-agentd -- --check` | 0 |
| `default-feature-check.json` | `codex-rs` | `cargo check --locked -p codex-hepta-cognitive-store --no-default-features --lib` | 0 |
| `agentd-normal-profile-check.json` | `codex-rs` | `cargo check --locked -p codex-hepta-agentd --lib` | 0 |
| `api-probes.json` | `.` | `python3 scripts/cognitive_store_api_probe.py --output $RUNNER_TEMP/cognitive-api-probes.json` | 0 |
| `cognitive-store-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-cognitive-store --all-features` | 1 |
| `memory-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-memory` | 1 |
| `publication-fault-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-memory --test cognitive_recovery_publication_fault` | 1 |
| `recovery-final-use-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-memory final_use_tests` | 2 |
| `agentd-product-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-agentd --test cognitive_store_product_writer --features qualification-cognitive-write` | 1 |
| `bootstrap-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-agentd --test cognitive_bootstrap --features qualification-cognitive-write` | 1 |
| `recovery-boundary-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-agentd --test cognitive_recovery_boundary --features qualification-cognitive-write` | 8 |
| `normal-read-page-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-agentd --test cognitive_store_read_pages` | 3 |
| `normal-host-read-page-tests.json` | `codex-rs` | `cargo test --locked -p codex-hepta-agentd --test cognitive_store_host_read_pages` | 1 |
| `crash-reopen.json` | `codex-rs` | `cargo test --locked -p codex-hepta-memory local_lease_outbox_tests::qualification_durable_writer_crash_reopen_probe -- --ignored --exact` | 1 |
| `perf-256.json` | `codex-rs` | `cargo run --locked --release -p codex-hepta-memory --example cognitive_store_perf` | 0 |
| `perf-16384.json` | `codex-rs` | `cargo run --locked --release -p codex-hepta-memory --example cognitive_store_perf` | 0 |
| `history-64-16.json` | `codex-rs` | `cargo run --locked -p codex-hepta-memory --example cognitive_store_history_perf` | 0 |
| `history-128-64.json` | `codex-rs` | `cargo run --locked -p codex-hepta-memory --example cognitive_store_history_perf` | 0 |
| `recovery-release-256.json` | `codex-rs` | `cargo run --locked --release -p codex-hepta-memory --example cognitive_store_recovery_perf` | 0 |
| `recovery-release-256-report.json` | `.` | `python3 scripts/cognitive_store_recovery_report.py --report $RUNNER_TEMP/cognitive-recovery-perf-256.json --source-commit $SOURCE_SHA --tested-commit $TESTED_SHA --tested-tree $TESTED_TREE --records 256 --minimum-repetitions 3 --require-rss` | 0 |
| `recovery-release-16384.json` | `codex-rs` | `cargo run --locked --release -p codex-hepta-memory --example cognitive_store_recovery_perf` | 0 |
| `recovery-release-16384-report.json` | `.` | `python3 scripts/cognitive_store_recovery_report.py --report $RUNNER_TEMP/cognitive-recovery-perf-16384.json --source-commit $SOURCE_SHA --tested-commit $TESTED_SHA --tested-tree $TESTED_TREE --records 16384 --minimum-repetitions 3 --require-rss` | 0 |
| `clippy.json` | `codex-rs` | `cargo clippy --locked -p codex-hepta-cognitive-store -p codex-hepta-memory -p codex-hepta-agentd --all-targets --all-features --no-deps -- -D warnings` | 0 |
| `clean-source.json` | `.` | `git diff --exit-code HEAD --` | 0 |

A v2 qualification manifest is retained even when work fails or is not executed.
It binds source/base/tested commits and trees, workflow blob/SHA, runner image, toolchain,
run ID/attempt, actual command exit codes, minimum/observed test counts, raw-log digests,
and artifact digests. Missing/skipped/running evidence cannot become terminal-success.

## Host and data-lifecycle boundary

The process-exit regression uses the real writer and SQLite, but fixture authority.
The post-rename regression injects a real Linux directory-fsync failure through
the public recovery entry, but it is not selected-host filesystem evidence. A
trusted target-host run must separately establish signer governance, witness
reconciliation, filesystem fault injection, canary, restart, and strictly newer
rollback generations.

History profiles measure corrections, tombstones, growth, snapshots, and reopen cuts.
They neither implement history pruning nor prove payload erasure in backups or derived artifacts.

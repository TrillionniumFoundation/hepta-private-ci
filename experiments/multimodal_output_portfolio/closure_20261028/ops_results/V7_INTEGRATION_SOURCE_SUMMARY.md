# v7 exact integration payload

Parent generator source: `943768d41de711ef888d8c21c1466aa783885307`.

This review bundle contains the 33 reviewed source changes and both actual generated locks. The working-tree dependencies have not been changed. The complete candidate patch passed a private-index check with no conflicts. The integration manifest pins every file byte and Git executable mode, the original policy inputs, the frozen recipe and the exact producer receipt.

Integration manifest SHA-256: `ef1fc0a4cfd8c2621eeb82e413555c1ea1780020a1f74f7c666253b62a5bfde2`.

| Source path | Added lines | Removed lines |
| --- | ---: | ---: |
| `MODULE.bazel` | 2 | 2 |
| `codex-rs/Cargo.toml` | 27 | 14 |
| `codex-rs/core-plugins/Cargo.toml` | 1 | 1 |
| `codex-rs/core-plugins/src/command_migration.rs` | 4 | 17 |
| `codex-rs/core-plugins/src/plugin_metrics.rs` | 1 | 1 |
| `codex-rs/core-plugins/src/startup_sync.rs` | 28 | 6 |
| `codex-rs/core-plugins/src/startup_sync_zip_tests.rs` | 196 | 0 |
| `codex-rs/core-plugins/tests/fixtures/zipball_lzma.zip` | - | - |
| `codex-rs/ext/skills/Cargo.toml` | 1 | 1 |
| `codex-rs/ext/skills/src/loader/environment.rs` | 2 | 2 |
| `codex-rs/ext/skills/src/loader/metadata.rs` | 1 | 1 |
| `codex-rs/external-agent-migration/Cargo.toml` | 1 | 1 |
| `codex-rs/external-agent-migration/src/subagents.rs` | 11 | 17 |
| `codex-rs/hepta-matrix-sdk/Cargo.toml` | 1 | 0 |
| `codex-rs/hepta-matrix-sdk/src/config.rs` | 2 | 0 |
| `codex-rs/hepta-matrix-sdk/src/gap_fill_tests.rs` | 45 | 2 |
| `codex-rs/hepta-matrix-sdk/src/sdk.rs` | 103 | 36 |
| `codex-rs/hepta-matrix-sdk/src/startup_deadline_tests.rs` | 127 | 0 |
| `codex-rs/hepta-matrix-sdk/tests/event_context_migration.rs` | 127 | 0 |
| `codex-rs/hepta-matrix-sdk/tests/store_version_migration.rs` | 312 | 0 |
| `codex-rs/rust-toolchain.toml` | 1 | 1 |
| `codex-rs/skills/Cargo.toml` | 1 | 1 |
| `codex-rs/skills/src/parser.rs` | 4 | 4 |
| `codex-rs/third_party/imbl-6.1.0/BUILD.bazel` | 12 | 6 |
| `codex-rs/third_party/matrix-sdk-sqlite-0.18.0/BUILD.bazel` | 12 | 7 |
| `codex-rs/utils/yaml/BUILD.bazel` | 6 | 0 |
| `codex-rs/utils/yaml/Cargo.toml` | 20 | 0 |
| `codex-rs/utils/yaml/src/key.rs` | 43 | 0 |
| `codex-rs/utils/yaml/src/lib.rs` | 197 | 0 |
| `codex-rs/utils/yaml/src/yaml_tests.rs` | 113 | 0 |
| `codex-rs/utils/yaml/tests/legacy_projection.rs` | 115 | 0 |
| `codex-rs/windows-sandbox-rs/Cargo.toml` | 1 | 0 |
| `codex-rs/windows-sandbox-rs/tests/helper_manifest.rs` | 1 | 5 |

The binary ZIP fixture uses exact bytes from the candidate artifact; it is 194 bytes, SHA-256 `b6ce81e8450c7de591a4e4c7e2e9e975542cc709a07487e16d8f0dfaf7e3d30c`. No binary reconstruction from text is needed.

The dependency changes cover the reviewed Rust/compiler and Cargo/Bazel ports for YAML, AWS, credential storage, Matrix, Starlark, compression and Windows helper compatibility. Existing vendor inventories and fixed policy rules remain frozen. The detailed version/feature graph and actual CI qualification boundaries are in CI_V7_VERIFIED_RESULT.json.

Apply the 35 exact payloads together with the explicit integrated-source mode. The new mode must verify the committed payload identities and modes, same-run artifacts and clean current HEAD; run actual Cargo metadata, just bazel-lock-update/check with zero drift; retain all vendor/graph/policy and behavioral qualification. The old patch mode keeps its unconditional check/apply behavior.

## Startup budget is an explicit runtime change

The candidate adds one predeclared 20-second SDK startup budget. It is not a value derived from an enforced Supervisor minimum. The existing Supervisor default health timeout is 60 seconds; the real Synapse test uses a 30-second readiness window and passes it to the Supervisor. Supervisor configuration only requires a finite, nonzero health timeout, so a custom shorter window is not automatically compatible with 20 seconds.

`restore`, `login_password` and `login_or_restore` establish one deadline. Local build, authentication and a fresh-client fallback share that original deadline. `authenticate_until` additionally caps the whole authentication future at the earlier of the shared deadline and five seconds from its start. This is not evidence that every underlying HTTP request has an independently configured five-second limit. Finalization checks expiry before and after event-cache activation and retains any session file already durably written. Synchronous KDF or filesystem work cannot be preempted by Tokio's timer: a late result is refused after it returns; a strict wall-clock execution cap is not established.

The actual v7 SDK command executed these four passing deadline tests:

| Actual test | Observed seconds | What it establishes |
| --- | ---: | --- |
| `expired_authentication_does_not_poll_the_request` | 0.007 | An expired authentication future is never polled. |
| `fresh_login_cannot_renew_expired_startup_budget` | 0.010 | An expired fresh login does not create its storage directory or renew its budget. |
| `authentication_returning_late_ready_cannot_activate_a_session` | 1.110 | A synchronous future returning late cannot be accepted. |
| `expired_finalization_rejects_success_without_erasing_a_written_session` | 11.222 | Real encrypted-store initialization completes in this Linux test; expired finalization refuses activation and keeps the already written session. |

These test durations come from job 122711813403 in run 40656660435. The four tests do not dynamically execute the complete failed-restore-to-fresh-login branch within one active budget; preservation of the shared deadline across that branch is visible in the frozen call chain, with native behavioral qualification still pending. They do not establish cold-start readiness on the native arm64 host or the complete Supervisor/Matrix/Synapse delivery path. That native business qualification remains open; its tool probe failed before execution. The separate 7.370-second old-store reopen pass does not replace this gate. No candidate source, timeout or frozen test was changed for this explanation.

[Supervisor default and validation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/943768d41de711ef888d8c21c1466aa783885307/codex-rs/hepta-supervisor/src/model.rs) · [Native readiness contract](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/943768d41de711ef888d8c21c1466aa783885307/codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs) · [Frozen SDK source patch](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/943768d41de711ef888d8c21c1466aa783885307/experiments/multimodal_output_portfolio/closure_v2_20261027/ci/port-remediation/combined-source-v7.patch) · [Actual SDK job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122711813403)

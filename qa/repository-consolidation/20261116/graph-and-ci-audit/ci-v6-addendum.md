# Native v6 validation addendum

**The v6 command failed with exit code 100.** It selected and ran 26 tests: nine passed, one failed, and 16 timed out. Another 1,584 tests were excluded by the recorded selection. The eight specifically requested control tests all passed.

This addendum preserves the primary report's 13:19:57 UTC snapshot, which correctly said v6 was running at that time. It supplies the later result without changing that historical document or any source.

## Execution and source identity

| Item                       | Recorded value                                                     |
| -------------------------- | ------------------------------------------------------------------ |
| Validated source commit    | `d3746789d49ca8a4bb5600e0c6fbe682ef5f1765`                         |
| Validated source tree      | `751e50a0172e467176be68a1331519c8ea171307`                         |
| Native execution base      | `285e971b3af3a93a79169b56a42263069e473057` plus recorded overlays  |
| Command elapsed time       | 1,407.174 seconds, including compilation                           |
| Test execution time        | 289.177 seconds                                                    |
| Input inventory            | 7,748 entries, all unchanged during execution                      |
| Stack setting              | Original 8 MiB                                                     |
| Nextest budget and retries | Original 60 seconds; zero retries                                  |
| Test threads               | Four                                                               |
| Raw log SHA-256            | `bde487fe8413f5b7fd963cdc542a5b788c0c9df225c9571f9978ce5beb4d22ba` |

The [result receipt](ci-v6-evidence/combined-native-v6-result.json.gz) contains the exact `just test --locked --lib -p codex-hepta-agentd` command and filter. The [invocation](ci-v6-evidence/native-v6-invocation.json.gz) and [source inventory](ci-v6-evidence/native-v6-input-sources.json.gz) preserve the environment and hashes.

The [candidate comparison](ci-v6-evidence/native-v6-candidate-source-bridge.json.gz) still has 7,742 matching entries and six different test paths. All recorded Agentd inputs match the validated source. The previous exact-source B4 and caller proofs remain valid for their recorded scope; no source changed for this addendum.

## Eight control tests actually matched and passed

| Test                                                                              | Result | Seconds | Source definition                                |
| --------------------------------------------------------------------------------- | ------ | ------: | ------------------------------------------------ |
| `original_control_frame_preserves_partial_write_errors_before_shutdown`           | PASS   |   0.032 | `control_frames_tests.rs:115`                    |
| `original_control_frame_preserves_other_shutdown_errors`                          | PASS   |   0.032 | `control_frames_tests.rs:131`                    |
| `original_control_frame_accepts_not_connected_only_after_complete_write`          | PASS   |   0.037 | `control_frames_tests.rs:105`                    |
| `original_control_frame_rejects_oversize_input_before_admission`                  | PASS   |   0.039 | `control_frames_tests.rs:25`                     |
| `original_control_frame_bounds_a_nonreading_response_peer`                        | PASS   |   2.034 | `control_frames_tests.rs:43`                     |
| `original_control_frame_rejects_partial_input_with_unchanged_io_budget`           | PASS   |   2.039 | `control_frames_tests.rs:12`                     |
| `feature_socket_ack_timeout_recovers_original_completion_without_redispatch`      | PASS   |  16.808 | `circuit_feature_control_completion_tests.rs:12` |
| `source_capture_control_retains_connection_error_without_stopping_other_requests` | PASS   |   0.273 | `control_source_capture_tests.rs:93`             |

These are Linux library tests. They preserve the original bounded I/O checks and the distinction between a successful completed write followed by `NotConnected` and a real read/write/transport failure. They do not qualify the original macOS five-agent scenario or Windows behavior.

The ninth pass is `original_panel_fixture_future_layout_diagnostic` in 0.032 seconds. It is a layout diagnostic, not evidence that the functional evaluation path completes.

## The 17 nonpasses

The sole ordinary failure is `q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources` after 48.641 seconds. Its first error is:

> original C Observer completion is uncertain; read the same operation

The test is defined at `circuit_deep_training_readback_tests.rs:25`; the first repository frame is line 114, column 17. The raw log records the error at line 2571. The independent `rust_review` task owns its diagnosis; this addendum records the observed failure without duplicating that investigation.

The remaining 16 cases are timeouts:

| Test family        | Count | First observed cause                                    |
| ------------------ | ----: | ------------------------------------------------------- |
| provider           |     3 | Nextest 60-second timeout; no test-level error captured |
| model material     |     3 | Nextest 60-second timeout; no test-level error captured |
| evaluation host    |     3 | Nextest 60-second timeout; no test-level error captured |
| training operation |     4 | Nextest 60-second timeout; no test-level error captured |
| panel              |     3 | Nextest 60-second timeout; no test-level error captured |

[The exact result map](ci-v6-evidence/native-v6-exact-test-results.json.gz) lists every fully qualified test name, source definition, observed duration, and log line. The structured addendum also records the first diagnostic for every nonpass.

Each timeout block contains only `running 1 test` and `test timed out`. No earlier provider-binding assertion or stack overflow appears in those blocks. The log therefore does not establish the precise stalled phase or prove that all 16 share one runtime root cause.

## Source leads and remaining evidence

[The source map](ci-v6-evidence/native-v6-timeout-source-map-reviewed.json.gz) shows the shared setup chain: `HostFixture::new` enters `PanelFixture::completed`, which enters `preregistered` and then `PositiveFixture::ready_with_admission`. Direct provider tests begin at `preregistered`; panel completion also populates and consumes actual B members. These locations are possible navigation points, not captured suspended instructions. The syntax map is not exhaustive inside macro token trees.

A useful next diagnostic is one original provider test with progress or a thread backtrace captured before its unchanged 60-second deadline. A timeout alone is insufficient evidence to increase the budget or classify the failure as intermittent.

The [addendum artifact manifest](ci-v6-artifact-manifest.json) binds the raw log, receipts, invocation, source inventory, result map, and report to exact hashes. Original bytes are preserved in deterministic gzip with no file above 500,000 bytes. The primary Windows admission and platform qualification blockers remain unchanged.

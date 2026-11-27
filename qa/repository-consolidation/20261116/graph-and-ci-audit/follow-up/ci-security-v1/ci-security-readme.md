# CI repairs, OAuth validation, and complete CodeQL source review

This checkpoint preserves the original failures and exact evidence for the reviewed repairs. The source and observation baseline is 7e04259b85ee2d3c31182c6b4be8b6a3ace29fc0. It does not certify the entire repository or replace final checks on the next published head.

## OAuth diagnostics

The four-file overlay classifies external callback codes, descriptions, nested token error messages, and non-JSON bodies into fixed diagnostic categories. Unknown values become a fixed unknown category. HTTP status, error kinds, entitlement guidance, state validation, PKCE and token protocol requests, success handling, and HTML escaping remain in place.

The original commands passed: just fix --locked -p codex-login, just fmt --check, the four focused regression tests, and just test --locked -p codex-login --status-level all --final-status-level fail. The full package ran **199 tests, all passed, zero skipped**. The four new regressions are included in those 199 tests. All 7,760 tracked validation inputs were unchanged in every phase, and the scoped fix changed no source bytes.

New regressions capture structured tracing, callback HTML, returned error display, debug formatting, and error source chains. They do not capture a real CLI or device-login child process stderr. The terminal diagnostic field is a fixed static string by type and source review. The function comparison preserves 28 server functions and nine integration test functions byte for byte; the only two changed production functions differ in the reviewed diagnostic blocks. The entitlement predicate body is identical after its move.

## Complete original CodeQL result review

The table contains all 195 original result indices. The complete JSON contains individual source locations, rule metadata, full-flow references, source hashes, compilation guards, reasons, and limitations. Its archive includes the original SARIF, all 98 non-pointer primary and data-flow source paths at both pinned heads, 29 additional source pins, all 32 pointer reviews and their proof archive, and the earlier client/CLI native proof.

The original rule scores are **137 results at 9.8, 57 at 7.5, and one at 8.1**. These scores are separate from confirmed vulnerability judgments. Flow classifications are 158 test or fixture, 35 production, and two experiment. The former 23 visible annotations are explicitly mapped to the full queue. No alert was dismissed and no rule was suppressed.

The review distinguishes deterministic test inputs and fully overwritten buffers from production uses. It also distinguishes required login instructions and intentional prompt display from redundant authentication diagnostics. The CLI partial-key output and client duplicate login diagnostics were repaired in 7e and validated by the earlier 666-test package run. The separate OAuth repair is validated in this checkpoint but was outside 7e. A new scan remains necessary.

## CI and platform evidence

The CI proof includes all three iterations of the five-file custody/docs repair and the four-file workflow prerequisite repair. Final changes preserve original scope, execution commands, test budgets, and approval guards. The observer expectation requires the exact ordered six packages, retaining the old five and the existing contracts package. It passed the original 16 tests and 12 missing/duplicate-package mutation rejections. Prerequisite validation passed the original UI 10, scientific audit 40, continuum seven, and factorial ten tests.

The 7e Intel macOS job did not pass. Before its original 120-minute job budget ended, Agentd unit tests reported **559 passed, 22 failed, two ignored**: one overlong Unix socket path, eight non-canonical cognitive fixture roots, and 13 non-canonical AuthBus checkpoint parents. The PTY unit target reported **29 passed and one deadline failure** in pty_dropped_output_receiver_keeps_draining_child. Core unit attempts recorded timeouts and a later Bazel flaky summary. The final job conclusion was cancelled at 17:09:49 UTC; this is not described as a budget-only failure.

Both old-head Windows pointer-compression builds completed successfully: ARM64 at 16:52:27 UTC and x86-64 at 16:59:58 UTC. These builds do not qualify the separately failing Windows elevated-admission functional tests. The Rust CodeQL job remained in analysis at the 17:12 UTC observation; no missing or neutral status is treated as a clean result.

## Archive reconstruction

Each manifest lists a single deterministic gzip stream split into ordered parts, each at most 480,000 bytes. Concatenate a package's parts in manifest order, verify the compressed SHA-256, then decompress the gzip stream and read the tar archive. Verify every member length and SHA-256 against its manifest. All archived source, log, receipt, and historical proposal bytes are preserved exactly; reconstruction was verified before publication.

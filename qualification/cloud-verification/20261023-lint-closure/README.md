# Strict lint dependency closure — 2026-10-23

Exact tested source: `77d25b6d1dda5d0718f226960a5cf85ea69f8be7`, tree `8bea1b178d49af3652e0d5982a35c4947a6346cf`. Base: PR #3599, `6a9fe952c9191dd342c9cc2e23d791cfbe8a6465`. Two commits, eight files. These are local cloud results; hosted CI is separately pending verification.

## Changes and provenance

- Five core/extension files reuse #2515, donor `eade627d9b1dbdc605a0d529030d701b53ac8891`, with matching preimages. Group response-stream inputs in `ResponseEventSource`; update all callers. Restrict a test-only constructor to tests and remove an unused private digest helper. No authorization, cancellation, redaction, or terminal-event behavior change is intended.
- Schema fixture reuses #2924, donor `8d1c0f8603f988dfcef77e808183931f18c4aab8`, with matching preimage: use the repository file-backed durable SQLite fixture rather than an in-memory pool. Migration inventory and trigger-rejection assertions remain.
- Final-use dispatch test helpers propagate errors with `Result` and `?` instead of 16 `expect` calls. All assertions remain; production dispatch code is unchanged.
- Full Memory tests on intermediate `4125a454a226c3d8c83ba7c5fff6d13141351794` exposed one real stale test oracle: 271 passed, one failed, seven skipped. Existing migration 0015 was absent from the expected list. Reuse the matching #2924 fixture change, ordering the SQL aggregation and asserting the complete sequence 1–15. No production migration changed. Original failure is retained in `memory-tests.log`.

`source-provenance.json` records per-file blobs. Both donors' preimages were checked before reuse. All eight final remote files were fetched and matched local content; the complete fetched source tree also matched. Independent review found no blocking issue; see `independent-review.md` and `independent-review-final-manifest.json`. Reviewed diff SHA-256: `4c70d44e9ce054660369072a6a3636effe68d29be54daeb452904b1fbd4a2613`. Review preceded the final completed rerun; the results below were executed by the primary agent.

## Exact-source validation

Commands ran from the source worktree at the exact SHA above. Each `final-*-exit.txt` records exit 0; corresponding logs preserve full output.

```sh
export RUSTUP_HOME=/workspace/rustup
export CARGO_HOME=/workspace/cargo
export PATH=/workspace/cargo/bin:$PATH
export CARGO_TARGET_DIR=/workspace/target-3567
export CARGO_BUILD_JOBS=2
export CARGO_INCREMENTAL=0

just test --locked -p codex-hepta-memory --lib
just test --locked -p codex-core --lib -E 'test(client::provider_policy_tests) | test(client::tests::dropped_response_stream) | test(client::tests::dropped_backpressured_response_stream) | test(client::tests::response_stream_records_last_model_feedback_ids) | test(client::tests::ephemeral_unauthorized_and_stream_errors_are_redacted)'
just test --locked -p codex-hepta-memory-extension --lib -E 'test(cognitive::tests)'
cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-memory --all-targets -- -D warnings
cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-app-server --all-targets -- -D warnings
just fmt --check --base 6a9fe952c9191dd342c9cc2e23d791cfbe8a6465
```

| Check | Final result |
|---|---|
| Memory library tests | 272 passed, 7 skipped |
| Selected core stream/provider-policy tests | 10 passed, 2412 not selected/skipped |
| Selected extension cognitive tests | 11 passed, 89 not selected/skipped |
| Memory strict Clippy **all targets** | Passed |
| App-server strict Clippy **all targets** | Passed |
| Changed Rust formatting | Passed |

The original 17 Memory all-targets violations and three extension/core errors are closed for these exact commands. Their baseline failure logs remain in the [previous report](../20261023-memory-clippy/README.md). No global lint allowance, test deletion, new ignored test, or relaxed authorization/recovery assertion was introduced.

## Environment and limits

Linux x86_64, Rust/Cargo 1.95.0, just 1.59.0, nextest 0.9.149; five CPUs, approximately 17 GiB RAM, no swap, 32 GB filesystem. Locked dependencies; two build jobs; incremental compilation disabled. Only regenerable incremental caches were removed to recover disk space; `cache-cleanup.txt` records removal. Final disk availability was approximately 6.9 GiB. No supplier calls, real credentials, model downloads, security-setting changes, merges, or deployments.

Not run on this final SHA: full core/extension/app-server behavioral suites, whole workspace, Bazel, Windows/macOS, earlier Bedrock/Python/250-test validation sets. Earlier results are not transferred to this combination. The seven existing skipped Memory probes include crash-child/qualification, capacity/latency, seeded stress, and host-restart soak tests. Runner pass counts do not establish physical power-loss or independent hardware acceptance. Configuration `OkOverridden` semantics are unchanged; no new all-error rollback guarantee is claimed.

All selected final local commands passed. Hosted exact-head CI must be checked on the new draft PR; queued CI is not a passing result. `SHA256SUMS` covers the evidence files except itself.

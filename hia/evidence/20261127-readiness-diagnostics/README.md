# Bounded startup diagnostics

The fleet readiness harness now includes the beginning of retained stderr alongside its existing output tails. Each stderr view is independently bounded to 4096 decoded UTF-8 bytes. The stdout tail remains bounded to 4096 bytes. This keeps an initial startup rejection visible after a long backtrace.

The real process fixture writes an initial error marker, more than 5000 bytes, and a final marker before exiting with code 17. The original five-second exit, tail limits, and failed-lifecycle assertions remain. Its strengthened expectation failed against the original harness and passed with the head view.

## Recorded execution

- Original SQLx 14-owner run: 2178 passed, one older-database recovery test failed, and 16 pre-existing cases skipped. Its complete original log is retained.
- Before control: one failing test, zero skips; both existing local-profile attempts report the initial cause missing.
- SQLx candidate after the diagnostic change: all four tests passed, including all three original kernel evidence product cases, with zero skips. `RUST_BACKTRACE=1` was explicit in both controlled runs.
- Exact base dependencies plus the two diagnostic source changes: Summary [  71.340s] 210 tests run: 210 passed (5 slow, 1 leaky), 6 skipped
- Strict scoped `just fix --locked --offline -p codex-hepta-agentd -- -D warnings` and repository `just fmt` both returned zero. The receipt records tested and final source identities; tests were not repeated after fix or formatting.

The published change includes the shared test harness and its existing real-process test. Cargo manifests and locks match base `73a86e4c0f7b6d4772dc259796f7492323acb539`. The SQLx feature-removal candidate remains separately owned.

All compressed logs round-trip to the original bytes and hashes recorded in `index.json`.

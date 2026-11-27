# CI scope repair after the reviewed Rust batch

The published ceb13 candidate failed three of the original 68 selector tests: a stale CLI crate-root expectation and two incomplete workflow concurrency identities. The source child fixes those exact contracts; all 68 original tests pass with zero skips and all 19 input hashes unchanged after execution. No implementation or dependency policy was relaxed.

The raw failing GitHub logs, exact patch, source-bound local receipt, formatter result and original-to-published commit identity are preserved here. Full required CI must run on the eventual published child. A skipped cargo-deny job supplies no new dependency acceptance result. Main and HIA refs remain unchanged by this source repair. The full branch audit remains in progress.

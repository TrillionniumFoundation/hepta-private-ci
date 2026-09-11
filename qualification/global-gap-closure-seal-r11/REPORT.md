# Hepta fixed-point convergence seal r10

- r8 qualified source: `dc8c66bde32429564989dada0208daa8b58cc178`
- r9 qualified source: `3c93f73172ad1b8392b1d7307e815ca1825f084c`
- r8 internal validation: `BLOCKED`
- r9 internal validation: `BLOCKED`
- filtered surface r8: `b1acb17f354e6c658a57a4b5599b9916a21af81666a110bca94ffa46237b58ff` (7765 entries)
- filtered surface r9: `82eeed3694ee1d26d723964efedc471fca871004c70c0f30cee9fecf88b4c966` (7765 entries)
- fixed point: `DRIFTED_OR_BLOCKED`
- external independent-authority gates: `retained open`
- self-issued authority: `false`

## Drift paths

- `codex-rs/Cargo.lock`
- `codex-rs/agent-graph-store/Cargo.toml`
- `codex-rs/app-server-protocol/Cargo.toml`
- `codex-rs/app-server-transport/Cargo.toml`
- `codex-rs/app-server/Cargo.toml`
- `codex-rs/codex-mcp/Cargo.toml`
- `codex-rs/core/Cargo.toml`
- `codex-rs/ext/hepta-memory/Cargo.toml`
- `codex-rs/external-agent-migration/Cargo.toml`
- `codex-rs/hepta-cognitive-read/src/authoritative_tests.rs`
- `codex-rs/hepta-cognitive-store/src/v2.rs`
- `codex-rs/hepta-cognitive-store/src/v2_tests.rs`
- `codex-rs/hepta-cognitive-types/src/lane_c.rs`
- `codex-rs/hepta-compact-engine/src/qualified.rs`
- `codex-rs/hepta-compact-engine/src/qualified_tests.rs`
- `codex-rs/hepta-context-compiler/src/v2.rs`
- `codex-rs/hepta-context-compiler/src/v2_tests.rs`
- `codex-rs/hepta-kg/src/generation.rs`
- `codex-rs/hepta-kg/src/generation_tests.rs`
- `codex-rs/hepta-memory-federation/src/v2.rs`
- `codex-rs/hepta-memory-federation/src/v2_tests.rs`
- `codex-rs/hepta-memory-retrieval/src/generation_bound.rs`
- `codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs`
- `codex-rs/hepta-ndu/src/error.rs`
- `codex-rs/hepta-ndu/src/evaluator.rs`
- `codex-rs/hepta-objective/src/compiler.rs`
- `codex-rs/hepta-objective/src/error.rs`
- `codex-rs/hepta-prompt-registry/src/v2.rs`
- `codex-rs/hepta-prompt-registry/src/v2_tests.rs`
- `codex-rs/mcp-server/Cargo.toml`
- `codex-rs/model-provider/Cargo.toml`
- `codex-rs/state/Cargo.toml`
- `codex-rs/tui/Cargo.toml`
- `qualification/module-execution-dossiers/NATIVE_BINDINGS.json`

## Authority ceiling

This seal proves only repository-internal fixed-point convergence over the bound source surfaces and receipts. It does not self-certify independent semantic review, runtime/model identity, future-time validity, target-host/hardware qualification, remote-owner consent, operator acceptance, production canary, selection, promotion, release, provider dispatch, model invocation, or an additional production writer.

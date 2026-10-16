# Hepta Neuron / Matrix P0 combined source identity (DRAFT)

This is a **non-authorizing** source-integration candidate, not evidence of a production-ready inference system. The candidate deliberately keeps the existing combined Draft PR #1507 and its own YAML parser qualification fixtures.

## Verified source parents

- Previous paired integration source: `91a20ee74833c484f3a400e675be0a74486a5bac` (Draft #1507).
- Matrix security source: `11c9c8f55774a2bd21315f4af6a4589887c8ac7d` (Draft #1372).
- Neuron shared-feature/worker source: `96f290ca1e3eade759d5c20e0433c62c2311c878` (Draft #1498).
- Common historical comparison base: `78fdb0cf8537e3a84fc6e0a849707559c80881e8`. The live `main` ref must be independently reverified by CI; it is not pinned to this historical event base.

The new commit's ordered parent list and exact tree SHA, not branch names, are the immutable source identity. The candidate is not promoted merely because a parent had a passing workflow.

## Tree reconciliation

Git blob comparisons against the common base identified 24 Neuron-only file changes and 22 non-identical overlapping paths. Identical changes already present in the Matrix tree need no second copy. All 24 Neuron-only files are carried over unchanged, including the Arc-backed immutable `SharedFeatureIdentityV2`/shared-feature cache, bounded CPU gated Head, Worker batch APIs, negative tests, and exact-source CI triggers. The security branch's file tree is the starting point.

For the 22 overlapping paths, preserve:
- Matrix security authority for `codex-rs/Cargo.lock` and its **Matrix SDK 0.19.1 / anymap3 / patched SQLx-SQLite** resolution; do not restore Matrix 0.18 or `anymap2`, ignore security advisories, or change signing authority.
- Matrix secure variants for `defs.bzl`, `exec-server/src/local_file_system.rs`, `ext/hepta-memory/src/cognitive/federation.rs`, `git-utils/src/git_process_tests.rs`, `hepta-evidence/src/authbus_outbox_tests.rs`, `hepta-fleet/src/registry_tests.rs`, `hepta-memory/src/cognitive_schema_tests.rs`, `hepta-memory/src/production_writer.rs`, `hepta-supervisor/src/tick.rs`, `hepta-supervisor/tests/restart_budget_recovery.rs`, `windows-sandbox-rs/tests/helper_manifest.rs`, and the CLI Doctor snapshot. These are 13 retained paths, not claims of a clean full CI.
- Reconciled source blobs for nine remaining paths: `codex-rs/Cargo.toml`, `codex-rs/cli/Cargo.toml`, `.github/workflows/rust-ci.yml`, `.github/workflows/v8-canary.yml`, `.github/scripts/test_run_bazel_ci.py`, `codex-rs/hepta-agentd/src/control.rs`, `codex-rs/hepta-matrixd/src/control.rs`, `codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs`, and `codex-rs/hepta-operator-acceptance/src/durable.rs`. Preserve the secure dependency graph and independent final-use ordering while retaining Neuron's actual E2E streaming fixture, CLI recursion root, canonical UDS preflight checks and specific macOS CI race regressions. The Neuron Windows durable helper retains its parent-module alias, imported into the secure Matrix writer without reverting sidecar durability.

The existing paired-branch-only YAML security workflow and its two input tests are retained. None of the retained or combined test fixtures authorizes model execution.

## Fail-closed release gates

1. **P0:** exact combined-head `cargo --locked` check, regression tests, strict Clippy, rustfmt, Windows-native tests, Matrix `cargo-deny` **without advisory ignores**, crypto/SQLite WAL migration, source/base architecture checks, and every global blocking-ci job, including Bazel Windows release/test/lint. A skipped/queued/cancelled check is not a pass. Any integration conflict, resolver drift, test failure, or unverified operation must keep this PR Draft.
2. **P1:** real pinned Laya/ModernBERT weights+tokenizer, joint question/options input, physically shared encoder execution and immutable Feature Snapshot correctness on real held-out inputs.
3. **P2:** independently verified model Artifact CAS bytes, signed load receipt, trusted Final-use grant at every V2 physical dispatch, generation/epoch/fence and durable recovery; currently V2 is crate-private and `DENY_ALL`.
4. **P3:** frozen no-change baseline, independent evaluator and selector, real future/OOD windows, negative-transfer accounting and signed NDU acceptance evidence.
5. **P4:** measured 64/256/1024/4096 Cell CPU/RSS/GPU, throughput, p95/p99, WAL replay and crash/restart on the target host. The scalar Q24 Head adapter is not a GPU fusion or OS RSS benchmark.

**No production merge, release, signing-key issuance, physical Cell split or model promotion is authorized.** A source tree/commit is not a runtime receipt.

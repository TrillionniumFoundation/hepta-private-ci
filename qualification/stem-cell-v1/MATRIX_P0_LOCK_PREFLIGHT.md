# Matrix SDK P0 dependency preflight (research-only)

**Branch:** `research/matrix-sdk-p0-preflight-20261012` (forked from Hepta PR #1495 at `d6def139c5c449d0f71b06d87de62690157827a8`). This separate branch does **not** mutate the source SHA currently undergoing CI in PR #1495.

This preflight is a **read-only lockfile diagnostic**, not a remediation, not a replacement for `cargo-deny`, not a versioned upstream fork audit and not a production authorization. Its report always sets `cargo_deny_passed=false` and `production_authorized=false`, including when its modeled advisory conditions are absent.

## Run against the actual checked-in lock and toolchain

```sh
python3 -m unittest discover -v -s qualification/stem-cell-v1 -p 'test_matrix_security_preflight.py'
python3 qualification/stem-cell-v1/matrix_security_preflight.py \
  --lock codex-rs/Cargo.lock \
  --toolchain codex-rs/rust-toolchain.toml \
  --output /tmp/hepta-matrix-lock-preflight-$(git rev-parse --short HEAD).json \
  --enforce
```

Exit code 2 is **expected on the current vulnerable SDK graph**, and must not be ignored to claim P0 success. Output files are create-only, so reruns must use distinct paths. For actual promotion the independent Cargo-deny, Rust, Bazel, Matrix E2EE and SQLite recovery gates still must pass on the exact frozen SHA.

## Verified blocker baseline

- The current lock resolves `matrix-sdk 0.18.0`, `matrix-sdk-crypto 0.18.0` and `anymap2 0.13.0`.
- `RUSTSEC-2026-0318`: Matrix crypto before 0.19.0 has the to-device IdentityBasedStrategy panic issue.
- `RUSTSEC-2026-0319`: `anymap2` is unmaintained. Upstream `matrix-sdk 0.19.1` still directly imports it, so an SDK-only upgrade does not clear this advisory.
- Published Matrix 0.19.0 / 0.19.1 require Rust 1.96; Hepta currently pins 1.95.
- The repository carries a local Matrix SQLite 0.18.0 patch to align native SQLite ownership. Review binary/ABI, durable WAL, encryption and store-migration behavior, not only Cargo dependency resolution.
- Cargo-deny on [exact original PR SHA, run 38197306303](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38197306303), job `114644503856`, **failed** on the two RUSTSEC findings; yanked `chacha20 0.10.0` and `spin 0.9.8` also need independent treatment.

## Required release gates (no waivers)

1. Select a reviewed, version-pinned SDK **family** that includes fixed crypto and removes unmaintained anymap2 through an audited maintained replacement.
2. Reconcile Hepta Matrix E2EE, sync, to-device and SQLite/WAL/restart APIs; run real recipient-without-cross-signing and migration regressions.
3. Update `rust-toolchain.toml` only after scoped reproducible Rust/Bazel checks, then regenerate both `Cargo.lock` and `MODULE.bazel.lock`.
4. Require `cargo tree --locked -i anymap2` to prove no remaining users and `cargo tree --locked -i matrix-sdk-crypto` to bind the secure version.
5. Run unchanged `cargo deny check --locked`, native Matrix tests, strict cross-platform Bazel and the complete `blocking-ci` on **one exact final SHA**.
6. Keep Stem/Cell in Draft/Shadow until signed CAS/final-use/Generation Fence, real weights, target-host resources and independent NDU are also established.

**Never** silence advisories, prune the feature graph, disable encryption, substitute fake crate metadata or treat this diagnostic's `blocked=false` as a cargo-deny/production pass.

# P0 global cargo-deny: Matrix dependency security blocker

Status: **OPEN, fail closed**. This is not a Stem experiment waiver.

## Verified actual CI at SHA 73dad71b502d976f442113794b32adf2fbef1eb5

- [Stem L1 38190012627](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38190012627): all 7 jobs passed (L1 only).
- [Global blocking CI 38190012730](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38190012730): `cargo-deny` **failed**. Job 114622236685 records:
  - RUSTSEC-2026-0319: unmaintained `anymap2 0.13.0` pulled by `matrix-sdk 0.18.0`; no safe in-place upgrade.
  - RUSTSEC-2026-0318: vulnerable `matrix-sdk-crypto 0.18.0`, patched in `>=0.19.0`.
  - Yanked `chacha20 0.10.0` via `rand 0.10.1` is separately flagged as a warning.
- **No advisory ignore, feature disable, dependency pruning, or fake green gate is permitted.**

## Upstream version trap

As checked October 12, 2026, the official `matrix-sdk 0.19.0` and `0.19.1` still directly declare `anymap2 ^0.13.0` (see https://docs.rs/crate/matrix-sdk/0.19.0 and https://docs.rs/crate/matrix-sdk/latest/source/Cargo.toml). Therefore simply changing from 0.18 to 0.19 resolves **0318** but leaves **0319** in the dependency graph. Avoid unreviewed blanket upgrades.

The `codex-rs/Cargo.toml` workspace pins `matrix-sdk 0.18.0` with E2EE/SQLite and carries a local `matrix-sdk-sqlite 0.18.0` patch to align `libsqlite3-sys` native `links` ownership with SQLx/WAL. This is a real storage compatibility constraint.

## Required engineering and evidence sequence

1. Freeze the Matrix 0.18 baseline and inventory API consumers, encrypted messaging, migrations and SQLite durability.
2. Adopt an upstream or reviewed pinned Matrix revision that **both** contains the `matrix-sdk-crypto >=0.19.0` security fix **and** removes `anymap2` (migrate to maintained `anymap3` where appropriate); review a fork as a supply-chain artifact if upstream has no suitable published release.
3. Resolve native SQLite links/version compatibility. Exercise real upgrade, WAL recovery and E2EE cases without disabling either safeguard.
4. Regenerate `Cargo.lock` and `MODULE.bazel.lock` using repository tooling; include manifest and complete source provenance. Do not manually invent checksums.
5. Pass `cargo check --locked`, Matrix integration tests, `cargo-deny`, Strict Clippy, full cross-platform Bazel/CI and Rust formatting on the **exact final SHA**.

**Release gate:** Remain Draft/Shadow. Stem L2 real weights, L3 64–4096 target-host resource/recovery, and L4 independently observed NDU/future-window evidence also remain unqualified.

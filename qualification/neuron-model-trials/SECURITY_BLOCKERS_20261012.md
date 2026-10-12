# Matrix security dependency blockers — 2026-10-12

This is a **WIP-only** dependency admission note, not a remediation or CI waiver.

## Reproduced on experimental SHA

PR #1494 commit `a1cc44d52442597eb4653434fc7ac652768feef2`,
global `blocking-ci` run 38201146104, cargo-deny job 114656645739:

- `RUSTSEC-2026-0318`: vulnerable `matrix-sdk-crypto 0.18.0`. The upstream
  fix begins with `matrix-sdk-crypto >= 0.19.0`.
- `RUSTSEC-2026-0319`: `anymap2 0.13.0` unmaintained, pulled through
  `matrix-sdk 0.18.0` into `codex-hepta-matrix-sdk` and `matrixd`.
  There is **no patched anymap2 release**.

The upstream `matrix-sdk 0.19.1` still depends on `anymap2 ^0.13.0`
and requires Rust **1.96**, while this workspace pins `1.95.0`
(`codex-rs/rust-toolchain.toml`). It is therefore NOT a drop-in full fix.
The Matrix SDK storage must also be checked against this workspace's SQLx
and `libsqlite3-sys 0.37` SQLite/WAL corruption fix, as well as existing
persistent `matrix-sdk-0.18` directory migrations.

## Strict next acceptance path

1. Investigate a maintained Matrix SDK release/fork that removes anymap2 and
   includes the crypto fix. Verify actual publisher, changes, review and
   signed source artifact. **Never silently replace with a random fork.**
2. Test all API, E2EE, sync, outbox, crash/recovery and state-directory
   compatibility in a separately proposed upgrade branch with matching pinned
   Rust toolchain and lockfile.
3. Prove no SQLite native-link conflict and no rollback of the WAL-reset
   corruption fix on Linux, Windows and macOS.
4. Run `cargo deny check advisories bans licenses sources` and full
   `blocking-ci` on one final SHA, without adding RUSTSEC ignores or pruning
   the vulnerable Matrix dependency from the graph.
5. Only then consider merging. This diagnosis grants no production deployment
   or model-promotion authority.

Sources:
- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://docs.rs/crate/matrix-sdk/0.19.1/source/Cargo.toml
- https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38201146104

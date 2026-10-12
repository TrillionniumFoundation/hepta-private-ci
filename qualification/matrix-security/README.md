# Matrix SDK P0 security migration: fail-closed prerequisites

This is **not a remediation** of the open Cargo advisory failures; it is a
read-only guard against false remediation. It does not grant production access,
ignore advisories, reduce `cargo-deny` coverage, disable end-to-end encryption,
remove Matrix support, or change a trust root. The existing global `cargo-deny`
remains a separate mandatory failure until the actual dependency graph is safe.

## Confirmed evidence on the 2026-10-12 research HEAD

- `codex-rs/Cargo.toml` pins `matrix-sdk 0.18.0` with **both** `e2e-encryption`
  and `sqlite` features. The exact `Cargo.lock` graph includes
  `codex-hepta-matrixd -> codex-hepta-matrix-sdk -> matrix-sdk -> anymap2 0.13.0`.
- `matrix-sdk-crypto 0.18.0` is loaded through `matrix-sdk-base` and
  `matrix-sdk-sqlite`. RustSec **RUSTSEC-2026-0318** is fixed in crypto **0.19.0**
  and later: <https://rustsec.org/advisories/RUSTSEC-2026-0318.html>.
- RustSec **RUSTSEC-2026-0319** marks `anymap2` as unmaintained, recommending
  `anymap3`: <https://rustsec.org/advisories/RUSTSEC-2026-0319.html>.
  Matrix SDK **0.19.1** still lists `anymap2` as a direct dependency, so **a
  version bump alone cannot remove the advisory**:
  <https://docs.rs/crate/matrix-sdk/0.19.1/source/Cargo.toml>.
- Matrix SDK **0.19.1** declares `rust-version = "1.96"`, while Hepta's
  `codex-rs/rust-toolchain.toml` currently pins `1.95.0`.
- Hepta's 0.18 SQLite adapter is locally patched to use `rusqlite 0.39`
  and the `libsqlite3-sys 0.37` WAL-reset fix, so changing the upstream
  `matrix-sdk-sqlite` release also requires a **new actual storage migration**.

### Remaining safe implementation path

1. Freeze actual upstream 0.19.x source and versions. Migrate Rust toolchain
   coherently across Windows/macOS/Linux and strict Clippy/format checks.
2. Replace Matrix SDK's use of `anymap2` with an independently reviewed and
   reproducibly pinned `anymap3` migration **in source**, or consume a future
   upstream SDK release that no longer depends on `anymap2`. Merely patching the
   package name while retaining unmaintained code is not a fix.
3. Upgrade the **entire Matrix SDK family** (SDK/base/crypto/SQLite and related
   dependencies), removing vulnerable crypto 0.18; update the SQLite compatibility
   patch with real libsqlite3 linking and WAL crash/restart verification.
4. Retain SDK session-key, E2EE decryption/encryption, scope isolation,
   homeserver restart, checkpoint replay, durable outbox, to-device messages,
   verification missing cross-signing keys, and full `real_synapse_e2e` tests.
5. Run `cargo update`/`--locked`, refresh `MODULE.bazel.lock`, and get **new
   exact-SHA** Rust, Bazel, cargo-deny, cross-platform and E2EE receipts before
   removing the Matrix P0 blocker. Keep P1–P4 production admission closed.

### Usage

```
python3 qualification/matrix-security/matrix_dependency_gate.py --root . --output /tmp/matrix-p0-report.json
python3 qualification/matrix-security/matrix_dependency_gate.py --root . --require-safe
python3 -m unittest discover -v -s qualification/matrix-security -p 'test_*.py'
```

`--require-safe` deliberately exits nonzero on the current lockfile. Even when
static prerequisites eventually pass, the resulting report will continue to set
`cargo_deny_verified=false`, `matrix_e2ee_verified=false`,
`sqlite_wal_recovery_verified=false`, and `production_authorized=false`;
independently signed runtime/CI evidence must establish those claims.

## Pinned upstream compatibility candidate (separate from released 0.19.1)

A read-only review of the **Git source** at commit
`b3c07ea6ba6e8e46e30811c0500b04505c4be9f9` shows:

- `matrix-sdk` source still advertises `0.19.1`, but now uses `anymap3` instead
  of `anymap2`. This is a **pinned, not-yet-qualified Git tree**, not a claim
  that crates.io `matrix-sdk 0.19.1` has changed. No source is executed.
- `matrix-sdk-crypto` source is `0.19.1` and the upstream workspace requires
  Rust `1.96`. The SQLite crate uses `rusqlite 0.40.2`, which itself depends on
  `libsqlite3-sys 0.38.2`; Hepta still pins `0.37` via its SQLx 0.9 family.
- The distinct `upstream_source_probe.py` checks exact Git SHA, no `anymap2`,
  crypto version, MSRV and SQLite versions against local Hepta bindings. Its
  status remains `migration_ready=false` even if all upstream manifests pass.
- Do not patch Cargo.lock to point to this Git source without separate
  source-review, reproducible dependency resolution, SQLite `links` alignment,
  native compile, E2EE conformance and actual WAL recovery evidence.
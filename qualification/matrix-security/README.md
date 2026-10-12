# Matrix SDK 0.19.1 migration feasibility — non-authorizing

**Scope:** The separate Matrix SDK security blockers in global `cargo-deny` for Hepta's pinned `matrix-sdk = 0.18.0` dependency. This is **not** a way to bypass `cargo-deny` or a production change.

**Frozen input:** The exact Git commit checked out by the associated GitHub Actions run. The runner uses a detached temporary Git worktree; it never edits `codex-rs/Cargo.toml`, `Cargo.lock`, `deny.toml` or any source in the tested checkout.

## Verified blockers

- `RUSTSEC-2026-0318` impacts `matrix-sdk-crypto` versions below 0.19.0. Matrix SDK 0.19.1 is a candidate for this fix, but it must be tested with the Hepta integration and encrypted persistence.
- `RUSTSEC-2026-0319` marks `anymap2` unmaintained, and the published `matrix-sdk 0.19.1` manifest **still directly depends on `anymap2 0.13`**. A version-only upgrade is insufficient. Remove that package from the actual resolved dependency graph through a reviewed upstream fix/fork and test the replacement.
- `matrix-sdk 0.19.1` contains components that require at least Rust 1.96. The Hepta workspace currently pins 1.95.0; the research job uses a temporary 1.96.1 toolchain without changing the main project toolchain.
- The pinned Matrix SDK 0.18 SQLite store has a deliberate local `rusqlite` / `libsqlite3-sys` compatibility patch. Any upgrade requires a verified SQLite owner/migration, lockfile, Windows/Linux/macOS and real Synapse conformance story.

## Acceptance contract

The independent preflight records baseline and candidate lockfile evidence, actual Cargo resolution/compile/test exit results, residual `anymap2` paths and an exact proposal diff. The `security_ready` field covers **only these two advisories and the tested Matrix Owner commands** and is never sufficient for production. Its consumer must separately require full cargo-deny, consistent Rust toolchains, native Matrix/Synapse tests and the existing Hepta release gate.

No changes to `deny.toml` advisory exclusions, no `cargo-deny` warning downgrade, no fake synthetic performance, and no implicit production activation are permitted. An evidence-producing research workflow may complete successfully while the **release disposition remains BLOCKED**.

## Source references

- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://docs.rs/crate/matrix-sdk/0.19.1/source/Cargo.toml
- https://docs.rs/crate/matrix-sdk-store-encryption/0.19.1/source/Cargo.toml

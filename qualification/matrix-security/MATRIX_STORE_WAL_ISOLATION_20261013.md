# Matrix SQLite owner dependency isolation — 2026-10-13

**Status: research candidate; P0 production cargo-deny remains BLOCKED.**
Source branch: `research/stem-cell-three-experiments-20261011`, draft PR #1495.
Do not treat a narrow Cargo graph as a signed Matrixd acceptance or a production release.

## Causal diagnosis from real GitHub Actions

Historical [narrow SDK run 38333560563](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38333560563)
reported this exact dependency conflict:

```text
matrix-sdk-store-encryption 0.19.1 -> blake3 ^1.8.7
hepta-matrix-sdk -> hepta-matrix-store -> codex-state
  -> codex-protocol -> codex-execpolicy -> starlark 0.14.2
  -> blake3 =1.8.2
```

Hepta's `hepta-matrix-store/src/store.rs` depended on `codex-state` at
**only one runtime call site**, `SqliteConfig::open_durable_evidence_pool`.
That call did not require any Codex state, protocol or executable services.

## Actual source change

The Matrix durable store now opens its own audited SQLx connection using the
exact original evidence options:

| Setting | Former `codex-state::SqliteConfig` | Matrix owner candidate |
| --- | --- | --- |
| Filename | `matrix_1.sqlite3` | unchanged |
| Create file | `create_if_missing(true)` | unchanged |
| WAL | `journal_mode(Wal)` | unchanged |
| Durability | `synchronous(Full)` | unchanged |
| Referential integrity | `foreign_keys(true)` | unchanged |
| Lock wait | 5 seconds | unchanged |
| Pool cap | 5 connections | unchanged |
| SQL statement logging | off | off, including slow statements |
| SQLite WAL-reset guard | `libsqlite3_sys::SQLITE_VERSION_NUMBER >= 3_051_003` | same compiled guard |
| Schema and migrations | Matrix-owned, create-only migrations | unchanged |
| Agent binding, permissions, outbox replay | Matrix-owned | unchanged |

This is a narrowly scoped exception to the workspace's centralized SQLx
connection lint, explicitly annotated at the only permitted Matrix owner
connection constructor and read-only qualification fixtures. It is **not**
an advisory ignore, authentication bypass, SQLite feature disable, data
migration, or an alternate sqlite database.

Additional runtime checks query WAL, synchronous=FULL, foreign_keys=ON, and
busy_timeout=5000 on an **actual acquired owner pool connection** before
migrations. On mismatch, initialization fails closed. A read-only readiness
method allows checking the same invariant after reopening.

The `hepta-matrix-store` Cargo manifest/lock no longer directly binds
`codex-state` or `codex-utils-absolute-path`, and now directly binds
the existing workspace-pinned `libsqlite3-sys 0.37` to preserve the SQLite
version assertion.

## Independent evidence still required

1. Locked product-toolchain `cargo check`, Rust tests `durable_core`,
   `sync_observation_v1`, `sync_mutation_v2`, and new
   `sqlite_profile_contract` must **actually pass**.
2. Strict Clippy with scoped, documented disallowed-method exceptions,
   global `imports_granularity=Item` Rustfmt, Bazel lock and full CI must pass.
3. The **disposable** pinned Matrix 0.19.1 + AnyMap3 narrow SDK resolver must
   prove `blake3 >=1.8.7`, no `starlark`, `codex-state`,
   `codex-execpolicy` or `anymap2`. Even such success does **not** mean
   full product workspace resolution or cargo-deny success.
4. A separate real SQLite `rusqlite` / `libsqlite3-sys` links alignment,
   0.19 Matrix E2EE, to-device missing-cross-signing-keys regression,
   encrypted state, WAL crash and replay, and Windows/macOS/Linux suites
   must pass on an exact frozen SHA.
5. **Production** `matrix-sdk 0.18.0` and `matrix-sdk-crypto 0.18.0`
   remain in the canonical lock. `RUSTSEC-2026-0318` (crypto) and
   `RUSTSEC-2026-0319` (anymap2) remain OPEN. Do not weaken `deny.toml`,
   change this diagnosis to a pass, or activate/release anything based on
   this refactor alone.

P1 real selected CAS/Final-use/WAL recovery, P2 fixed audited model weights,
P3 target-host Cell stress and P4 independent future NDU/negative-transfer
are separately unfulfilled gates.

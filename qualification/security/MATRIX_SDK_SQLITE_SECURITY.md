# Matrix SDK 0.19 Security/SQLite ABI Upgrade — Shadow-Only Blocker

This branch attempts to resolve RUSTSEC-2026-0318 by upgrading
`matrix-sdk` from 0.18.0 to 0.19.0 with real Cargo 1.95; it does **not**
authorize release, change a production route, rewrite a SQLite ledger, or
add a `cargo-deny` waiver.

## Actual Cargo resolution receipt

GitHub Actions run
[38423631690](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423631690)
reached `cargo +1.95.0 update -p matrix-sdk --precise 0.19.0`
but failed to resolve because:

- `matrix-sdk v0.19.0` includes `matrix-sdk-sqlite v0.19.0`, with
  `rusqlite ^0.40.2` and `libsqlite3-sys ^0.38.2`.
- `codex-state` currently requires `libsqlite3-sys ^0.37`.
- `sqlx-sqlite 0.9.0` supports `libsqlite3-sys >=0.30.1, <0.38.0`.

Rust/Cargo's `links = "sqlite3"` rule permits only one SQLite linker
package per full workspace dependency graph. Merely changing the direct
`libsqlite3-sys` version cannot satisfy SQLx 0.9.0 and Matrix SDK 0.19.0
simultaneously.

## Invariants that cannot be sacrificed

`codex-hepta-matrix-sdk::MatrixSdkClient::build` calls
`sqlite_store_with_cache_path` to persist Matrix SDK session and crypto state,
and `sync_durable_once` uses the Hepta authoritative inbox cursor.
Dropping the `sqlite` feature, silently resetting the `matrix-sdk-0.18`
store directory or relying on an in-memory E2E store is not an acceptable
production remediation. The additional offline guard checks these facts.

No patch to SQLx's declared SQLite dependency upper bound is safe without a
maintained fork, reviewed ABI compatibility, all Owner integration tests and
fault-injected restore testing. Alternatively, a separately locked,
process-isolated Matrix sidecar would require an explicit stable, authenticated
IPC and durable lifecycle/restart protocol. Both are real engineering changes.

## Remaining independent advisories

`anymap2 0.13.0` is unmaintained (RUSTSEC-2026-0319), potentially resolved
by the same Matrix family upgrade, subject to a new Cargo audit.
`unsafe-libyaml 0.2.11` (RUSTSEC-2024-0449) is a separate legacy
`serde_yaml` migration and is NOT fixed by upgrading Matrix.

## Required sequence

1. Choose and verify one **compatible** SQLite dependency and persistence
   route; do not relax the SQLx upper bound based on untested guesses.
2. Regenerate Cargo.lock with real Cargo, preserve exact crate checksums.
3. Pass Matrix Owner compilation, recovery and compatibility tests,
   full `cargo-deny` (no ignore), all-target Clippy and cross-platform CI.
4. Record actual migration and state replay, generation fence, old-db
   compatibility and rollback receipts.
5. Only then merge through the normal production CI and authorization owners.

This branch is currently intentionally not deployable: its Cargo.toml
requires 0.19.0, but Cargo.lock has not been upgraded because resolution
**failed**. Do not represent its saved artifact or manifest as approved.

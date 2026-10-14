# Matrix SDK security remediation — isolated candidate, not an exception

## 2026-10-14 originating CI evidence

PR #1452's exact-head `blocking-ci` run
[38493138286](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38493138286),
`cargo-deny` job `115623338724`, failed because:

| Advisory | Dependency and observed version | Required disposition |
| --- | --- | --- |
| RUSTSEC-2026-0318 | `matrix-sdk-crypto 0.18.0` via `matrix-sdk 0.18.0` | Upgrade affected SDK graph to a security-patched version (advisory calls for `>=0.19.0`), then test actual device-encryption behaviour |
| RUSTSEC-2026-0319 | `anymap2 0.13.0` transitively from Matrix SDK | Migrate off the unmaintained package; do not relabel it as safe |
| RUSTSEC-2024-0449 | `unsafe-libyaml 0.2.11` via `serde_yaml` in `codex-core-plugins` | Replace the parser dependency with a maintained implementation, inspect the YAML contract and verify all callers |

These are **not** harmless lint warnings. Never silence them in
`codex-rs/deny.toml`, skip `cargo-deny`, alter `blocking-ci`, or treat
a different model's task result as a production dependency acceptance.

## Reproducible research-only Matrix SDK 0.19 candidate

`.github/workflows/hepta-memory-matrix-sdk-security-probe.yml` creates
a disposable, permission-read-only GitHub Actions checkout, pins its exact
commit/tree and unchanged source Cargo files, and applies *only to that
checkout* the following compatibility attempt:

1. Upgrade the workspace `matrix-sdk` dependency from `0.18.0` to
   `0.19.0`; temporarily remove the 0.18-specific vendor override for
   `matrix-sdk-sqlite` in the **throwaway runner checkout**.
2. Run a genuine Cargo resolver update and `cargo check` for both
   `codex-hepta-matrix-sdk` and `codex-hepta-matrixd`. These may fail
   due to actual API or SQLite `links` conflicts.
3. Run the unchanged RustSec-driven `cargo-deny` on the candidate, not a
   weakened policy. Retain the exact dependency graph, resolver output,
   compilation errors, source snapshot, Cargo diff and SHA-256 manifest.

The small read-only `matrix_sdk_security_probe.py` separately checks
that no protected Matrix SDK component was simply deleted or downgraded
to make an advisory vanish. It accounts for three known failing advisories,
but **absence of these three is not a full security audit**.

No candidate Cargo manifest/lock or rebuilt binary from this workflow is
submitted as a production fix. Apply a candidate to PR #1452 only after it
actually resolves, compiles, passes RustSec, preserves code and test
behaviour and receives the appropriate maintainer review. Replacing
`unsafe-libyaml` is independent of the Matrix SDK version migration.

**Current status:** research setup, not an executed/verified upgrade.
Original `blocking-ci` remains mandatory; production acceptance remains
false. This is unrelated to, and does not substitute for, independent
MemoryCell task, citation and future-window evidence.

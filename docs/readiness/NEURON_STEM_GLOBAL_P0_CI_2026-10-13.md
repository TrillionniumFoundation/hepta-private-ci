# Hepta global CI qualification, 2026-10-13

**Status:** blocking; source audit only, not a production-release receipt.
Applies to the stacked research PRs #1499 (Jina v5), #1510 (native Stem
Worker) and #1517 (single-use signed final-use). The three relevant
specialized PR #1517 checks `Hepta Stem-Head Worker Bridge`,
`Hepta Neuron Stem` and `Hepta architecture convergence` succeeded on
exact SHA `7c25de01f63e0dcd618f0bd2f37f3a66e237647e`, but
[global blocking-ci 38339726827](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38339726827)
failed. An older green run is not evidence for a newer SHA.

## Native code and formatting

- The failing whole-repository formatter was
  `uv run --frozen --project scripts ruff format --check scripts .github`,
  reporting *one file*: `.github/scripts/test_run_bazel_ci.py`.
  This branch formats the relevant recently added macOS Bazel cache test,
  retaining all cache safety and Windows argument assertions.
  The passing Rust format job is not an alternative to the missing Python
  formatter receipt.
- Cross-platform native Hepta checks passed on Linux, macOS and Windows in
  that run. This does **not** imply Bazel whole-repository Windows tests passed.

## Cargo-deny dependency security

**Do not add any `advisories.ignore` entries.** The log confirms:

| Advisory | Dependency and owner path | Required intervention |
| --- | --- | --- |
| RUSTSEC-2026-0318 | `matrix-sdk-crypto 0.18.0` via `matrix-sdk 0.18.0`, `codex-hepta-matrix-sdk`, `codex-hepta-matrixd` | Upgrade compatible Matrix SDK family to 0.19.0 or later, matching full Cargo.lock and vendored SQLite interface, and run real Matrix integration/crypto tests |
| RUSTSEC-2026-0319 | `anymap2 0.13.0` via Matrix SDK 0.18 | Upgrade the SDK and verify `anymap2` is absent; an in-place anymap replacement in only one dependent crate is not sufficient |
| RUSTSEC-2024-0449 | `unsafe-libyaml 0.2.11` via deprecated `serde_yaml` and `codex-core-plugins` | Replace the consumer/parser with a supported safe-Rust implementation, test roundtrip/ambiguous-input policy, remove the dependency from lockfile |

The workspace currently pins `matrix-sdk = "0.18.0"` and contains a
vendored `third_party/matrix-sdk-sqlite-0.18.0` patch to control its
`rusqlite` constraint. **Do not edit only the version string**: the patched
SQLite crate and all Matrix APIs must be migrated in one compatibility-tested
change. Run `cargo tree -i matrix-sdk-crypto`, `cargo tree -i anymap2`
and `cargo tree -i unsafe-libyaml`, then `cargo deny check advisories`
on the exact native Cargo.lock. Keep `cargo test --locked` and Bazel
lock/Bzlmod regeneration part of acceptance.

## Windows Bazel product gates

These are independently blocking, not shadow Stem benchmark results:

- Windows shard 1 observed `git_process` timeout child cleanup failures
  and `hepta-supervisor` restart-budget recovery assertion failure.
- Windows shard 2 observed `hepta-intelligence` evaluated-shadow and
  segmented ledger recovery failures due to native Windows
  `ERROR_LOCK_VIOLATION` / `ERROR_ACCESS_DENIED` when re-opening or
  reading locked files. Repair fixture handle/ownership/recovery ordering,
  not the production durability assertions.
- Windows shard 3 observed signed-intent recovery and additional
  compilation/contract failures; reproduce with the exact failing Windows
  Bazel shards and inspect the first root error, not subsequent cascade
  diagnostics.
- Reproduce on Windows with the repo's actual Bazel/host-compiler flags
  and clean generated-artifact tree. Do not `#[ignore]`, skip Windows
  shards, or weaken signed failure/recovery checks.

## Acceptance dependencies

1. Python `ruff format --check` passes on final source.
2. All three reported cargo-deny advisories eliminated by an actually
   resolved dependency graph; no warning ignores.
3. Native target-owner Rust tests, `cargo fmt`, Strict Clippy and Bzlmod
   lock all pass on one combined SHA.
4. Windows Bazel test shards and release-build/clippy matrix pass on the
   exact same merged tree.
5. Independent model CAS/load, signed final-use, generation fence,
   WAL/unclean-crash recovery, frozen/no-change/future-NDU and real
   64/256/1024/4096-Cell target-host throughput still require separate
   product receipts.

No CI source patch in this file provides release authorization. Continue
to retain existing production routing and fail closed.

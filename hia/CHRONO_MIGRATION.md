# Chrono retirement: source-only dependency inventory

**Pinned review target:** `bbb534d8be9098c041d5f3dd1ca1214fbcc2fd8a` on `codex/hia-union29-20261116-a90d`.

**Blocking advisory:** [RUSTSEC-2026-0543](https://rustsec.org/advisories/RUSTSEC-2026-0543.html), issued 2026-11-17, classifies all `chrono` versions as **unmaintained**; no patched release is listed. RustSec recommends `jiff` or `time`. This is an informational maintenance advisory, not evidence of an exploited vulnerability. Upgrading from `chrono 0.4.43` to another `chrono` release does not close it.

At the pinned `codex-rs/Cargo.lock` Git blob `e1fdaf3fde907d24fec7ea787d49c0e29b3eb4bd`, the resolved graph contains `chrono 0.4.43` and **36 immediate dependency edges**: **28 workspace-local packages, seven registry packages and one vendored third-party package**. The complete names and versions are recorded in `chrono_lock_baseline.json`. This counts lockfile edges, **not** independent runtime uses, executed code paths, or the number of public API changes.

The workspace itself pins `chrono = "0.4.43"` in `codex-rs/Cargo.toml` (Git blob `145c9b24e7203461337a68cf9938f9f0bce720a9`). External importers include `oauth2`, `rmcp`, `schemars`, `serde_with`, and the `sqlx-core/mysql/postgres/sqlite` family. `sqlx-sqlite 0.9.0` is patched from `third_party/sqlx-sqlite-0.9.0`; its missing registry source does not make it first-party. The `workspace_local` label is based on lockfile and patch provenance, not a standalone authorship proof. Replacing direct first-party imports alone cannot make a graph-wide cargo-deny check pass while external importers still depend on `chrono`.

## Executable inventory and closure condition

Run the standalone Python 3.11+ source scanner (it does not run Cargo, compile Rust, or fetch packages):

```bash
python -B hia/chrono_lock_audit.py codex-rs/Cargo.lock \
  --baseline hia/chrono_lock_baseline.json --fail-on-growth
python -B hia/chrono_lock_audit.py codex-rs/Cargo.lock --require-zero
```

The first command distinguishes retired/new immediate edges; **it does not replace cargo-deny or waive an advisory**. The second is intentionally unsuccessful until no `chrono` package and no direct importer remains. Only a fresh exact-tree Cargo/Bazel lock update, all relevant original tests, cargo-deny and multi-platform CI can qualify the migration. The original `deny.toml` and `.cargo/audit.toml` remain unchanged; do not add `RUSTSEC-2026-0543` to their ignore lists to label this blocker closed.

Practical order: migrate first-party date/time uses to a reviewed `jiff`/`time` representation while preserving time-zone, serialization, precision and historical timestamp behavior; separately trace the external dependency graph to identify upstream releases or actual feature changes eliminating `chrono`; finally regenerate both Cargo and Bazel locks under the pinned toolchain and run the original checks. Do not remove Rust/default dispatch, loosen tests, change security profiles, merge, or promote a release from this inventory.

This package provides **only static dependency analysis and seven synthetic unit tests**. It does not fix `RUSTSEC-2026-0543`, add a production HIA kernel, or prove entire Codex migration/retirement. All of those status gates remain false.

**November 18 audit correction:** v1 prose claimed 28/8, but its Python implementation actually classified vendored SQLx SQLite as a workspace dependency (29/7). v2 corrects the three-way classification using the pinned workspace manifest. This repairs the audit, not the RustSec/cargo-deny blocker. The historical v1 report remains preserved in Git history.

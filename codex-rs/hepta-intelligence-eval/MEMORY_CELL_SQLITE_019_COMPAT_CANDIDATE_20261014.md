# Matrix SDK 0.19 SQLite dependency compatibility experiment — 2026-10-14

**Not a production fix, not a dependency override in the PR branch, and not a cargo-deny exception.**

## Observed root cause

A security probe [38495562743](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38495562743) ran seven source-identity unit tests successfully, but the exact published Matrix SDK 0.19 dependency graph failed *Cargo resolution*, before compilation. The blocker was:

- Published `matrix-sdk-sqlite 0.19.0` requires `rusqlite 0.40.2`, which depends on `libsqlite3-sys ^0.38.2`.
- The existing Hepta `codex-state` and SQLx 0.9.0 dependency graph uses `libsqlite3-sys 0.37.0`; `rusqlite 0.39.0` currently links to that same system crate.
- Cargo forbids two versions of packages both providing the native `links="sqlite3"` library in one dependency graph.

The original local `third_party/matrix-sdk-sqlite-0.18.0` exists precisely because an earlier published Matrix SDK dependency graph had a similar native SQLite conflict. Do not assume that simply switching the Matrix SDK version preserves storage or encryption behaviour.

## Source-verified, ephemeral compatibility candidate

A new dedicated research workflow `.github/workflows/hepta-memory-matrix-sdk-019-sqlite-compat.yml` operates on a **disposable checkout only**:

1. Fetch the published `matrix-sdk-sqlite 0.19.0` Cargo package and independent publisher metadata over TLS. Verify package SHA-256 and reject path traversal, symlinks/hardlinks, duplicates, oversized archive content, unexpected package versions and ambiguous manifest edits.
2. Change exactly **one** dependency value in the temporary extracted upstream manifest: `rusqlite 0.40.2` to `0.39.0`. This is a *compatibility experiment*, not a semantically approved fork.
3. Pin the disposable workspace to `matrix-sdk =0.19.0` and the source-verified temporary `matrix-sdk-sqlite 0.19.0`, then run real Cargo dependency resolution and compile the production code owners `codex-hepta-matrix-sdk` and `codex-hepta-matrixd`.
4. Only after a clean dependency resolver and compilation, execute **unchanged cargo-deny**, retaining any remaining advisories. Preserve original and candidate lock files, patched manifest, compiler errors, exact source, original registry metadata, original crate SHA, and all bytes in a SHA-256 manifest.

Six separate synthetic tests of the vendor tool passed locally before submission. Those tests verify byte and archive safety, **not** actual Matrix SDK code compatibility or security.

The candidate may still fail due to rusqlite API changes, upstream crate storage semantics, Rust compiler-version requirements, `anymap2` remaining in the SDK graph, or `unsafe-libyaml` remaining through the separate `serde_yaml` dependency. Any of those keeps the security gate closed. The provenance of the publisher crate and the source code for this proposed one-line patch must be re-reviewed before any acceptance. An approved fix also requires real Matrix device-encryption, SQLite WAL persistence/recovery, multi-device revocation and end-to-end regression tests.

## Integrity boundary

- The actual PR branch's `codex-rs/Cargo.toml`, `Cargo.lock`, vendored 0.18 source, and `deny.toml` remain unchanged by this proposed workflow.
- Original `blocking-ci` remains mandatory; no pre-existing RustSec warning or vulnerability is suppressed.
- A safe production SDK is **not** proven by this experiment, even if the resolver/compiler passes.
- This dependency research is independent from MemoryCell's reader/citation and prospective task evidence. `production_accepted=false`.

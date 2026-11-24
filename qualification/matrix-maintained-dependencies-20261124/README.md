# Matrix dependency and encrypted store qualification

This source stage replaces Matrix SDK 0.18 with the maintained 0.19.1 release
and preserves the upstream Rust 1.96 minimum throughout active build pins.
It backports upstream anymap3 commit
`9c5fdd2cf5be1b7b8b20541e56d7a109db968534` and aligns the SQLite adapter with
`rusqlite 0.41.1` / `libsqlite3-sys 0.39.1`. Cargo and Bazel lockfiles are
resolved in the integrating change; this source commit alone is not a
qualified, deployable dependency set. No advisory is ignored.

`source-normalization.json` records each imported Rust file's original and
normalized hashes. The reference is independently reconstructed from the
official crate archive, with the exact upstream anymap3 source patch, followed
by the repository formatter. Mechanical formatting is intentionally disclosed.

The existing persisted `matrix-sdk-0.18` path is retained. The pinned baseline
`07c8994f2402a58f6b59eb648c801fc40c6e2b96` creates an actual encrypted SQLite
state and crypto store with a synthetic Matrix identity. The normal Linux
workflow checks old-version reopen, new-version upgrade, second reopen, the
original Curve25519/Ed25519 device keys and custom state, and rejection of a
wrong passphrase on a separate fixture copy. It then runs the existing Matrix
consumer tests. No login or sync is performed, and no real credentials or
private operational store are used or uploaded.

## Validation status at source commit

- Official crate archive checksums verified.
- Exact upstream patch provenance verified.
- All 207 imported Rust files match the independently formatted reference.
- Repository `just fmt` and `git diff --check` passed.
- Workflow YAML and changed TOML parse checks passed.
- Actual locked dependency resolution, Rust 1.96 consumer compilation,
  encrypted-store migration and complete CI remain required on the final
  integrated head. This document does not report those pending checks as passed.

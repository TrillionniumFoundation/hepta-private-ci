# Remaining cargo-deny blockers

Status: **DENY / no advisory ignores**  
Base reviewed: `f8c9419df6ddeb36ff8b522a50219981fb8d9345`

## Exact RustSec evidence

With cargo-deny 0.19.0 and the cached RustSec database:

```
cargo deny check advisories --disable-fetch --hide-inclusion-graph
```

reports:

| Advisory | Current dependency | Required action |
|---|---|---|
| RUSTSEC-2026-0319 | `anymap2 0.13.0` via `matrix-sdk 0.18.0` | Replace with `anymap3` through a coordinated Matrix SDK migration; RustSec reports no safe upgrade. |
| RUSTSEC-2026-0318 | `matrix-sdk-crypto 0.18.0` | Upgrade the Matrix SDK family to >=0.19.0, including the vendored sqlite fork. |
| RUSTSEC-2024-0449 | `unsafe-libyaml 0.2.11` via `serde_yaml 0.9` | Replace YAML implementation with a maintained parser/adapter that does not depend on unsafe-libyaml. |
| RUSTSEC-2026-0367/0368/0369 | `zip 2.4.2` | Major upgrade to >=9.0.0 after auditing extraction, symlink, traversal, and mode-bit semantics. |
| RUSTSEC-2026-0346..0349 | `rustls 0.23.45` | Remediated by PR #2605 (`0.23.46`). |

Yanked warnings also remain for `chacha20 0.10.0` and `spin 0.9.8`; refresh them through normal lockfile updates after the advisory fixes.

## Why blind updates are rejected

- Matrix SDK 0.19 advertises Rust 1.96, while this repository currently pins Rust 1.95. Its vendored `matrix-sdk-sqlite-0.18.0` patch must migrate together with the SDK family.
- `serde_yaml_ng 0.10.0` still depends on `unsafe-libyaml`; renaming the crate does not close RUSTSEC-2024-0449.
- `zip 9.x` is a major version change and requires call-site review before changing the workspace requirement.

## Closure sequence

1. Raise and validate the Rust toolchain policy, then migrate Matrix SDK, crypto, base, store-encryption, and the vendored sqlite fork together. Prove `anymap2` is absent from `cargo tree`; run Matrix/e2e tests.
2. Replace YAML parsing with a maintained non-unsafe-libyaml parser while preserving schema, duplicate-key, alias, and error behavior. Add fixture tests.
3. Upgrade zip only after auditing all `ZipArchive::extract` and stream extraction call sites; add traversal, symlink, and Unix mode-bit tests.
4. Refresh yanked crates and run exact-head cargo-deny with a fetchable advisory database.

**No advisory ignore is acceptable for these findings.**
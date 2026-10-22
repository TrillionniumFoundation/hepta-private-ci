# i18n-config 0.4.8 maintained TOML parser backport

## Source and scope

- Published source: <https://static.crates.io/crates/i18n-config/i18n-config-0.4.8.crate>.
- Archive SHA-256: `3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`.
- The original MIT license, README, changelog, and three source modules are retained.
  Cargo cache bookkeeping and the standalone upstream Cargo.lock are omitted;
  `codex-rs/Cargo.lock` resolves the product dependency graph.
- Upstream fix: <https://github.com/kellpossible/cargo-i18n/commit/2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4>.

The `basic-toml` dependency is unmaintained (RUSTSEC-2026-0374). This backport
changes only the parser dependency, its error payload type, and the two
`from_str` calls. It does not import the upstream workspace modernization,
edition change, other dependency upgrades, API renames, or localization changes.
Repository rustfmt is applied to the imported Rust files, and a separate test
module exercises the public parsing entry points.

## Compatibility and features

Both manifests retain the reconciled base's `toml = "1.1.8"` requirement. The product lock
already contains the compatible `1.1.8+spec-1.1.0`; this patch reuses that version.
Only `std`, `serde`, and `parse` are enabled. Serialization and other optional
features are not needed by either parsing call.

All configuration fields, defaults, crate traversal, and localization selection
remain unchanged. The public `CannotDeserializeToml` variant retains its path
and error meaning, but its second field is now `toml::de::Error`, as in the
upstream fix; parser diagnostic wording can differ. The consuming
`i18n-embed-fl` code handles this error through its display implementation.
Tests cover the age fluent profile, Cargo metadata, gettext defaults and
overrides, parent selection, and invalid inputs with the original file path.

## Cargo and Bazel

This directory follows the existing path-patch convention in
`[patch.crates-io]`. It is not a new workspace package or a separately declared
Bazel target. The repository excludes `codex-rs/third_party` workspace targets
in `.bazelignore`; `@crates` resolves path patches as external dependencies.
Regenerate `MODULE.bazel.lock` with the repository's `just bazel-lock-update`
after changing the manifests or Cargo.lock.

No advisory suppression or audit policy change is part of this patch. Remove
it when a compatible published i18n-config release includes the maintained
parser and both Cargo and Bazel resolve the replacement successfully.

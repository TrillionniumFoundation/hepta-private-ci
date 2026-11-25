# Hepta TOML parser maintenance backport

This directory starts from the crates.io `i18n-config 0.4.8` archive:

- Archive SHA-256: `3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`.
- Published source commit: `ae88dc79fda061e1bbf96b8d8e8fe8d23f1e52e7`, path `i18n-config`, in [cargo-i18n](https://github.com/kellpossible/cargo-i18n).
- The upstream MIT license and package source are retained. The archive's standalone `Cargo.lock` is omitted; the Hepta workspace lockfile owns this dependency resolution.
- The retained `.cargo_vcs_info.json` identifies that upstream base, not the modified local source. This directory has no `.cargo-checksum.json` claiming unchanged registry contents; the committed workspace source records the patch.

`basic-toml` is unmaintained under [RUSTSEC-2026-0374](https://rustsec.org/advisories/RUSTSEC-2026-0374.html), with no patched release. At this backport, `0.4.8` is still the latest published `i18n-config` release. The upstream replacement is present in immutable commit [2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4](https://github.com/kellpossible/cargo-i18n/commit/2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4).

The backport takes only that parser change: use the workspace's already locked `toml 1.1.4` for the two existing deserialization calls and for the error payload, enabling only its `parse` and `serde` features, as the existing `ruma-macros` dependency does. These APIs use the parser's allocation support without requiring its optional `std` feature; `toml::de::Error` implements `core::error::Error` unconditionally. Upstream's migration uses the same APIs with a `1.1.6` dependency requirement; this backport retains the existing compatible `1.x` resolution instead of updating unrelated consumers. It does not import upstream's edition, unrelated dependency, or API-name changes. Existing configuration fields, file discovery, and error variant names (including `CannotPaseI18nToml`) remain unchanged. The payload of `CannotDeserializeToml` changes from `basic_toml::Error` to `toml::de::Error`; parser diagnostics consequently follow the maintained parser. Consumers must be compiled against this patch rather than assumed binary compatible.

`BUILD.bazel` and parser regression tests are local additions. The package is an explicit workspace member so Cargo's normal scoped test entry point executes these tests. They exercise actual file parsing, Cargo identity, Fluent settings, optional configuration, and malformed-input errors. The workspace's existing `codex-secrets` tests cover the `age` consumer. No advisory exception or deny-policy change is part of this patch.

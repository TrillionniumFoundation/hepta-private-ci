# i18n-config parser maintenance

This document retains the original import and dependency-patch record. The current
checkout also includes the repository formatting follow-up described below.


The starting source is the complete production source and license from the
crates.io `i18n-config 0.4.8` archive, SHA-256
`3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`.
The archive matches the original project Cargo.lock checksum.

The parser replacement follows the maintained upstream change at
https://github.com/kellpossible/cargo-i18n/commit/2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4:
the dependency is `toml 1.1.8`, two parsing calls use `toml::from_str`, and the
parse-error payload is `toml::de::Error`. The existing public error variant
`CannotPaseI18nToml` and the remaining 0.4 API are preserved. Unrelated upstream
API renames, package-wide dependency upgrades and CI changes are not included.

Three added behavior tests cover Fluent/Gettext settings and defaults, actual
crate/parent resolution, and malformed-file error identity. The existing package
had no unit tests. The new tests run from the independent vendor harness in the
project cloud, along with the unchanged Secrets, Keyring and Login package suites.
The package stays out of the production workspace's member list. Its root
Bazel alias points to `@crates//:i18n-config-0.4.8`, the native rules_rs library
generated from this local path patch. This uses the same resolved dependencies
and version as production consumers. Cloud evidence checks the generated
library's type, version and actual dependency edges before building it.

The registry packaging lock, original workspace-inheriting manifest, `.gitignore`
and registry VCS marker are omitted; the root generated Cargo/Bazel locks govern
the shipped dependency. Original README, changelog, source modules and MIT
license are retained. No RustSec waiver is added. This source proposal is not
qualified until its cloud-generated locks are reviewed and exact-head original
security and platform checks pass.

## Repository formatting follow-up (2026-11-14)

The normal repository formatter changed 2 Rust files.
HEPTA-FORMATTING-PROVENANCE.json binds every affected path to its exact Git
object, mode, size and SHA256 before and after formatting. The comparison uses
c2130629037b342e6e48154867b65acc8fc82434 as the input identity.

Import targets, aliases, visibility and attached attributes are retained.
Comments and non-import literals are retained; the other reviewed changes are
layout, trailing punctuation, single-expression block layout and same-order
derive grouping. Existing minimal dependency patches, upstream README files
and license bytes are retained. This record does not claim a new runtime test
result or a successful full-repository formatting check.

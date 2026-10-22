# i18n-config parser maintenance

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

The original workspace-inheriting `Cargo.toml.orig` is retained for source
auditing. The actual dependency graph is defined by the normalized `Cargo.toml`
and root generated Cargo/Bazel locks. The registry packaging lock, `.gitignore`
and registry VCS marker are omitted. Original README, changelog, source modules
and MIT license are retained. No RustSec waiver is added. This source proposal is not
qualified until its cloud-generated locks are reviewed and exact-head original
security and platform checks pass.

# Hepta security vendor: i18n-config 0.4.8

This is the MIT-licensed i18n-config module from
https://github.com/kellpossible/cargo-i18n at pinned Git commit
`10e345470d97c9cffb3bc611182f595ad93251bf` (source files, README and LICENSE copied exactly).
The Cargo.toml manifest is made standalone (workspace inheritance removed);
it retains the upstream maintained `toml` parser rather than the archived
`basic-toml` parser shipped by the crates.io i18n-config 0.4.8.

Reason: RUSTSEC-2026-0374 / unmaintained basic-toml is introduced by
i18n-config 0.4.8 via i18n-embed-fl/age. This local [patch.crates-io]
substitution eliminates the affected package without suppressing RustSec.

Cargo.lock selects the already-resolved toml 1.1.x and thiserror 2.x,
preserving the external i18n-config API version. Exact-head Cargo/Bazel,
localization parsing compatibility and security CI are required before merge.
Do not treat this as a release/production qualification.

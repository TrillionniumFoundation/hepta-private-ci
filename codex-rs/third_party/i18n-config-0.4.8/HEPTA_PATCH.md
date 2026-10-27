# Maintained TOML parser for age localization

The original package is `i18n-config 0.4.8` from crates.io. Its source archive
SHA-256 is `3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`.
The upstream license, original manifest, and source metadata are retained. The
exact original `.crate` archive is also retained in the dependency-remediation
evidence directory. Repository formatting may normalize the copied Rust source;
the production behavior changes remain limited to the parser migration below.

The production changes are limited to:

- replacing the `basic-toml 0.1` dependency with `toml 0.9.5`, which is also
  the workspace's TOML dependency range;
- changing the two deserialization calls to `toml::from_str`;
- using `toml::de::Error` as the payload of `CannotDeserializeToml`.

This changes the parser implementation. It does not rename the abandoned parser
or suppress RUSTSEC-2026-0374. The remaining i18n-config data model, fluent and
gettext support, age encryption, and localization assets remain in the graph.
The concrete error payload type and parser error wording change; consumers in
this repository must be compiled with the patch and retain error handling.

The added parser tests read real Cargo/i18n files, exercise both localization
backends, and reject malformed or duplicate-key configuration. The final gates
are `just test -p i18n-config`, `just test -p codex-secrets`, the normal
Cargo/Bazel lock refresh, and the unchanged cargo-deny scan. These gates must
run before this remediation is reported as complete.

Primary references:

- https://crates.io/api/v1/crates/i18n-config/0.4.8/dependencies
- https://static.crates.io/crates/i18n-config/i18n-config-0.4.8.crate
- https://rustsec.org/advisories/RUSTSEC-2026-0374.html

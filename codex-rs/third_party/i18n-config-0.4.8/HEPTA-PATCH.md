# i18n-config 0.4.8 maintained TOML parser

Source: the official i18n-config 0.4.8 archive, SHA-256
`3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`,
upstream commit `ae88dc79fda061e1bbf96b8d8e8fe8d23f1e52e7` in
<https://github.com/kellpossible/cargo-i18n/tree/ae88dc79fda061e1bbf96b8d8e8fe8d23f1e52e7/i18n-config>.
The complete upstream MIT license is retained in LICENSE.txt.

Age's localization macros still consume i18n-config 0.4.8, which depends on
the unmaintained basic-toml parser (RUSTSEC-2026-0374). This patch changes the
real parent implementation to the maintained toml crate already used by
the workspace. Both manifests use toml 0.9; the two parsing calls and the
wrapped deserialization error use toml's API. Configuration structures,
localization features, parent lookup and inheritance are preserved.

The upstream standalone Cargo.lock is omitted; the product Cargo.lock
resolves the shipped dependency graph. The dependency is explicitly excluded
from workspace membership. Bazel materializes this Cargo patch through
@crates; no ignored local BUILD target is added.

The codex-secrets owner tests exercise configuration strings and Unicode,
Gettext defaults and parent inheritance, parse failures, and the real Age
encryption/decryption integration. No advisory is ignored. Remove the patch
when upstream i18n-config replaces basic-toml in a compatible release.

Advisory: <https://rustsec.org/advisories/RUSTSEC-2026-0374.html>.

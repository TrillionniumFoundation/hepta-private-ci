# Hepta security vendor: i18n-config 0.4.8

Derived from MIT-licensed `kellpossible/cargo-i18n` i18n-config at commit
`10e345470d97c9cffb3bc611182f595ad93251bf`. The Rust source,
README.md and LICENSE.txt are unchanged copies from reviewed Hepta PR #2976.
Only its standalone Cargo.toml was adapted to the frozen Cell branch's
pre-existing `toml 1.1.4+spec-1.1.0` and `thiserror 2.0.18` versions.

Archived `basic-toml 0.1.10` was pulled via
`age -> i18n-embed-fl -> i18n-config` (RUSTSEC-2026-0374). The compatible
local i18n-config 0.4.8 uses maintained `toml`, preserving encrypted secret
handling and strict RustSec policy. Cargo.lock drops only the unmaintained
package and rebinds i18n-config to existing resolved versions; no registry
checksum was fabricated.

**Draft candidate; no production acceptance:** exact-head `cargo metadata
--locked`, Cargo check/test/Clippy, `cargo deny check`, Bazel lock and
Linux/macOS/Windows qualification plus upstream localization/API parity
must pass. Any resolver drift requires native Cargo reconciliation.

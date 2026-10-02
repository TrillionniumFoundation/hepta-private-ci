# Upstream Matrix SDK 0.19.0

Source: the official crates.io `matrix-sdk` 0.19.0 archive, SHA-256
`d41d3631bac5de5c2fdd8dad2edb84a9077a12836d50ef0fb5c3465335cc49ed`.

The published and original Cargo manifests retain `anymap2` as an import
alias for maintained `anymap3` 1.1, with its `std` map feature explicitly
enabled. RustSec RUSTSEC-2026-0319 recommends this replacement. The sole Rust
adaptation, in `src/event_handler/mod.rs`, imports its public `CloneAny`
trait and preserves the native `Send + Sync` map bounds. The Wasm map keeps
its original clone-only bound. Event context types, cloning, lookup and
handler identity stay unchanged; no unsafe adapter is added. Encryption,
authentication and identity checks are unchanged. Upstream 0.19 contains
the RUSTSEC-2026-0318 crypto fix.

The Cargo-derived rules_rs repository materializes this patched crate once,
preserving the dependency alias and selected features. Its generated
`rust_crate` includes the upstream Markdown files in `compile_data`;
the vendor directory is not a separate workspace crate.
Remove this patch when the upstream SDK adopts the maintained
package and the workspace can consume that release directly.

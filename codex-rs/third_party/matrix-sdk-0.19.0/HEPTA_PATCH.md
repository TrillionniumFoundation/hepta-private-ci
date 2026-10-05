# Upstream Matrix SDK 0.19.0

Source: the official crates.io `matrix-sdk` 0.19.0 archive, SHA-256
`d41d3631bac5de5c2fdd8dad2edb84a9077a12836d50ef0fb5c3465335cc49ed`.

The published and original Cargo manifests retain `anymap2` as an import
alias for maintained `anymap3` 1.1, with its `std` map feature explicitly
enabled. RustSec RUSTSEC-2026-0319 recommends this replacement. The event-context
adaptation, in `src/event_handler/mod.rs`, imports its public `CloneAny`
trait and preserves the native `Send + Sync` map bounds. The Wasm map keeps
its original clone-only bound. Event context types, cloning, lookup and
handler identity stay unchanged; no unsafe adapter is added. This context
adaptation leaves encryption, authentication and identity checks unchanged.
Upstream 0.19 contains the RUSTSEC-2026-0318 crypto fix.

The native HTTP settings path requires TLS certificate verification. Its public
`disable_ssl_verification` setter remains source compatible, but client build
returns `HttpError::TlsCertificateVerificationRequired` before constructing an
HTTP client or opening a store. The invalid-certificate acceptance branch is
removed. Default certificate validation, additional trusted roots and the
minimum TLS version retain their original behavior.

The Cargo-derived rules_rs repository materializes this patched crate once,
preserving the dependency alias and selected features. Its generated
`rust_crate` includes the upstream Markdown files in `compile_data`;
the vendor directory is not a separate workspace crate.
Remove the context adapter when the upstream SDK adopts the maintained package
and the workspace can consume that release directly. Preserve the certificate
verification requirement when updating the bundled SDK.

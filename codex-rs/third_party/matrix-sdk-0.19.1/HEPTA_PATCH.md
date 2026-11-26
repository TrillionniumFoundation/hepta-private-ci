# Hepta compatibility patch

This directory contains the crates.io source package `matrix-sdk 0.19.1`,
with its upstream version and license unchanged. The workspace keeps the
existing `e2e-encryption` and `sqlite` features and disables default features.
It explicitly enables upstream `rustls-aws-lc-rs` so a standalone client can
start with reqwest 0.13. Reqwest respects an existing process TLS provider and
otherwise uses a client-local AWS-LC provider; Hepta does not install a global
provider just for this adapter.

The private event-handler context map uses `anymap3 1.1.0` instead of
unmaintained `anymap2 0.13.0` (RUSTSEC-2026-0319). The manifest explicitly enables
`anymap3`'s `std` feature. The source imports its public `CloneAny` trait and
uses `Map<dyn CloneAny + Send + Sync>` on native targets and
`Map<dyn CloneAny>` on WebAssembly. Context extraction still calls
`get::<T>().cloned()`; public handler APIs and context ownership are unchanged.

All other SDK source is the upstream release. `BUILD.bazel` exposes this local
package and its included Markdown to Bazel. `Cargo.toml.orig` and `Cargo.lock`
are preserved upstream package files; workspace resolution uses the root
`codex-rs/Cargo.lock`.

The 0.19.1 Matrix dependency family includes the crypto fix for
RUSTSEC-2026-0318. Remove this event-handler patch when upstream adopts a
maintained context-map dependency.

Sources:

- https://crates.io/crates/matrix-sdk/0.19.1
- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://docs.rs/anymap3/1.1.0/anymap3/

Published `.crate` SHA-256 (verified against the crates.io index):

`2afc652a144822f6fbe24084e08bc59cb483fd0b504396d492131dec0749396e`

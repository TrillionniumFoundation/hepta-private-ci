# Rust UI workspace

This standalone workspace retains `core`, `web` and `robrix-ui` with its exact
lock. `robrix-ui` is the shared Rust/Makepad renderer; `core` contains bounded
state and owner-facing types; `web` is internal Rust compatibility code.

Use explicit UI tooling rather than the backend workspace's Rust1.96.0:

```sh
cargo +1.95.0 check --locked --manifest-path Cargo.toml --target wasm32-unknown-unknown -p hepta-robrix-ui
cargo +1.95.0 nextest run --locked --manifest-path Cargo.toml -p hepta-control-core -p hepta-robrix-ui --no-default-features --lib
```

Run `npm run build` from the parent application directory for the owned WASM
package. Run `npm run desktop` for the shared native preview with verified font
resources and per-invocation staging; a direct unprepared `cargo run` is not a
supported resource-complete build. Platform development libraries are required.

The builder's exact SDK/nightly pins, patches, licenses and source guards are
part of the build contract. Keep generated HTML, framework glue, WASM and font
assets from one verified build. See the [application guide](../README.md) for
product integration, owner and qualification limits.

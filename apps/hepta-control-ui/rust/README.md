# Rust UI workspace

This standalone workspace retains `core`, `web` and `robrix-ui` with its exact
lock. `robrix-ui` is the shared Rust/Makepad renderer; `core` contains bounded
state and owner-facing types; `web` is internal Rust compatibility code.

Use the standalone UI manifest and its explicit stable toolchain. The gateway
separately follows the canonical backend toolchain manifest:

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

Local draft recovery uses `ChatWorkspace::archive_local_drafts` and
`ChatWorkspace::from_local_draft_archive`. The bounded archive includes all
local rooms and selections in the anonymous partition and the four named
partitions retained by the original workspace. It excludes owner sessions,
signatures, remote thread bindings, timeline events and delivery state. A
restored workspace starts in its anonymous partition; a named partition is
selected only by a later authenticated `install_owner` call. The archive's
principal strings are routing labels and provide no authority. The host owns
private file storage, atomic replacement and migration, while an active IME
composition defers checkpointing.

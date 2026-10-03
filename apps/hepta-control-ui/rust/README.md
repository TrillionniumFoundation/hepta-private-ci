# Robrix-derived Rust UI workspace

[`robrix-ui`](robrix-ui) is the shared native/Web Makepad application. Follow
[CHAT_DESIGN.md](../CHAT_DESIGN.md) for the single normative design and the
[application guide](../README.md) for current implementation limits.

## Source map

- `robrix-ui/src/robrix/`: adapted upstream UI modules used by the application
- `robrix-ui/src/app.rs`: common Makepad entry and widget lifecycle
- `robrix-ui/src/presentation.rs`: borrowed chat projection and local actions
- `core/src/chat*.rs`: existing bounded chat state and owner-facing contracts
- `robrix-ui/UPSTREAM.json` and `robrix-ui/licenses/ROBRIX-MIT.txt`: derivation and license

The former `web` semantic-DOM host and native egui implementation are retained
historical/compatibility code, not the Robrix renderer. Their previous browser,
CPU-fixture and Console receipts do not validate the new application.

## Build the new crate

From this `rust/` directory, the native source entry is:

```sh
cargo run -p hepta-robrix-ui --bin hepta-robrix
```

Use the Makepad revision fixed in `robrix-ui/Cargo.toml` and the workspace
lockfile. Native builds also require the platform development libraries;
see the [current verification status](../README.md#current-status).

A standard Rust target check is useful but does not package a browser app:

```sh
cargo check --target wasm32-unknown-unknown -p hepta-robrix-ui
```

For the Web package, run the owned builder from the application directory:

```sh
cd ..
pnpm build
```

The builder verifies the pinned Makepad source/tooling and qualified nightly,
uses the no-threads custom-target/build-std flow, and applies the recorded WASM
clock patch in an isolated generated workspace. It emits a static message bridge
from that exact WASM, retains runtime schema equality checking and records the
input/output hashes. Raw upstream packaging alone omits these compatibility
steps. Keep HTML, framework JavaScript, resources and WASM from the same build.

`pnpm dev` builds and serves this package; `pnpm start` serves an existing build.
`pnpm build:legacy-dom` is explicitly legacy. The owned wrapper retains its
restrictive CSP; do not relax security policy to make a preview load.

Presentation-only tests, excluding the Makepad host, can be run from the
repository root through the repository runner:

```sh
just test --manifest-path "$PWD/apps/hepta-control-ui/rust/Cargo.toml" -p hepta-robrix-ui --no-default-features --lib
```

Compilation and these tests do not establish native rendering, browser input,
IME/accessibility behavior, live chat, operational Console controls or release
readiness. Test counts and the current build/runtime result are maintained only
in the [application status](../README.md#current-status). No deployment is implied
by these build instructions.

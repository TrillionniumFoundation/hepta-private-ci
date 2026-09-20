# Hepta Native

`apps/hepta-native` is the native desktop shell for Hepta. The production shell candidate is Rust-first and uses **eframe/egui + AccessKit** on Windows, macOS and Linux. The older JavaScript files remain as compatibility/source-boundary fixtures while product callers migrate; they are not the native host.

## What is implemented

- session-incarnation-fenced native operation identity;
- durable pending-operation journal and crash/restart reconciliation without effect replay;
- final-payload digesting inside the Rust shell rather than trusting a caller-supplied digest;
- kernel-owned `FinalUseAuthority` admission with durable single-use nonce consumption and live epoch/revocation revalidation immediately before OS entry;
- explicit local platform policy plus narrow open/reveal/clipboard/notification adapters;
- OS keyring storage for opaque session references and loopback gateway bearer capabilities through `codex-keyring-store`;
- signed endpoint manifests plus authenticated `keyring_bearer_v1` gateway requests; the product shell refuses the legacy unauthenticated gateway mode;
- signed stable-channel update verification, package and installed-predecessor digest fencing, UI staging, GUI-exit handoff to a separate updater helper, predecessor backup and rollback;
- eframe/egui native window with runtime, operation, update and accessibility views;
- AccessKit, native DPI scaling, keyboard focus order and English/Chinese shell strings;
- a Windows/macOS/Linux merge-candidate matrix plus an exact-head Linux gate that build, lint, test, package, restart packaged binaries in self-test mode and emit **unsigned qualification receipts**.

## Build

From this directory:

```sh
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets
cargo build --release --bins
```

On Linux, eframe's native dependencies are required. The repository CI installs the X11/Wayland/XKB/GL development packages before building.

## Run

Provision a random loopback gateway capability into the OS keyring without printing the bearer value:

```sh
cargo run --bin hepta-native-credential -- provision gateway.local
```

Launch the existing Hepta gateway with the same keyring account:

```sh
hepta --serve-ui --listen 127.0.0.1:7373 --auth-keyring-account gateway.local
```

The endpoint JSON passed to the GUI is a **signed** `hepta.endpoint-manifest.v1` that binds the loopback address, protocol version and `gateway.local` account. The signing private key remains external to this module.

The application fails closed unless all security-sensitive paths are explicit and absolute:

```sh
cargo run --bin hepta-native -- \
  --endpoint-manifest /absolute/path/endpoint.json \
  --trusted-keys /absolute/path/trusted-keys.json \
  --final-use-authority /absolute/path/final-use-authority.json \
  --state-dir /absolute/private/hepta-native-state \
  --allow-root /absolute/user-approved/root \
  --allow-clipboard \
  --allow-notifications
```

`--allow-root`, clipboard and notification switches are local policy ceilings only. They do **not** authorize an effect. Every effect requires an independently issued kernel `SignedFinalUseGrant`; the shell durably claims its nonce and consumes the resulting non-serializable `VerifiedUseToken` at the final OS boundary. If `--final-use-authority` is omitted, platform mutations are rejected before adapter entry. The current kernel durable final-use store is Unix-qualified only, so Windows builds remain read-only for platform effects until an equivalent Windows kernel store is implemented and qualified.

For a headless packaging smoke check:

```sh
cargo run --bin hepta-native -- --self-test
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the state machine, threat boundary, update protocol, platform matrix and qualification rules.

# Hepta Native

`apps/hepta-native` is the native desktop shell for Hepta. The production shell candidate is Rust-first and uses **eframe/egui + AccessKit** on Windows, macOS and Linux. The older JavaScript files remain as compatibility/source-boundary fixtures while product callers migrate; they are not the native host.

## What is implemented

- session-incarnation-fenced native operation identity;
- durable pending-operation journal and crash/restart reconciliation without effect replay;
- final-payload digesting inside the Rust shell rather than trusting a caller-supplied digest;
- Ed25519-signed, short-lived platform grants bound to session, operation, action and final payload;
- explicit local platform policy plus narrow open/reveal/clipboard/notification adapters;
- OS keyring storage for opaque session references and loopback gateway bearer capabilities through `codex-keyring-store`;
- signed endpoint manifests plus authenticated `keyring_bearer_v1` gateway requests; the product shell refuses the legacy unauthenticated gateway mode;
- signed update manifest verification, package digest verification, staging, predecessor backup, separate updater activation and rollback;
- eframe/egui native window with runtime, operation, update and accessibility views;
- AccessKit, native DPI scaling, keyboard focus order and English/Chinese shell strings;
- a Windows/macOS/Linux CI matrix that builds, lints, tests and packages **unsigned development artifacts**.

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
  --state-dir /absolute/private/hepta-native-state \
  --allow-root /absolute/user-approved/root \
  --allow-clipboard \
  --allow-notifications
```

`--allow-root`, clipboard and notification switches are local policy ceilings only. They do **not** authorize an effect. Every effect still requires a valid signed `hepta.platform-grant.v1` for the exact session incarnation, operation and final payload.

For a headless packaging smoke check:

```sh
cargo run --bin hepta-native -- --self-test
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the state machine, threat boundary, update protocol, platform matrix and qualification rules.

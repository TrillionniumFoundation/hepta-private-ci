# Hepta native compatibility boundary

This root retains the bounded JavaScript native-operation intent and terminal-
observation fixtures used by existing contract tests. It does not call platform
APIs directly and grants no filesystem, notification, physical-effect,
promotion or release authority.

The selected native desktop application is now the Rust
[`codex-rs/hepta-native-app`](../../codex-rs/hepta-native-app/README.md).
New product-host work belongs there. This compatibility package remains
fail-closed until its callers are migrated or explicitly retired.

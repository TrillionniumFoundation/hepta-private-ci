# Hepta native intent and shell compatibility library

This JavaScript root defines bounded native-operation intents, terminal
observations and injected backend/platform/updater boundaries. It does not
call platform APIs directly or launch the shipped Rust window.

The actual Rust/Makepad application, native keyboard and Linux accessibility
bridge are in [hepta-control-ui](../hepta-control-ui/README.md) and its
[native composition](../hepta-control-ui/rust/robrix-ui/NATIVE_COMPOSITION.md).
This compatibility library grants no filesystem, notification, physical-effect,
promotion or release authority. Its Node tests are separate from native ELF,
IME, AT-SPI, screen-reader and display qualification.

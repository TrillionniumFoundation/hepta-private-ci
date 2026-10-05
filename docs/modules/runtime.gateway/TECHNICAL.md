# Native gateway

The native gateway is an independent loopback HTTP process. It composes the
existing runtime projection and Supervisor client for the desktop. It belongs
above those owners; libraries and domain owners must not depend on this binary.
Its sole source and Cargo ownership declaration is [module.toml](module.toml).

[Launch and HTTP handling](../../../codex-rs/hepta-native-gateway/src/lib.rs)
bound requests to 32 KiB and 64 concurrent connections, with existing five-second
request and response limits. The listener requires a loopback address and a
private bearer capability from the OS keyring or protected capability file.
[Lifecycle transport](../../../codex-rs/hepta-native-gateway/src/lifecycle_source.rs)
uses the existing typed Supervisor requests and response envelopes.

The gateway owns no Fleet, grant, model, secret or domain store. A lifecycle
request reaches the existing Supervisor authority and durable mutation journal;
the HTTP response cannot establish process readiness or task success on its own.
Uncertain mutations retain their original operation identity for status lookup.
Unavailable owners produce bounded errors rather than fabricated healthy state.

Existing protocol compatibility, capability checks and source modes remain in
[gateway tests](../../../codex-rs/hepta-native-gateway/src/lib.rs) and
[lifecycle tests](../../../codex-rs/hepta-native-gateway/src/lifecycle_http.rs).
Run `just test -p codex-hepta-native-gateway --lib` from `codex-rs` for this owner.
The [desktop operating guide](../../../apps/hepta-native/README.md) describes its
actual consumer. The source registry records production implementation as false
until the integrated source and installed Linux instance are qualified together.

Adding or removing this composition process changes its manifest, package and
consumer configuration. It does not require rewriting the historical V8
implementation-lane or work-package inventories. Existing owner recovery,
privacy and resource requirements remain in the [shared guide](../README.md).

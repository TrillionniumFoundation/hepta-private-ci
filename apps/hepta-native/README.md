# Hepta native shell

This root defines bounded native-operation intents and terminal observations.
It does not call platform APIs directly and grants no filesystem, notification,
physical-effect, promotion or release authority.


## Optional HAC1 native reference adapter

`NativeShellRuntime.requestPlatformCapabilityBinary` accepts the registered HAC1
frame through a constructor-installed principal and body generation, read-only reference resolver and
monotonic clock. The existing six-field text entry is unchanged. Only the existing
open/reveal/copy/notify reference capabilities are supported; raw paths, credentials,
executable payloads and arbitrary desktop input are not accepted here.

The adapter freezes frame bytes and the current view before asynchronous resolution,
verifies the resolved platform-reference payload, forwards the full action digest to
the installed platform permission/invoke ports, and reuses the existing operation
identity and in-flight promise. Resolution and permission timeouts cannot dispatch;
an invocation timeout remains indeterminate even if a late reply reports success.
Unsettled resolvers retain their bounded capacity slot. A deadline does not prove
physical cancellation of an already entered platform operation.

The platform reference must be resolved to immutable final bytes by its owning
adapter before actual effects. Matching digests is not cryptographic authorization.
This shell boundary is process-local, not durable exactly-once execution, a selected
OS driver, an independently trusted outcome observer, or deployment activation.
The platform owner remains responsible for final-use revocation, persistent operation
identity, stop/reconcile and OS-specific outcome evidence.

The selected body generation is distinct from the UI projection generation; a matching UI generation cannot authorize an action for a different body.

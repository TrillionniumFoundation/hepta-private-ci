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

## Query without redispatch

`observePlatformOperationBinary({ operationId, sourceActionDigest })` returns an
immutable snapshot of the exact retained local operation: `not_recorded`,
`permission_pending`, `dispatched`, or `observed` plus the original receipt.
It remains readable after action expiry or session close; it never invokes the
resolver, permission adapter or platform operation. A different action digest is
an identity conflict. An indeterminate receipt is not replaced by a late success.
This owner-local method is not an external unauthenticated endpoint.

Local `not_recorded` is not evidence that a previous process did nothing. Durable
lookup and terminal reconciliation belong to the existing platform/kernel owners.
The deadline is checked again on promise settlement, independently of Node timer
callback ordering. A result arriving after the monotonic deadline is not timely.

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

## Bounded Linux/X11 clipboard adapter

`src/x11-clipboard.js` supplies an optional `X11ClipboardPlatform` implementation
for the existing `NativeShellRuntime` platform port. It admits only `copy_text`
and immutable `text.sha256:<content-sha256>` resources. The selected host provides
the local display, exact executable digest, shared monotonic clock and a synchronous
`withVerifiedUse(request, dispatch)` authorizer. Availability is not authorization;
no default permissive authorizer or ambient display/shell is installed.

The exact checked executable is launched through its inherited Linux descriptor.
The complete HAC1 source-action digest, session/operation identity, content-bound
payload and deadline reach the final-use callback. One foreground writer is started;
bounded separate read-only processes check the clipboard contents. Observation
retries never create another writer. Receipts expose digests rather than clipboard
text. At most four live writer handles are retained. Close requests termination,
escalates after a bounded interval, and reports unresolved cleanup rather than
claiming an unobserved process exit.

This adapter has no persistent effect ledger. Same-process deduplication remains in
`NativeShellRuntime`; crash/restart can still leave an unknown effect requiring the
existing durable operation owner. Clipboard ownership is ephemeral and ends when
its writer exits. A matching readback is a point-in-time postcondition, not proof
of permanent clipboard contents or an independent acceptance decision. Dynamic
libraries, X server authenticity, other clients and filesystem parents remain
selected-host assumptions. macOS/Wayland and normal daemon installation are not
provided by this Linux/X11 profile.

`qualification/x11-clipboard.mjs` is an explicit disposable-display real-OS probe;
its backend and final-use callbacks are fixtures, not production trust. It uses no
user clipboard or secrets and starts no TCP listener. Its presence and unit-test
results are not a passed OS probe. A successful probe must retain the actual source,
executable, action, readback and cleanup receipt. Run it only in the authorized
qualification host; normal test discovery does not start an X server.

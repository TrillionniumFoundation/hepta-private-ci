# Live-shell organ composition

The existing `hepta --serve-ui` startup opens and verifies the existing schema-v5
stores, constructs a compiled-in body graph, and starts its handlers in dependency
order. `GET /api/hepta/runtime` calls `HeptaRuntime::status_json`, which dispatches
one generation-fenced message from `runtime.status.ingress` to
`runtime.status.adapter`. The adapter serializes the existing `RuntimeStatus`.
The JSON schema, route inventory and all eight closed-effect flags are unchanged.

This is a real native-gateway caller of the control-plane host, not a qualification
binary or a declaration that all 24 planned organs are running. Both handlers
share the live-shell process. Body generation 1 identifies this compiled-in graph;
it is not the memory snapshot generation or a deployable signed body generation.
The local fallback digest identifies the HTTP-503 software contract, not physical
safety evidence. The owner is `runtime.hepta-live-shell`, the actual composing
component; this does not claim that agentd starts the shell today.

The host admits only empty effect scopes and trusted, compiled-in handlers. The
handler trait is not a sandbox. No plugin discovery, dynamic code loading, state
migration, credential, network client, model call, automatic fallback, selection,
promotion or release is introduced. Future hosts that need any of those capabilities
require their own contracts and independent admission.

An initialization failure is retained and aborts native startup. Busy, poisoned,
stopped or quarantined hosts cannot bypass dispatch; the gateway returns a generic
503 without exposing internal errors to the client. The host uses a nonblocking
lock so concurrent requests cannot queue an unbounded backlog behind a handler.
Its final owner drop stops started handlers in reverse initialization order.
`/healthz` remains process liveness, not organ readiness.

The existing infallible `from_adapter` remains available for explicit host adapters.
Such adapters are trusted synchronous, bounded status providers, not untrusted
plugins. `status()` retains its legacy direct snapshot API; the network route uses
only `status_json()`. State adapters must not create or migrate stores while
observing status.

Qualification targets are `codex-hepta-control-plane`, `codex-hepta-runtime` and
`codex-hepta-native-gateway`. Tests cover graph lifecycle, bounded dispatch, the
real adapter call, denied authority, busy/stopped failure and verified-store reopen.
Tests are not proof of deployment, physical embodiment, artifact activation or
longitudinal learning; those remain independent work packages.

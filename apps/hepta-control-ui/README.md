# Hepta control UI

This source root contains the authority-free presentation and runtime-client
implementation for `ui.control`.

The current implementation has eight bounded source layers:

- `src/protocol.js` — canonical bounded values, semantic SHA-256 binding,
  stable typed errors and capacity limits.
- `src/control.js` — safe runtime projection and authority-free UI operation
  proposals.
- `src/runtime-client.js` — authenticated session/snapshot/request/reconciliation
  state.
- `src/browser-app.js` — a framework-free accessible DOM control-plane shell with duplicate-action locking, focus restoration and external mutation blocking.
- `src/pending-store.js` — bounded durable unresolved-operation identity mirror; no proposal/scope payload is persisted.
- `src/http-transport.js` — same-origin HTTPS/CSRF JSON transport adapter.
- `src/browser-host.js` — authenticated bootstrap and native accessible exact-request confirmation dialog.
- `src/web-main.js` — browser composition, snapshot polling, reconnect/reconcile and connectivity mutation blocking.

`RuntimeClient.applySnapshot()` projects each backend module through the safe
allowlist before it reaches `readView()`. Raw provider payloads, credentials and
unknown presentation fields are not forwarded. Requests carry the actual
bounded `intent` or stop `scope`, and the client computes the semantic digest
from the final immutable request rather than trusting a caller-supplied digest.
A request identity is recorded before transport I/O and, when configured by the authenticated browser bootstrap, durably mirrored before dispatch. Response loss therefore remains `indeterminate` across reconnect or reload and is reconciled by operation identity instead of being silently forgotten or blindly duplicated. The durable mirror contains only identity/provenance/retry metadata, never the operation proposal or stop scope.

The `hepta.ui-control.transport-request.v1` and request-semantics labels used by
`runtime-client.js` identify a **package-local transport-adapter envelope**.
They are not new registered cross-module contracts and do not replace
`ModulePort::runtime.agentd::ui.control`; the injected transport remains
responsible for mapping this bounded client envelope onto the existing
registered backend boundary.

`buildOperationProposal()` returns `UiOperationProposalV1`. The historical
`buildOperationIntent()` export is a compatibility alias and deliberately does
**not** mint or impersonate `kernel.operations`' `OperationIntentV1`. A
separately authorized backend adapter owns admission of effect-bearing
contracts.

Build and verify from the repository root:

```bash
npm --prefix apps/hepta-control-ui run check
npm --prefix apps/hepta-control-ui run build
# CI also runs this against real Google Chrome:
npm --prefix apps/hepta-control-ui run browser-e2e
```

See [`docs/modules/ui.control/DEVELOPMENT.md`](../../docs/modules/ui.control/DEVELOPMENT.md)
for request/transport schemas, state-machine semantics, limits, browser-host
integration and the deployment qualification checklist.

`build` emits content-hashed ESM/CSS, top-level SRI, an asset manifest, a web manifest and a deployer `security-headers.json`. The concrete browser transport refuses cross-origin endpoints, requires HTTPS outside loopback, uses same-origin credentials and obtains a fresh CSRF token for POSTs.

This source implementation still grants no authority to issue capabilities or write authoritative stores. A built artifact and mock-backend Chrome smoke are not evidence that a selected deployment actually applies TLS/session/security headers, that the real backend enforces authority/RBAC/effects, or that independent cross-browser/screen-reader acceptance, activation or release are complete.

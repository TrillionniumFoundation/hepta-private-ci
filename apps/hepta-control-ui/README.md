# Hepta control UI

This source root contains the authority-free presentation and runtime-client
implementation for `ui.control`.

The current implementation has four layers:

- `src/protocol.js` — canonical bounded values, semantic SHA-256 binding,
  stable typed errors and capacity limits.
- `src/control.js` — safe runtime projection and authority-free UI operation
  proposals.
- `src/runtime-client.js` — authenticated session/snapshot/request/reconciliation
  state.
- `src/browser-app.js` — a framework-free accessible DOM control-plane shell.

`RuntimeClient.applySnapshot()` projects each backend module through the safe
allowlist before it reaches `readView()`. Raw provider payloads, credentials and
unknown presentation fields are not forwarded. Requests carry the actual
bounded `intent` or stop `scope`, and the client computes the semantic digest
from the final immutable request rather than trusting a caller-supplied digest.
A request is recorded before transport I/O; response loss therefore remains
`indeterminate` and is reconciled by operation identity on reconnect instead of
being silently forgotten or blindly duplicated.

`buildOperationProposal()` returns `UiOperationProposalV1`. The historical
`buildOperationIntent()` export is a compatibility alias and deliberately does
**not** mint or impersonate `kernel.operations`' `OperationIntentV1`. A
separately authorized backend adapter owns admission of effect-bearing
contracts.

Run the complete source checks from the repository root:

```bash
npm --prefix apps/hepta-control-ui run check
npm --prefix apps/hepta-control-ui run build
```

See [`docs/modules/ui.control/DEVELOPMENT.md`](../../docs/modules/ui.control/DEVELOPMENT.md)
for request/transport schemas, state-machine semantics, limits, browser-host
integration and the deployment qualification checklist.

This source implementation still grants no authority to issue capabilities or
write authoritative stores. A built browser shell is not evidence that deployed
authentication, CSP/CSRF/WebSocket topology, backend authority, end-to-end
accessibility, activation, acceptance or release are complete.

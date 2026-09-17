# Hepta control UI

`apps/hepta-control-ui` is the authority-free web control-plane client and
presentation boundary for module `ui.control`.

The package now contains four layers:

- `src/control.js` — allowlisted runtime projection and authority-free operator proposals.
- `src/runtime-client.js` — authenticated session, coherent snapshot and operation state machine.
- `src/web-app.js` — framework-free accessible browser presentation/controller shell.
- `web/` — static browser entrypoint built by `npm run build`.

The UI never creates canonical `OperationIntentV1`, never writes an
authoritative store directly and never treats request acceptance, disconnect or
local rendering as terminal external success. `OperationIntentV1` remains owned
by `kernel.operations`.

Runtime snapshots are projected through a closed safe-field boundary before
`readView()` can expose them. Request semantic digests are derived internally
from canonicalized complete request semantics. A request is placed in the local
pending ledger before transport I/O so a lost acknowledgement remains
`indeterminate` and must be reconciled rather than blindly retried.

The browser shell is source-complete enough for local packaging and injected
transport composition, but it does **not** claim production deployment
qualification. A selected deployment still has to provide the authenticated
backend transport/subscription implementation, server-side Origin/CSRF/session
controls, CSP headers, browser support evidence and end-to-end accessibility
qualification.

See [`DEVELOPMENT.md`](DEVELOPMENT.md) for the implementation contract, wire
shapes, state machine, local commands and qualification checklist. Normative
module ownership and authority remain in
[`docs/modules/ui.control/TECHNICAL.md`](../../docs/modules/ui.control/TECHNICAL.md)
and the canonical registries.

## Local commands

```sh
npm --prefix apps/hepta-control-ui test
npm --prefix apps/hepta-control-ui run build
npm --prefix apps/hepta-control-ui run check
npm --prefix apps/hepta-control-ui run dev
npm --prefix apps/hepta-control-ui start
```

`dev` and `start` bind only to `127.0.0.1` and are a local static development
server, not a production host.

# ui.control development guide

This guide is the implementation-facing companion to [`TECHNICAL.md`](TECHNICAL.md).
`TECHNICAL.md` and the canonical registries remain normative for ownership and
capability. This file explains how to develop, test and integrate the current
JavaScript/browser implementation without widening that authority boundary.

## 1. Current source layout

`ui.control` is rooted at `apps/hepta-control-ui`.

- `src/protocol.js` — bounded canonical data snapshotting, SHA-256 semantic
  binding, stable typed errors and shared limits.
- `src/control.js` — authority-free runtime projection and UI operation
  proposal construction.
- `src/runtime-client.js` — authenticated runtime session, coherent snapshot,
  request submission, indeterminate handling and reconciliation.
- `src/browser-app.js` — framework-free DOM control-plane shell. It renders only
  projected state and disables mutation from stale views.
- `src/index.js` — package exports.
- `test/control.test.js` — projection and proposal boundary tests.
- `test/runtime-client.test.js` — protocol, failure, capacity and reconciliation
  tests.
- `test/browser-app.test.js` — browser presentation and stale-control tests.
- `scripts/build.mjs` — dependency-free ESM build/copy step into `dist/`.

The browser shell is a source implementation. Deployed authentication,
CSP/CSRF/WebSocket topology, a selected hosting profile and end-to-end
accessibility/deployment qualification remain separate gates.

## 2. Runtime snapshot ingress

The runtime client accepts one coherent snapshot at a time. A snapshot has this
shape:

```js
{
  sessionId: "session.17",
  connectionGeneration: 4,
  generation: 31,
  revision: 902,
  digest: "<64 lowercase hex>",
  modules: [
    {
      moduleId: "runtime.agentd",
      status: "ready",
      revision: 44,
      digest: "<64 lowercase hex>"
    }
  ]
}
```

`RuntimeClient.applySnapshot()` validates session/generation lineage, rejects
revision regression and duplicate module IDs, and passes every module through
`projectRuntime()` before it becomes visible to `readView()`. Unknown provider
or secret fields therefore do not cross the presentation boundary. The
projected view is bounded to 1 MiB and the module list is bounded to 4096
entries. The current and immediately previous coherent snapshot generations are
retained only in memory; neither is an authoritative store.

Do not render raw backend snapshot objects. New display fields must first be
registered and added to the explicit projection with corresponding negative
leakage tests.

## 3. Operation request semantics

The UI does not mint `kernel.operations`' `OperationIntentV1`. The source-level
proposal is `UiOperationProposalV1`:

```js
{
  operationId: "operation.123",
  subjectId: "runtime.agentd",
  action: "request_retry",
  expectedRevision: 44,
  displayedRevision: 902
}
```

`expectedRevision` is the target subject revision. `displayedRevision` is the
coherent runtime view revision from which the operator confirmed the request.
They are independent values and can differ.

`RuntimeClient.submitRequest()` constructs the authority-free proposal itself.
The client canonicalizes the request semantics and computes the SHA-256 semantic
digest internally. A caller-supplied digest is never trusted as authority and
is not used to decide semantic identity.

The transport receives:

```js
{
  schema: "hepta.ui-control.transport-request.v1",
  sessionId,
  connectionGeneration,
  runtimeGeneration,
  displayedRevision,
  operationId,
  semanticDigest,
  intent: {
    kind: "UiOperationProposalV1",
    operationId,
    subjectId,
    action,
    expectedRevision,
    authorityGranted: false,
    directStoreWrite: false
  }
}
```

A separately authorized backend adapter remains responsible for current-state
validation and construction/admission of any canonical effect-bearing contract.

## 4. Stop request semantics

`requestStop()` requires an explicit bounded scope:

```js
await client.requestStop({
  operationId: "stop.123",
  displayedRevision: 902,
  scope: {
    scopeKind: "runtime",
    targetId: "runtime.agentd"
  }
});
```

The scope is recursively snapshotted and frozen before digesting and transport.
The default browser shell does not equate this request acknowledgement with a
hardware or backend terminal stop. Only a trusted terminal observation can
settle it.

## 5. Transport adapter contract

Inject a transport with four asynchronous functions:

```js
const transport = {
  async connect({ endpointId, protocolVersion, manifestDigest }) {},
  async request(method, request) {},
  async reconcile(query) {},
  async close({ sessionId }) {}
};
```

A successful request acknowledgement must bind all of:

```js
{
  accepted: true,
  method,
  sessionId,
  connectionGeneration,
  runtimeGeneration,
  operationId,
  semanticDigest
}
```

A reconciliation observation must bind the current connection and the original
operation provenance:

```js
{
  sessionId,                    // current session
  connectionGeneration,         // current connection generation
  method,
  operationId,
  semanticDigest,
  originSessionId,
  originConnectionGeneration,
  runtimeGeneration,
  status,
  terminalObserved,
  outcomeDigest
}
```

The client rejects observations with changed method, digest, origin generation,
current session, or runtime generation.

## 6. Pending, indeterminate and terminal state

The local state machine is deliberately conservative:

1. Before crossing `transport.request()`, the operation identity and immutable
   semantics are inserted into the bounded pending map.
2. A valid backend acknowledgement leaves the operation `pending`.
3. A transport exception leaves it `indeterminate`; it is not removed and it is
   not blindly retried.
4. Reconnect marks unresolved work indeterminate and calls
   `transport.reconcile()` for each retained operation ID.
5. Only a provenance-valid observation with a registered terminal status and
   `terminalObserved: true` removes the operation from the pending map.

This closes the response-lost-after-accept ambiguity without claiming exactly
once execution. The backend must implement durable operation identity and
reconciliation semantics.

## 7. Canonicalization and limits

Current client-enforced limits:

| Boundary | Limit |
|---|---:|
| Projected runtime view | 1 MiB UTF-8 JSON |
| Canonical request/scope | 64 KiB UTF-8 JSON |
| Canonical object depth | 32 |
| Canonical nodes | 4096 |
| Modules per snapshot | 4096 |
| Pending operations | 1024 |
| Stable identifier | 128 characters |

Canonical request values permit JSON primitives, arrays and plain objects with
safe-integer numbers. Accessors, symbols, non-plain prototypes, sparse arrays,
cycles and values outside the resource bounds fail closed.

## 8. Typed failure surface

All new protocol/runtime errors use `UiControlError` with a stable `code`.
Current codes are:

- `INVALID_INPUT`
- `NOT_CONNECTED`
- `UNAUTHENTICATED`
- `INCOMPATIBLE_PROTOCOL`
- `STALE_SNAPSHOT`
- `REQUEST_REJECTED`
- `BACKEND_UNAVAILABLE`
- `PROTOCOL_VIOLATION`
- `RECONCILIATION_MISMATCH`
- `CAPACITY_EXHAUSTED`
- `VIEW_TOO_LARGE`

Browser UX should branch on `code`, not parse error-message text. Message text
is for diagnostics and may be refined without changing recovery semantics.

## 9. Browser application shell

`ControlPlaneApp` is intentionally framework-free so the authority and state
boundary is independent of a selected UI framework. The host supplies the DOM
root, a connected `RuntimeClient`, and a final confirmation function:

```js
import { ControlPlaneApp } from "@hepta/control-ui";

const app = new ControlPlaneApp({
  root: document.querySelector("#app"),
  client,
  confirmAction: async ({ kind, request }) => {
    // Render an accessible final confirmation using the exact immutable request.
    return kind === "operation" ? showOperationDialog(request) : showStopDialog(request);
  }
});

app.render();
```

The shell uses DOM `textContent`, not HTML injection, marks status/alert regions
for assistive technology, exposes pending/indeterminate state, and disables all
mutating controls while the view is stale. The final confirmed request is the
same immutable object passed to `RuntimeClient`.

A production host must still define focus restoration, complete keyboard and
screen-reader flows, localization, authentication/session expiry behavior,
CSP, CSRF/CORS policy and WebSocket/HTTP transport deployment.

## 10. Local development

From repository root:

```bash
npm --prefix apps/hepta-control-ui run check
npm --prefix apps/hepta-control-ui run build
```

`check` performs JavaScript syntax validation and executes all control-ui tests.
`build` produces `apps/hepta-control-ui/dist/` from the source ESM modules and
syntax-checks the output. `dist/` is a build artifact and must not be treated as
an authoritative source or evidence receipt.

## 11. Required regression cases

Every change touching the transport, projection or browser controller should
retain tests for:

- provider/secret fields cannot reach `readView()` or the browser view model;
- stale displayed revisions reject mutation;
- target revision and displayed revision remain separately bound;
- semantic digest is computed by the client from the final payload;
- reused operation identity with changed semantics fails closed;
- response-lost-after-accept becomes indeterminate and reconciles after
  reconnect without duplicate submission;
- cross-session/origin provenance cannot settle a pending operation;
- terminal state requires explicit terminal observation;
- 1 MiB view and 1024 pending-operation limits are enforced;
- protocol mismatch and backend rejection expose stable typed errors;
- stale browser views disable mutation.

The repository CI runs these checks at source HEAD and at a deterministic
synthetic merge candidate for pull requests.

## 12. Deployment qualification checklist

Source completion is not deployment qualification. Before changing
`productionImplementation`, `deploymentQualificationComplete`, `activation` or
`release` claims, record independent evidence for all of the following:

- selected browser support matrix and real built artifact;
- authenticated backend endpoint and protocol version negotiation;
- deployed TLS/WebSocket/HTTP topology;
- CSP, CSRF/CORS, cookie/token and origin policy;
- backend durable operation deduplication/reconciliation;
- accessibility E2E for keyboard and screen-reader users, including error focus
  recovery and stop request;
- browser secret scan and provider-payload leakage checks;
- disconnected/reconnect and response-loss fault injection;
- measured interaction/render limits against the selected host profile;
- rollback to a compatible client/backend protocol pair.

Do not translate passing source tests into activation, acceptance, promotion or
release authority.

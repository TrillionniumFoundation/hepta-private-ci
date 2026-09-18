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
- `scripts/build.mjs` — dependency-free static browser build that emits hashed ESM/CSS, SRI, an asset manifest, a web manifest and a deployer security-header policy into `dist/`.
- `scripts/browser-e2e.mjs` — real Chromium/Chrome smoke qualification against the built artifact and a bounded mock control backend.
- `src/pending-store.js` — bounded, schema-validated durable mirror for unresolved operation identities only.
- `src/http-transport.js` — same-origin HTTPS JSON transport with fresh CSRF tokens, bounded responses and fail-closed origin policy.
- `src/browser-host.js` / `src/web-main.js` — browser bootstrap, native accessible confirmation dialog and deployable source composition.

The browser shell and static artifact are source implementations. The repository now supplies a same-origin HTTPS/CSRF HTTP adapter, generated security-header policy and a real-Chrome smoke harness. Real backend authority/RBAC/effects, selected TLS/session/reverse-proxy deployment and independent cross-browser/assistive-technology qualification remain separate gates; source controls are not deployment evidence.

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
entries. The current and immediately previous coherent snapshot generations are retained only in memory. Unresolved operation identities may additionally be mirrored in the bounded `LocalStoragePendingStore` so browser reload/crash recovery can reconcile without replaying a mutation. The durable mirror excludes the proposal/stop payload and is not an authoritative store; deployments must use an opaque principal-scoped `persistenceNamespace` and rotate it when the authenticated principal changes.

Do not render raw backend snapshot objects. New display fields must first be
registered and added to the explicit projection with corresponding negative
leakage tests.

## 3. Operation request semantics

The UI does not mint `kernel.operations`' `OperationIntentV1`. A caller submits
an authority-free operation proposal plus the exact coherent view identity that
was displayed and confirmed:

```js
await client.submitRequest({
  operationId: "operation.123",
  subjectId: "runtime.agentd",
  action: "request_retry",
  expectedRevision: 44,
  displayedView: {
    sessionId: "session.17",
    connectionGeneration: 17,
    generation: 51,
    revision: 902,
    digest: "<64 lowercase hex>"
  }
});
```

`expectedRevision` is the target subject revision. `displayedView.revision`
is the coherent runtime view revision from which the operator confirmed the
request; they are independent values and can differ. The remaining
`displayedView` fields bind the confirmation to the exact session, connection,
runtime generation and snapshot digest. A reconnect cannot make an old
confirmation valid merely by reusing the same numeric revision.

`RuntimeClient.submitRequest()` constructs `UiOperationProposalV1` itself.
The client compares the complete displayed-view binding with the current
coherent session/snapshot before transport, canonicalizes the request semantics
and computes the SHA-256 semantic digest internally. A caller-supplied digest is
never trusted as authority and is not used to decide semantic identity.

The transport receives:

```js
{
  schema: "hepta.ui-control.transport-request.v1",
  sessionId,
  connectionGeneration,
  runtimeGeneration,
  runtimeDigest,
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
  displayedView: {
    sessionId: "session.17",
    connectionGeneration: 17,
    generation: 51,
    revision: 902,
    digest: "<64 lowercase hex>"
  },
  scope: {
    scopeKind: "runtime",
    targetId: "runtime.agentd"
  }
});
```

The stop scope and exact displayed-view binding are both covered by the client-computed semantic digest. The scope is recursively snapshotted and frozen before digesting and transport.
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

The client rejects observations with changed method, digest, origin generation, current session, or runtime generation. An in-flight acknowledgement is always checked against the immutable provenance captured in its pending entry, never against mutable `this.#session` / `this.#snapshot` state after an `await`. An operation whose original mutation dispatch is still in flight is excluded from both automatic and direct reconciliation, so a reconnect cannot race terminal reconciliation ahead of the original acknowledgement.

## 6. Pending, indeterminate and terminal state

The local state machine is deliberately conservative:

1. Before crossing `transport.request()`, the operation identity and immutable
   semantics are inserted into the bounded pending map.
2. A valid backend acknowledgement leaves the operation `pending`.
3. A transport exception leaves it `indeterminate`; it is not removed and it is
   not blindly retried.
4. Reconnect marks unresolved work indeterminate and calls `transport.reconcile()` for each retained operation ID; it never replays the mutation.
5. Reconciliation runs as read-only batches of at most 8 concurrent queries so a reconnect cannot serially block on all 1024 unresolved identities. Reconnect may ignore ordinary backoff to inspect current unresolved work, but it never includes entries already marked `recoveryRequired`. Failed or absent queries advance an exponential retry schedule from 1 s up to 60 s. After 64 automatic attempts or 24 h of unresolved age, the entry becomes `recoveryRequired` and automatic attempts stop; only an explicit operator `reconcilePending({ force: true })` may include it again. Reloaded durable records with implausible future clock state or impossible retry-time ordering also fail closed into `recoveryRequired` rather than silently delaying reconciliation.
6. Only a provenance-valid observation with a registered terminal status and `terminalObserved: true` removes the operation from the pending map and durable mirror.
7. Failure to persist an operation identity before dispatch fails closed: `transport.request()` is not called. Failure to durably remove a terminal entry also fails closed into `recoveryRequired` rather than silently forgetting the identity.

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

`ControlPlaneApp` collapses rapid duplicate logical actions while confirmation/acknowledgement is outstanding even across polling rerenders, exposes `aria-busy`, restores focus after confirmation/cancellation/failure, and can be externally mutation-blocked after snapshot/connectivity loss. When unresolved operations exist and the client exposes `reconcilePending`, the shell also exposes a read-only reconciliation control; explicit operator force executes only one bounded reconciliation batch and never resubmits a mutation. Confirmation is revalidated against the exact session/connection/runtime-generation/revision/digest view identity immediately before submission, so an offline/reconnect/stale transition that occurs while the dialog is open invalidates the request instead of crossing transport. The native confirmation host displays the exact immutable request in an accessible `<dialog>`.

The repository-owned browser host treats `offline` as an immediate mutation block, stops polling, advances a lifecycle generation fence and re-establishes an authenticated observation session after `online`, `UNAUTHENTICATED`, `NOT_CONNECTED` and BFCache/page-session resume. Snapshot responses are applied only when the captured transport/client/application and lifecycle generation are still current, so stale I/O cannot re-enable mutation or cross-bind an old transport response onto a new client. Recovery never replays unresolved mutations. Pending storage keys are SHA-256-bound to the authenticated bootstrap persistence namespace plus endpoint/protocol, so unresolved identities survive compatible manifest/path redeploys while principal/protocol domains stay isolated. Browser writer leases are committed only after a candidate runtime installs successfully; failed startup or persistence-domain switches release the candidate lease instead of wedging future recovery. A separate live runtime binding covers endpoint/protocol/manifest/basePath; if that binding drifts during a running page, recovery fails closed and requires full page reconstruction before the durable pending domain is reconciled.

A production host must still define localization and real authentication/session-expiry behavior, apply the generated CSP/security-header policy at the TLS/reverse-proxy boundary, and independently qualify the selected browser/screen-reader matrix against the real backend.

## 10. Local development

From repository root:

```bash
npm --prefix apps/hepta-control-ui run check
npm --prefix apps/hepta-control-ui run build
```

`check` performs JavaScript syntax validation and executes all control-ui tests.
`build` produces a static `apps/hepta-control-ui/dist/` with content-hashed ESM/CSS, rewritten hashed imports, top-level SRI, `asset-manifest.json`, `manifest.webmanifest` and `security-headers.json`, then syntax-checks every generated JavaScript asset. `dist/` remains a derived build artifact, not authoritative source or an independent deployment receipt.

The dedicated UI workflow additionally runs `npm run browser-e2e` in real Google Chrome at the exact PR source and deterministic synthetic merge. That source-owned smoke test covers exact confirmation, rapid duplicate-click collapse, focus restoration, offline confirmation invalidation, online/session-expiry recovery without mutation replay and the generated security-header surface; it is not a substitute for independent cross-browser/screen-reader real-backend accessibility acceptance.

## 11. Required regression cases

Every change touching the transport, projection or browser controller should
retain tests for:

- provider/secret fields cannot reach `readView()` or the browser view model;
- accessor-shaped required snapshot/module/transport fields fail closed without invoking getters;
- stale displayed revisions reject mutation;
- target revision and displayed revision remain separately bound;
- semantic digest is computed by the client from the final payload;
- reused operation identity with changed semantics fails closed;
- response-lost-after-accept becomes indeterminate and reconciles after
  reconnect without duplicate submission;
- cross-session/origin provenance cannot settle a pending operation, in-flight acknowledgement provenance remains bound across close/reconnect races, and reconciliation cannot overtake the original mutation dispatch;
- reload/crash recovery reconciles the durable operation identity without persisting the request payload or resubmitting mutation;
- reconnect reconciliation is capped to a bounded concurrent batch rather than serially waiting on the full pending capacity;
- persistence failure before dispatch prevents transport I/O, while a persistence failure after dispatch forces the returned acknowledgement to `indeterminate + recoveryRequired` instead of exposing stale optimistic state;
- `close()` invalidates an in-flight connection attempt so a late connect response cannot resurrect a closed client;
- rapid duplicate logical actions collapse to one request while awaiting confirmation/acknowledgement even across polling rerenders, and rerender restores focus;
- an offline/session transition while confirmation is open invalidates the request before transport;
- session expiry, online recovery and BFCache/page-session resume establish a fresh observation session without mutation replay;
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

- selected browser support matrix and independently retained evidence for the selected built artifact;
- real authenticated backend endpoint, authority/RBAC enforcement and protocol version negotiation;
- deployed TLS/session/reverse-proxy topology and any selected WebSocket bridge;
- verification that the generated CSP/security headers plus CSRF/CORS, cookie/token and origin policy are actually applied by the selected host;
- backend durable operation deduplication/reconciliation;
- accessibility E2E for keyboard and screen-reader users, including error focus
  recovery and stop request;
- browser secret scan and provider-payload leakage checks;
- disconnected/reconnect and response-loss fault injection;
- measured interaction/render limits against the selected host profile;
- rollback to a compatible client/backend protocol pair.

Do not translate passing source tests into activation, acceptance, promotion or
release authority.


## 13. Concrete browser host and endpoint contract

The repository-owned static host expects these same-origin endpoints beneath the bootstrap-selected `basePath`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ui-control/bootstrap` | Return the bounded endpoint/protocol/manifest/persistence namespace and polling configuration. |
| GET | `/api/ui-control/csrf` | Return a fresh bounded CSRF token used by every mutation-like POST. |
| POST | `/api/ui-control/connect` | Establish an authenticated runtime observation session. |
| GET | `/api/ui-control/snapshot` | Return the current bounded runtime snapshot. |
| POST | `/api/ui-control/request` | Carry the package-local operation/stop envelope to the separately authorized backend adapter. |
| POST | `/api/ui-control/reconcile` | Read-only reconciliation by immutable operation identity/digest/provenance. |
| POST | `/api/ui-control/close` | Close the current observation session. |

`SameOriginHttpTransport` sends credentials only to the current origin, refuses redirects, forbids cross-origin/userinfo/fragment URLs, requires HTTPS outside loopback, canonicalizes POST bodies before CSRF/network I/O, obtains a fresh CSRF token for POSTs, requires the exact `application/json` media type and enforces response/request byte bounds while streaming (including responses without `Content-Length`). Its timeout remains armed through full response-body consumption, and authenticated bootstrap uses the same bounded whole-response lifetime rather than an unbounded pre-session fetch. The browser client still has no authority to turn these HTTP endpoints into effect authority: the server adapter must authenticate, authorize, validate revisions/digests/scopes, deduplicate operation IDs and expose terminal observation separately.

The `persistenceNamespace` is intentionally supplied by the authenticated bootstrap rather than derived from user-visible identity. It must be opaque and principal/session-domain scoped so one authenticated principal cannot inherit another principal's pending-operation mirror on a shared browser profile.

# ui.control development guide

This document is the implementation-level guide for the Web control-plane
source root `apps/hepta-control-ui`. It is subordinate to the canonical module
registries and `docs/modules/ui.control/TECHNICAL.md`; it does not grant
runtime, effect, deployment, acceptance or release authority.

## 1. Source layout

| Path | Responsibility |
| --- | --- |
| `src/control.js` | Safe runtime projection and authority-free operator proposal construction. |
| `src/canonical.js` | Bounded deep snapshotting, deterministic canonical JSON and SHA-256 derivation. |
| `src/errors.js` | Stable UI/client error codes. |
| `src/runtime-client.js` | Session, coherent snapshot, request idempotency and reconciliation state machine. |
| `src/web-app.js` | Accessible DOM renderer and interaction controller. |
| `web/` | Static browser entrypoint and baseline CSP. |
| `scripts/build.mjs` | Dependency-free static build. |
| `scripts/serve.mjs` | Loopback-only development server. |
| `test/` | Node product-boundary and presentation tests. |

No file in this package owns backend facts or effect authority.

## 2. Commands

From the repository root:

```sh
npm --prefix apps/hepta-control-ui test
npm --prefix apps/hepta-control-ui run build
npm --prefix apps/hepta-control-ui run check
```

For local static serving:

```sh
npm --prefix apps/hepta-control-ui run dev
npm --prefix apps/hepta-control-ui start
```

The development server binds to `127.0.0.1:4173` by default. Set `PORT` to a
local alternative if required. It is intentionally not a production server.

## 3. Security invariants

The implementation must preserve all of the following:

1. UI code cannot mint canonical `OperationIntentV1` or any authority grant.
2. `readView()` exposes only projected module fields: `moduleId`, `status`,
   `revision`, `digest`, `ready` and explicit false authority flags.
3. Unknown backend/provider fields are never read by the projection path and
   therefore cannot become presentation data accidentally.
4. Runtime and outcome digests are non-zero lowercase SHA-256 values.
5. Mutating requests are bound to the currently displayed runtime revision.
6. Semantic digests are computed by the client from the complete sanitized
   request; callers cannot supply or override them.
7. An operation identity can be reused only for byte-equivalent canonical
   semantics.
8. A request enters the pending ledger before network I/O. Transport ambiguity
   becomes `indeterminate`, never "not sent" and never terminal success.
9. Reconciliation binds the operation to request kind, semantic digest,
   original session, original connection generation and runtime generation.
10. Only an observation delivered on the current authenticated session can
    reconcile local pending state.
11. The projected runtime view is capped at 1 MiB and at 4096 modules. Pending
    operations are capped at 1024.
12. The client retains at most two coherent projected snapshots for the current
    connection incarnation.

## 4. Runtime snapshot contract

`RuntimeClient.applySnapshot()` accepts this local transport shape:

```json
{
  "sessionId": "session.1",
  "connectionGeneration": 1,
  "generation": 7,
  "revision": 9,
  "digest": "<64 lowercase hex>",
  "modules": [
    {
      "moduleId": "runtime.agentd",
      "status": "ready",
      "revision": 9,
      "digest": "<64 lowercase hex>"
    }
  ]
}
```

Each module is passed through `projectRuntime()` before storage. Additional raw
module fields can exist at the transport boundary but are neither read nor
retained. Duplicate `moduleId` values, regressed generations, non-advancing
revisions and oversized projected views fail closed.

Supported presentation statuses are:

- `ready`
- `degraded`
- `quarantined`
- `recovering`
- `unavailable`

## 5. Operation proposal ownership

`buildOperationProposal()` creates `UiControlOperationProposalV1` only:

```json
{
  "kind": "UiControlOperationProposalV1",
  "operationId": "operation.1",
  "subjectId": "runtime.agentd",
  "action": "request_retry",
  "expectedRevision": 9,
  "authorityGranted": false,
  "directStoreWrite": false
}
```

The deprecated export `buildOperationIntent()` is only a compatibility alias
and returns the same proposal kind. It intentionally does **not** return
`OperationIntentV1`.

Allowed proposal actions are:

- `request_quarantine`
- `request_reconcile`
- `request_retry`
- `request_rollback`

A separately authorized backend/kernel adapter remains responsible for
constructing any canonical `OperationIntentV1`.

## 6. Runtime transport interface

The injected transport used by `RuntimeClient` must implement:

```js
transport.connect({ endpointId, protocolVersion, manifestDigest })
transport.request(method, payload)
transport.close({ sessionId })
```

The browser controller additionally requires:

```js
transport.subscribe({ sessionId, onSnapshot, onObservation, onError })
```

`subscribe()` resolves to an unsubscribe function. Subscription callbacks must
come from the authenticated deployment transport; `RuntimeClient` still checks
session and operation provenance before accepting their data.

A successful protocol-v1 `connect()` observation has exactly:

```json
{
  "authenticated": true,
  "sessionId": "session.1",
  "connectionGeneration": 1,
  "protocolVersion": 1
}
```

The transport is responsible for actual authentication. The UI only verifies
the authenticated observation and expected protocol version.

## 7. Mutating wire request

### 7.1 Operation request

The public UI call is:

```js
await client.submitRequest({
  displayedRevision: 9,
  intent: {
    operationId: "operation.1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 9,
  },
});
```

The client sanitizes that input and hashes these complete semantics:

```json
{
  "kind": "UiControlOperationRequestV1",
  "operationId": "operation.1",
  "subjectId": "runtime.agentd",
  "action": "request_retry",
  "expectedRevision": 9
}
```

### 7.2 Stop request

The public UI call is:

```js
await client.requestStop({
  operationId: "stop.1",
  scope: { "subjectId": "runtime.agentd" },
  displayedRevision: 9
});
```

The hashed semantics are:

```json
{
  "kind": "UiControlStopRequestV1",
  "operationId": "stop.1",
  "scope": { "subjectId": "runtime.agentd" },
  "expectedRevision": 9
}
```

### 7.3 Transport envelope

Both calls become `hepta.ui-control.transport-request.v1`:

```json
{
  "schema": "hepta.ui-control.transport-request.v1",
  "sessionId": "session.1",
  "connectionGeneration": 1,
  "runtimeGeneration": 7,
  "displayedRevision": 9,
  "requestKind": "operation",
  "operationId": "operation.1",
  "semanticDigest": "<internally derived SHA-256>",
  "request": { "kind": "UiControlOperationRequestV1" },
  "intent": { "kind": "UiControlOperationRequestV1" }
}
```

For stop requests, `requestKind` is `stop`, `request` contains the complete stop
request and `scope` contains the sanitized stop scope. The semantic digest is
computed from `request`; the transport cannot substitute different semantics
without creating an acknowledgement mismatch at the UI boundary.

A successful backend acknowledgement must echo exactly:

```json
{
  "accepted": true,
  "operationId": "operation.1",
  "semanticDigest": "<same digest>",
  "requestKind": "operation",
  "originSessionId": "session.1",
  "originConnectionGeneration": 1,
  "runtimeGeneration": 7
}
```

Unknown acknowledgement fields are rejected for protocol v1. An explicit
rejection uses the same shape with `accepted: false`.

## 8. Canonical semantic digest

`canonical.js` recursively snapshots plain JSON data, sorts object keys,
rejects accessors/symbol fields/non-safe numbers/excessive nesting and encodes
the result as UTF-8 canonical JSON. SHA-256 is computed with Web Crypto so the
same code is usable in Node 22 and modern browsers.

The request digest is never accepted from the caller. This closes the class of
bugs where a caller supplies one digest while sending a different intent or
stop scope.

## 9. Pending state machine and network ambiguity

The local state machine is:

```text
validated
   |
   v
sending  -- acknowledgement --> pending
   |                            |
   | transport ambiguity        | non-terminal observation
   v                            v
indeterminate <-----------------+
   |
   | authenticated terminal observation
   v
succeeded / failed / cancelled / rejected
```

The pending entry is created **before** `transport.request()`. Therefore a
server-side write followed by a lost response cannot disappear from local
state. Repeating the same operation ID and identical semantics returns the
existing acknowledgement and does not automatically send a second effect.

A reused operation ID with changed semantics fails closed.

## 10. Reconnect and reconciliation

Pending operations survive reconnect. A reconciliation observation must contain:

```json
{
  "observerSessionId": "session.2",
  "originSessionId": "session.1",
  "originConnectionGeneration": 1,
  "runtimeGeneration": 7,
  "requestKind": "operation",
  "operationId": "operation.1",
  "semanticDigest": "<same digest>",
  "status": "succeeded",
  "terminalObserved": true,
  "outcomeDigest": "<64 lowercase hex>"
}
```

`observerSessionId` must equal the currently authenticated session. The origin
fields must equal the stored pending provenance. Terminal success or failure
requires an outcome digest. Non-terminal observations cannot claim an outcome
digest or terminality.

Disconnect and `close()` retain pending operation identities; they do not imply
that external work was cancelled.

## 11. Stable error surface

`UiControlError.code` uses these values:

| Code | Meaning / expected UI reaction |
| --- | --- |
| `UNAUTHENTICATED` | Authentication failed; disable mutation and re-authenticate. |
| `INCOMPATIBLE_PROTOCOL` | Client/backend protocol mismatch; block mutation and require compatible deployment. |
| `STALE_SNAPSHOT` | Displayed state is not current; refresh before confirming. |
| `REQUEST_REJECTED` | Backend explicitly rejected the request; show rejection without claiming effect. |
| `BACKEND_UNAVAILABLE` | Transport failed or became ambiguous; keep pending work visible and reconcile. |
| `PROTOCOL_VIOLATION` | Identity/digest/provenance/status invariant failed; fail closed. |
| `CAPACITY_EXHAUSTED` | Local bounded resource ceiling reached; block additional work. |
| `NOT_CONNECTED` | Runtime session is absent. |
| `RECONCILIATION_REQUIRED` | Observation cannot be matched to known pending work. |
| `INVALID_INPUT` | Public caller input or canonical semantic construction failed validation. |

Product UI code should branch on `code`, not on English error text.

## 12. Browser application shell

`ControlPlaneWebApp`:

- renders with DOM `textContent` rather than interpolated HTML;
- exposes runtime stale/pending/indeterminate state visibly;
- disables mutating buttons while the view is stale;
- requires an injected `confirmAction()` callback before every mutation;
- routes all mutation through `RuntimeClient`;
- exposes keyboard-native `<button>` controls and status/alert live regions;
- preserves pending/indeterminate state when a recoverable transport error is shown;
- moves focus to the rendered alert after an error so keyboard/screen-reader users do not lose recovery context;
- never reads raw provider payload fields.

`web/index.html` supplies a restrictive baseline meta CSP. Production must also
set CSP as an HTTP response header. The static entrypoint expects a deployment
bootstrap at `globalThis.__HEPTA_CONTROL_BOOTSTRAP__` containing the transport,
endpoint manifest and confirmation/operation-ID functions. Do not put secrets
or bearer credentials in that object.

## 13. Authentication, CSRF and WebSocket deployment requirements

This source package intentionally does not choose the server authentication
mechanism. A production host must document and qualify all of the following:

- same-site/same-origin session behavior;
- server-side authorization for every mutating request;
- CSRF protection for cookie-authenticated HTTP mutation;
- strict `Origin` validation for WebSocket/SSE upgrade paths;
- no bearer token in query strings, DOM, localStorage or diagnostic logs;
- CSP response headers with an explicit `connect-src` allowlist;
- CORS disabled by default or constrained to named trusted origins;
- session revocation and reconnect behavior;
- no cached secret-bearing API responses.

The development server is not evidence for any of these production properties.

## 14. Test matrix

`npm test` executes the entire package test suite. Required cases currently
cover:

- safe field projection and secret/provider leakage resistance;
- non-zero digest validation;
- operator proposal ownership and closed input fields;
- canonical JSON bounds and ambiguity rejection;
- full intent/scope transmission;
- internally derived semantic digests;
- stale displayed revision rejection;
- immutable projected snapshots;
- timeout-after-write becoming indeterminate;
- no blind retry of an indeterminate operation;
- reconnect reconciliation with origin/current-session provenance;
- semantic drift under reused operation ID;
- non-terminal versus terminal outcome semantics;
- generation/revision regression and duplicate module rejection;
- 1 MiB projected view limit;
- 1024 pending-operation limit;
- typed authentication/protocol/input errors;
- malformed/unknown acknowledgement fields fail closed and retain uncertainty;
- browser rendering and confirmed interaction routing;
- recoverable error focus and indeterminate-state visibility.

CI must run the package-wide command rather than naming only one test file.

## 15. Production qualification still required

Source completion is not product completion. Before setting production,
activation or release claims true, the selected host must add evidence for:

1. real backend transport and subscription integration;
2. deployed authentication/authorization and CSRF/Origin controls;
3. CSP/CORS/security-header qualification on the real host;
4. browser support matrix and built artifact provenance;
5. keyboard-only and screen-reader end-to-end flows;
6. reconnect/packet-loss/timeout chaos tests against the real backend;
7. secret scanning and browser bundle inspection;
8. deployed performance measurements and interaction latency budgets;
9. operator acceptance, rollback rehearsal and release governance.

Until those gates are closed, this package remains an authority-free client and
presentation implementation, not independent production authority.

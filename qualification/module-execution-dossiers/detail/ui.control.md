# ui.control: implementation design

Parent: `docs/modules/ui.control/TECHNICAL.md`. Implementation guide:
`docs/modules/ui.control/DEVELOPMENT.md`. Lane: `LANE-B-RUNTIME`.
Status: coherent-view, authenticated runtime client and source browser shell
implemented; deployment security topology, real backend authority and
independent product acceptance remain external gates. Common requirements:
`../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and
package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-control-ui`.
Packages: `UI-V5`.

Operation signatures below describe the target contract. Section 8 identifies
the implemented native subset and remaining deployment integration. Preserve
existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`read_view(snapshot_cursor) -> RuntimeView`;
`submit_request(intent, displayed_revision, session) -> RequestAcknowledgement`;
`request_stop(scope, session) -> StopAcknowledgement`.

The source client now carries the final authority-free proposal/stop scope over
the transport and computes its semantic digest locally. The UI may request or
display a decision but cannot issue capabilities, select its own authoritative
candidate or directly mutate domain stores. `UiOperationProposalV1` is not
`kernel.operations`' `OperationIntentV1`.

## 3. State records and transaction design

Only presentation/session-local state: current authenticated connection,
coherent current/prior snapshot, bounded pending operation identities and
browser presentation state. Server facts remain authoritative. A stale view is
visibly marked stale and mutating browser controls are disabled. Sensitive
action confirmation binds the exact final target, target revision, displayed
revision and scope/payload before submission.

Pending work is inserted before transport I/O. A response-loss or backend
transport failure therefore leaves an `indeterminate` local operation instead of
erasing it. Reconnect queries the injected backend reconciler by immutable
operation identity/digest/provenance; it does not re-submit the operation.

## 4. Deterministic algorithm and scheduling

Negotiate client/backend version; accept only session/generation-bound bounded
snapshots; project every module through the display allowlist; reject mixed or
regressing generations/revisions; render stale/pending/indeterminate/failed
states; submit the final bounded proposal/scope; reconcile by request identity
and full session/origin provenance. Queue acknowledgement never establishes a
terminal external effect.

## 5. Capacity and performance profile

Current source limits are enforced in `apps/hepta-control-ui/src/protocol.js` and
`runtime-client.js`: projected view <= 1 MiB, request/scope <= 64 KiB,
canonical depth <= 32, canonical nodes <= 4096, modules <= 4096 and pending
operations <= 1024. These are client limits, not host-performance measurements.
UI timing is not hardware-stop timing.

## 6. Concrete verification cases

- UI-01: incompatible protocol version returns `INCOMPATIBLE_PROTOCOL` and
  prevents mutation.
- UI-02: stale displayed revision fails closed; target revision and displayed
  revision remain separately bound.
- UI-03: response-loss-after-accept remains indeterminate and reconnect
  reconciles the retained ID without duplicate submission.
- UI-04: the source browser shell exposes live status/alert semantics and stale
  controls are disabled; full keyboard/screen-reader product acceptance remains
  an external gate.
- UI-05: secret/provider fields are eliminated before `readView()` and are
  re-projected at the browser view-model boundary.
- UI-06: observation provenance mismatch cannot settle pending work.

These source tests are not independent deployment-acceptance receipts.

## 7. Integration, rollback and capability ceiling

Web and native clients share authority-free request semantics. Human override
must be authenticated and scoped; hardware emergency stop remains independent.
Rollback preserves compatible client/backend versions and does not downgrade
authentication. No source test, generated dossier or UI acknowledgement grants
activation, acceptance, merge, promotion or release authority.

## 8. Current native implementation

- **Implemented runtime entrypoints:** `readView`, `submitRequest`,
  `requestStop`, reconnect reconciliation and typed error mapping in
  `apps/hepta-control-ui/src/runtime-client.js`.
- **Protocol boundary:** bounded canonical snapshots, client-owned semantic
  SHA-256 and stable `UiControlError` codes in `src/protocol.js`.
- **Projection boundary:** `projectRuntime` and authority-free
  `buildOperationProposal` in `src/control.js`; the compatibility
  `buildOperationIntent` name no longer emits `OperationIntentV1`.
- **Browser source shell:** `ControlPlaneApp` in `src/browser-app.js`, with
  stale-view mutation blocking, final immutable confirmation and text-only DOM
  rendering.
- **State/recovery:** authenticated session, current/prior coherent snapshot, maximum 1024 unresolved identities, optional bounded durable identity mirror with no request payload, immutable in-flight provenance, exponential reconciliation backoff and explicit `recoveryRequired` after the automatic ceiling. Snapshot/module/transport required fields are consumed as own data rather than invoking accessor-shaped ingress.
- **Browser/deployment source boundary:** `SameOriginHttpTransport`, authenticated bootstrap, principal/domain-bound pending-store key, accessible native confirmation, content-hashed/SRI static artifact and generated security-header policy. The host immediately blocks mutations offline and re-establishes observation sessions after online/session-expiry/BFCache resume without replaying mutations.
- **Source tests:** `test/control.test.js`, `test/runtime-client.test.js`, `test/browser-app.test.js`, `test/protocol-regression.test.js` and `test/hardening.test.js`; package commands are `npm run check`, `npm run build` and CI-owned real-Chrome `npm run browser-e2e`.
- **CI:** `.github/workflows/hepta-ui-control.yml` verifies exact source and a deterministic synthetic merge, builds the static artifact and runs it in real Google Chrome against a bounded mock backend, including duplicate-click, focus, offline-confirmation invalidation and session-recovery checks; Lane-B also invokes the package check/build.
- **Remaining work:** bind and independently qualify the real authenticated backend authority/RBAC/effect adapter; deploy the selected TLS/session/reverse-proxy topology and prove generated CSP/security headers plus CSRF/CORS/cookie policy are applied; perform independent selected-browser/screen-reader E2E against that real backend and collect deployment/performance evidence.

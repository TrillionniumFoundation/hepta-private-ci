# ui.control: implementation design

Parent: `docs/modules/ui.control/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: coherent-view and authenticated-transport client boundary implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-control-ui`.
Packages: `UI-V5`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`read_view(snapshot_cursor) -> RuntimeView`; `submit_request(intent, displayed_revision, session) -> RequestAcknowledgement`; `request_stop(scope, session) -> StopAcknowledgement`. Use generated protocol clients and backend-authenticated operations. The UI may request or display a decision but cannot issue capabilities, select its own displayed candidate or directly mutate domain stores.

## 3. State records and transaction design

Only presentation/session-local state: connection generation, current view revision, pending request IDs, accessibility focus and explicitly scoped preferences. Server facts remain authoritative. A stale view is visibly marked stale; optimistic presentation never becomes a terminal-effect record. Sensitive action confirmation binds the final displayed target/payload/revision.

## 4. Deterministic algorithm and scheduling

Negotiate client/backend version; subscribe to bounded snapshots; reject mixed generations; render state with pending/indeterminate/failed distinctions; route authenticated user intents to the owner; reconcile responses by request ID. Disconnect cancels pending UI affordances but does not assume an external action was cancelled. Emergency controls remain usable without model cooperation.

## 5. Capacity and performance profile

Pilot view <= 1 MiB subject to backend limits, retained events <= 1000 per view, rendering work scheduled in bounded batches. Measure interaction/stop request latency, disconnected behavior and keyboard/screen-reader paths; UI timing is not hardware-stop timing.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- UI-01: incompatible protocol version blocks mutating controls with an explicit explanation.
- UI-02: stale confirmation cannot authorize a changed target or payload.
- UI-03: reconnect reconciles pending IDs without duplicate requests.
- UI-04: keyboard-only and screen-reader users can inspect uncertainty, request stop and recover focus after errors.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Web and native clients share the same runtime contracts and state meanings. Human override is authenticated and scoped; hardware emergency stop remains independent. Rollback preserves compatible client/backend versions and does not downgrade authentication.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `readView` in [apps/hepta-control-ui/src/runtime-client.js](../../../apps/hepta-control-ui/src/runtime-client.js); `submitRequest` in [apps/hepta-control-ui/src/runtime-client.js](../../../apps/hepta-control-ui/src/runtime-client.js); `requestStop` in [apps/hepta-control-ui/src/runtime-client.js](../../../apps/hepta-control-ui/src/runtime-client.js). Coherent-view and authenticated-transport client boundary implemented.
- **State and recovery:** The client retains session, coherent generation/revision snapshot and at most 1024 pending requests in memory; stale revisions reject and terminal statuses require terminal observations from the injected transport.
- **Source tests:** [apps/hepta-control-ui/test/runtime-client.test.js](../../../apps/hepta-control-ui/test/runtime-client.test.js), [apps/hepta-control-ui/test/control.test.js](../../../apps/hepta-control-ui/test/control.test.js). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [apps/hepta-control-ui/README.md](../../../apps/hepta-control-ui/README.md), [docs/modules/ui.control/IMPLEMENTATION_MAP.json](../../../docs/modules/ui.control/IMPLEMENTATION_MAP.json).
- **Remaining work:** Package the chosen web framework and deployed authentication/CSP/CSRF topology; verify actual backend authority and accessible end-to-end behavior.

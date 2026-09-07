# ui.control: implementation design

Parent: `docs/modules/ui.control/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-control-ui`.
Packages: `UI-V5`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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

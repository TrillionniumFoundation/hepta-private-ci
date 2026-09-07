# ui.native: implementation design

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-native`.
Packages: `UI-NATIVE-1-SHELL`, `UI-V5`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`connect_runtime(endpoint_manifest, session) -> NativeSession`; `render_runtime_view(view_generation) -> PresentationState`; `request_platform_capability(action, user_intent) -> PlatformDecision`; `apply_shell_update(selected_package, evidence) -> UpdateDisposition`. Use the same generated runtime contract as the web UI; native OS permissions are separate from Hepta effect grants.

## 3. State records and transaction design

Ephemeral shell/window/session state and owner-approved local settings only. Secure OS storage may hold opaque session references through the designated secret boundary; it is not a new secret authority. Update metadata binds signed shell artifact, platform/architecture, compatible backend version and rollback predecessor. No model-generated package is installed by the UI alone.

## 4. Deterministic algorithm and scheduling

Validate endpoint identity and client compatibility; establish scoped session; render coherent views; route all domain mutations through backend owners. On crash/restart, reconnect and reconcile pending requests. Shutdown must not erase unobserved effects. Update only after independent selection and an explicit compatible process restart, preserving user recovery and accessibility.

## 5. Capacity and performance profile

Pilot bounded event/view caches as in ui.control; platform-specific startup/RSS/interaction budgets are frozen per target OS. Limit automatic reconnect and update retries. No broad filesystem or device permission is acquired merely to improve UX.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- NATIVE-01: native and web clients render the same pending/indeterminate/terminal state semantics.
- NATIVE-02: OS permission denial or revocation prevents the corresponding operation.
- NATIVE-03: crash/exit/restart reconciles existing request IDs without duplicate effects.
- NATIVE-04: unsigned/incompatible update is refused and a compatible signed predecessor remains recoverable.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Keep native lifecycle and accessibility adapters distinct from backend authority. The module may surface stop/takeover but cannot override backend scope. Rollback tests cover shell/backend protocol compatibility and secure-session revocation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

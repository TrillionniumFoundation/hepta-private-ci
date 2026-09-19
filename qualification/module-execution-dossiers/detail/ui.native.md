# ui.native: implementation design

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: native shell connection, capability and update driver boundary implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-native`.
Packages: `UI-NATIVE-1-SHELL`, `UI-V5`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

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

## 8. Current native implementation

- **Implemented entrypoints:** the canonical implementation is Rust-only. The product state machine is [apps/hepta-native/src/runtime.rs](../../../apps/hepta-native/src/runtime.rs), the OS adapter is [apps/hepta-native/src/platform.rs](../../../apps/hepta-native/src/platform.rs), signed grant/endpoint verification is [apps/hepta-native/src/security.rs](../../../apps/hepta-native/src/security.rs), signed update activation is [apps/hepta-native/src/updater.rs](../../../apps/hepta-native/src/updater.rs), and the named native application bootstrap is [apps/hepta-native/src/main.rs](../../../apps/hepta-native/src/main.rs).
- **State and recovery:** Operations are keyed by session id + session generation + operation id. The durable journal fsyncs `Invoking` before OS entry; retry/restart reconciles uncertain records instead of replaying them. `close` and reconnect preserve pending records while session fencing prevents receipt reuse across incarnations.
- **Security boundary:** Rust computes the final `PlatformPayload` digest, verifies a short-lived Ed25519 grant for the exact session/operation/action/payload, and reloads the trusted-key file before each effect so signing-key revocation is observed without shell restart. Endpoint identity and loopback gateway bearer capability are separately bound through a signed endpoint manifest and OS keyring. Update activation re-verifies signature/channel/target tuple, the staged package digest and the currently installed predecessor digest before replacement.
- **Platform/UI:** `eframe 0.36.2` / `egui` + AccessKit is selected. Product targets are Windows 11 x86_64, macOS 14+ arm64/x86_64 and Ubuntu 24.04 x86_64. The native window exposes runtime, operation, update and accessibility state; keyboard focus, HiDPI and English/Chinese shell copy are implemented. Local policy denial is testable before OS entry; terminal success is not fabricated where the OS has no trustworthy observation API.
- **Source tests:** [apps/hepta-native/tests/runtime.rs](../../../apps/hepta-native/tests/runtime.rs), [apps/hepta-native/tests/security_updater.rs](../../../apps/hepta-native/tests/security_updater.rs), [apps/hepta-native/tests/backend.rs](../../../apps/hepta-native/tests/backend.rs), and [apps/hepta-native/tests/session_store.rs](../../../apps/hepta-native/tests/session_store.rs). [.github/workflows/hepta-native-rust.yml](../../../.github/workflows/hepta-native-rust.yml) runs exact-head Linux checks plus Windows/macOS/Linux merge-candidate build/test/package/self-test and emits unsigned qualification receipts. Test paths are identities until the exact candidate run is observed.
- **Implementation references:** [apps/hepta-native/README.md](../../../apps/hepta-native/README.md), [apps/hepta-native/DEVELOPMENT.md](../../../apps/hepta-native/DEVELOPMENT.md), and [docs/modules/ui.native/IMPLEMENTATION_MAP.json](../../../docs/modules/ui.native/IMPLEMENTATION_MAP.json).
- **Remaining external work:** production signing/notarization/distribution trust roots, installed Windows AppUserModelID notification identity, real target-host OS permission/revocation observations where applicable, installed-package restart/rollback evidence, screen-reader/accessibility acceptance, operator acceptance, promotion and release.

### Candidate closure update — Rust product shell

This candidate has retired the injected JavaScript native boundary; `src/main.rs` composes the real Rust runtime, platform, security, keyring and updater components into the eframe application lifecycle. The runtime preserves uncertain effects across restart and never converts queue/launch acceptance into terminal success. The updater uses a separate activator and keeps the signed predecessor recoverable until the new binary confirms its digest.

The repository CI deliberately publishes **unsigned development artifacts**. Its receipts bind the tested source/merge identity and binary hashes but explicitly record production signing, independent accessibility acceptance and release authority as false. External trust material and target-host acceptance are not synthesized by repository tests.

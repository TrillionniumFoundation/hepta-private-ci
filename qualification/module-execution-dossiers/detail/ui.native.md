# ui.native: implementation design

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: selected Rust native application host, Agentd composition, durable operation reconciliation, FinalUse-bound platform effects, signed portable updater and accessibility-oriented UI are implemented in source; exact-candidate execution and platform-specific external acceptance remain listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-native`, `codex-rs/hepta-native-app`.
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

- **Selected product host:** [codex-rs/hepta-native-app](../../../codex-rs/hepta-native-app/README.md), an `eframe/egui 0.36.2` Rust desktop application. `hepta-native` is the named product caller; `hepta-native-updater` is a narrow post-exit replacement helper.
- **Runtime composition:** [src/backend.rs](../../../codex-rs/hepta-native-app/src/backend.rs) wraps the repository's real `AgentdClient`. Connection and coherent-view reads traverse the bounded Agentd JSON-over-UDS contract for health, session ingress, capability negotiation, lifecycle and event cursors. The host does not create a second execution spine.
- **Runtime correctness:** [src/runtime.rs](../../../codex-rs/hepta-native-app/src/runtime.rs) keys effects by `(session_id, session_generation, operation_id)`, persists `Pending` before adapter entry, fences cross-session reuse, returns existing terminal receipts idempotently, and reconciles `Pending/Indeterminate` state without redispatch. Restart recovery reloads the same journal.
- **Durable journal:** [src/persistence.rs](../../../codex-rs/hepta-native-app/src/persistence.rs) uses the OS keyring for a bounded index and per-operation records. It stores identity/resource metadata and canonical payload digests, not full clipboard/notification payloads. If the keyring is unavailable, the UI remains read-only and effect insertion fails before OS dispatch.
- **Trusted effect boundary:** [src/platform.rs](../../../codex-rs/hepta-native-app/src/platform.rs) consumes the canonical `FinalUseAuthority`. A `SignedFinalUseGrant` must match the exact final request and is converted to a single-use `VerifiedUseToken` immediately around one OS adapter call. Clipboard/open/reveal/notification adapters cannot mint their own authority.
- **Updater:** [src/update.rs](../../../codex-rs/hepta-native-app/src/update.rs) verifies a pinned Ed25519 signature over candidate/predecessor digests, OS/architecture, Agentd protocol, independent selector/generator identities and bounded restart args. On Unix it stages privately, retains the predecessor, runs the replacement's real Agentd `--post-update-probe`, and restores the predecessor on probe failure.
- **UI/accessibility:** [src/ui.rs](../../../codex-rs/hepta-native-app/src/ui.rs) provides Runtime, Operations, Updates and Settings pages, keyboard shortcuts, explicit semantic labels, AccessKit-enabled native widgets, HiDPI-native viewport scaling and English/Chinese locale selection.
- **Compatibility boundary:** [apps/hepta-native](../../../apps/hepta-native/README.md) remains a JS contract/fail-closed compatibility fixture while callers migrate. It is no longer the selected product-host implementation.
- **Focused product tests:** Rust source tests cover retry without duplicate dispatch, crash/restart reconciliation without replay, cross-session fencing, coherent-view digest drift, missing-authority denial before OS effect, real Agentd UDS composition, update-signature tampering and failed-probe rollback.
- **Platform matrix:** Linux is Tier 1 for host/effects/portable updater. macOS is Tier 1 for host/effects, with notarized `.app` updating still release-gated. Windows 11 is a read-only preview until the kernel FinalUse durable store has a hardened Windows implementation; this presentation module must not bypass that gate.
- **Remaining repository-controlled work:** harden `codex-hepta_contracts::FinalUseAuthority` durable state on Windows before enabling effects/update there; land current `Cargo.lock`; make the exact-candidate three-platform qualification workflow green.
- **Remaining external evidence:** macOS signing/notarization, Windows Authenticode/MSIX signing/installer acceptance, packaged screen-reader acceptance, and independent operator acceptance/promotion/release.

The source implementation intentionally distinguishes those remaining evidence gates from the already-materialized Rust host. A successful source test is not a notarization, installer, screen-reader or release receipt.

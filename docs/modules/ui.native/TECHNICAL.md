# ui.native technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `ui.native`

**Owner:** `ui-platform`

**Deputy:** `accessibility`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `UI-NATIVE-1-SHELL`

This stable document is the implementation guide for `ui.native`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Provide the native shell and accessibility layer over the same typed runtime boundary.

The primary owner `ui-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `accessibility` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `presentation`, kind `native`, state model `ephemeral` and architecture role `presentation` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `apps/hepta-native`
- `codex-rs/hepta-native-app`

Existing declared roots at this exact source snapshot:

- `apps/hepta-native`
- `codex-rs/hepta-native-app`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The selected Rust desktop host is [codex-rs/hepta-native-app](../../../codex-rs/hepta-native-app/README.md). Its production entrypoints are `hepta-native` and the narrow `hepta-native-updater`; `AgentdBackend` composes the existing Agentd UDS contract and `NativeShellRuntime` owns only presentation/session/effect-journal state. The older [apps/hepta-native/src/native.js](../../../apps/hepta-native/src/native.js) and `shell-runtime.js` remain compatibility/contract fixtures while callers migrate; they are no longer the selected product-host implementation.

Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/ui.native.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.native.md) for the exact implemented subset and remaining external qualification work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.agentd`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `authority_issuance`
- `direct_store_write`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `eframe/egui native shell` with AccessKit semantics
- `AgentdBackend` over the existing bounded JSON-over-UDS client
- `NativeShellRuntime` session/view/operation state machine
- `KeyringOperationStore` durable Pending/Indeterminate journal
- `SecurePlatformAdapter` consuming kernel `FinalUseAuthority`
- `SignedUpdater` plus the post-exit `hepta-native-updater` helper
- accessibility, keyboard, HiDPI and locale presentation adapters

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

None.

Consumed contracts:

- `DomainRead::runtime_health_observationV1`
- `ModulePort::runtime.agentd::ui.native`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `runtime_health_observation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/ui.native.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. The selected Rust host keys every effect by `(session_id, session_generation, operation_id)`, persists `Pending` before adapter entry, fences reuse across sessions, and reconciles `Pending/Indeterminate` records without redispatch. Exact duplicate terminal identities return their receipt; a changed payload under the same identity conflicts.

Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.native.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/ui.native.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.native.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

The Rust OS-effect adapter consumes the canonical `codex_hepta_contracts::FinalUseAuthority`: an externally signed `SignedFinalUseGrant` is checked against an exact session/action/resource/revision/payload binding, converted to a single-use `VerifiedUseToken`, and consumed immediately around one adapter call. The UI and adapter hold no signing private key and cannot mint the token they consume. The secure operation journal stores bounded identity/resource metadata and payload digests, not clipboard text or notification bodies.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.native.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [apps/hepta-native/src/native.js](../../../apps/hepta-native/src/native.js) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The selected host is a Rust `eframe/egui 0.36.2` desktop application with AccessKit semantics. Linux is the Tier-1 implementation for the complete FinalUse-bound effect path and signed portable-binary updater; macOS is Tier-1 for the shell/effect path while notarized `.app` replacement remains a release gate; Windows 11 is a read-only preview until the kernel `FinalUseAuthority` durable state owner has a hardened Windows implementation. The Windows gate must not be bypassed in this presentation module.

Code-signing identities, macOS notarization, Windows Authenticode/MSIX identities, packaged screen-reader acceptance and operator release decisions remain external evidence. Source code cannot self-certify those facts.

Current operating and state-format references:

- [docs/modules/ui.native/IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-native-app/src/runtime.rs](../../../codex-rs/hepta-native-app/src/runtime.rs): retry without duplicate dispatch, restart reconciliation without replay, cross-session fencing, coherent-view digest drift.
- [codex-rs/hepta-native-app/src/backend.rs](../../../codex-rs/hepta-native-app/src/backend.rs): real bounded Agentd JSON-over-UDS composition across health, ingress, capabilities, lifecycle and events.
- [codex-rs/hepta-native-app/src/platform.rs](../../../codex-rs/hepta-native-app/src/platform.rs): missing FinalUse authority rejects before OS effect.
- [codex-rs/hepta-native-app/src/update.rs](../../../codex-rs/hepta-native-app/src/update.rs): signed-manifest tamper rejection and failed post-update-probe predecessor restoration.
- [apps/hepta-native/test/native.test.js](../../../apps/hepta-native/test/native.test.js) and [shell-runtime.test.js](../../../apps/hepta-native/test/shell-runtime.test.js) remain compatibility-boundary tests.

From `codex-rs`, run `cargo test -p codex-hepta-native-app`, `cargo check -p codex-hepta-native-app --all-targets`, and `cargo clippy -p codex-hepta-native-app --all-targets -- -D warnings`. The commands are invocations, not stored pass receipts. Inspect exact-candidate CI for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.native.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `UI-NATIVE-1-SHELL`
- `UI-V5`

The bootstrap package is `UI-NATIVE-1-SHELL`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target roots exist, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. The Rust binary now supplies a named product caller, but production/deployment completion remains false until the current candidate passes the platform qualification workflow and the external signing/accessibility gates applicable to that platform.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `ui.native`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `UI-NATIVE-1-SHELL`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `ui-platform` / `accessibility`.
- Allowed write paths:
- `apps/hepta-native/**`
- `codex-rs/hepta-native-app/**`
- Development predecessors:
- `P0.8B-READINESS`
- `UI-V5`
- Activation predecessors:
- `P0.8B-READINESS`
- `UI-V5`
- Required deliverables:
- `exact_source_identity`
- `static_verification`
- `focused_tests`
- `clean_worktree`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `UI-V5`

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `independent_source_preparation`.
- Owner/deputy: `ui-platform` / `accessibility`.
- Allowed write paths:
- `apps/hepta-control-ui/**`
- `apps/hepta-native/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- Activation predecessors:
- `P0.8B-READINESS`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `ui.native` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `ui.native` is implemented by work package `UI-NATIVE-1-SHELL` in:

- `apps/hepta-native`
- `codex-rs/hepta-native-app`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

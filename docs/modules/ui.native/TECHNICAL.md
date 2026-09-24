# ui.native technical development guide

**Module:** `ui.native`  
**Owner / deputy:** `ui-platform` / `accessibility`  
**Primary lane:** `LANE-B-RUNTIME`  
**Candidate:** `work/ui-native-current-source-20260925`  
**Status:** current-source port and qualification candidate; not production accepted.

## 1. Source identity

The candidate starts at main `7ddbfac88525196e7a4b31387ceae194958275f5` and
materializes the actual Rust app root from historical #830
`3198549d80d6c59887b82e2c50018ab818217c53`. No history-only merge is treated as
source delivery. Existing current kernel/runtime owners are not replaced.

The executable development guide is
[`apps/hepta-native/DEVELOPMENT.md`](../../../apps/hepta-native/DEVELOPMENT.md).
The old guide is retained under an explicitly historical filename. Its old
Windows authority and product-closure statements are not current claims.

## 2. Mission, ownership and non-goals

Provide native presentation and bounded local OS adapters over existing
runtime owner contracts. The UI cannot issue authority, write domain stores,
select its own generated update, or turn CI evidence into release authority.
Canonical module/contract/ownership registries remain normative. Local shell
journal records are not backend domain facts or a second execution spine.

## 3. Current implementation and interfaces

`apps/hepta-native/src/main.rs` is the candidate desktop bootstrap.
`runtime.rs` implements `connect_runtime`, `refresh_runtime_view`,
`request_platform_capability` and `reconcile_pending`. `updater.rs` implements
signed staging, activation, recovery and installed-binary confirmation.
`backend.rs`, `platform.rs`, `security.rs`, `session_store.rs`, and `ui.rs`
provide the concrete adapter and presentation components.

The JavaScript shell driver is not the current product entrypoint in this
candidate. Global source bindings are refreshed after the reviewed adaptations
and lock are committed, rather than pointing at removed JavaScript symbols.

## 4. Concurrency and durability

The Rust runtime owns its mutable request values and session/view state.
Operation identity and immutable semantics include session incarnation, ID,
endpoint, subject, displayed revision, action, serialized payload and grant.
`Prepared` and `Invoking` are durable before platform entry. Uncertain effects
reconcile without blind replay. Terminal observations are immutable; duplicate
recovered keys and unknown journal fields are rejected by the reviewed port.
Persistence failure fences that owner until reopen. Terminal deletion is not
allowed without a durable deduplication retirement mechanism.

## 5. Authorization

Consume current `kernel.authority` final-use types and synchronous-effect fence.
OS permission remains an additional ceiling, never authority. Keep revocation
and exact payload checks before actual use. Do not restore obsolete owner
implementations to satisfy a desktop platform build.

## 6. Updates and recovery

Use independently signed, stable-channel manifests, package/target digests,
selector/generator separation and exact installed predecessor admission.
The separate updater shares a transition lock with GUI update mutations.
Pending recovery verifies its admitted signature; rollback cannot overwrite an
unrelated current binary. Unresolved activation/recovery cannot be erased by
`clear_pending`. Confirmation binds the actual installed target and its digest.
The detailed state machine and unqualified failure cuts are in DEVELOPMENT.md.

## 7. Product caller and remaining integration

Current main's gateway does not yet provide the keyring-authenticated contract
required by the recovered Rust backend. This is a repository-controlled
integration blocker. A fixture backend or operator-written fake health result
cannot establish ordinary daemon/client product composition.

Current non-Unix kernel final-use persistence, bounded launcher waits, UI-thread
responsiveness, safe terminal retirement, full pending-state/path trust and
physical installed-package lifecycle are not yet accepted. These are not all
external certificate issues.

## 8. Verification

The current-source workflow first commits the adapted sources and native lock,
then runs exact-head and deterministic-merge matrices on Linux/macOS/Windows.
It records actual checked-out SHA/tree, source candidate, base and outcomes.
Missing, failed or skipped steps cannot establish a pass. Strict lint and native
tests have independent feedback. Generated fingerprints prove file identity,
not behavioral correctness.

The added journal regression source covers conflicting terminals, endpoint
identity, duplicate replay snapshots, unknown fields, I/O failure isolation,
retained deduplication, session generations and monotonic dispatch phases.
Existing Rust runtime/security/update tests remain required. Detailed commands
are in DEVELOPMENT.md and use `--locked` after lock preparation.

## 9. Accessibility, performance and external gates

AccessKit presence is not screen-reader acceptance. Actual packaged keyboard
navigation, screen-reader state, IME, Chinese rendering, multi-monitor DPI,
startup/RSS/latency and long-running resource ceilings require observed runs.
Independent signing/notarization, release-channel custody and operator
acceptance remain separately governed and false until independently observed.

## 10. Completion vocabulary

Source location, implemented mapping, product composition, exact-candidate
qualification, physical host acceptance and release are separate states.
This candidate must not claim productionImplementation, productExecutionProved,
activation or release merely because Rust files and workflows are present.

# ui.native technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `ui.native`  
**Owner / deputy:** `ui-platform` / `accessibility`  
**Lane:** `LANE-B-RUNTIME`  
**Candidate:** `work/ui-native-current-source-20260925`  
**Status:** source-port and qualification candidate; not production accepted.

## 1. Identity, mission and ownership

Provide native presentation and bounded local platform adapters over existing
runtime owner contracts. The source owner is `ui-platform`; `accessibility`
reviews interaction and acceptance. No UI change transfers another module's
state, authority issuance, domain write, selection or release responsibility.

## 2. Source binding and implementation status

The exclusive application root is `apps/hepta-native`. This candidate starts at
main `7ddbfac88525196e7a4b31387ceae194958275f5` and restores the actual Rust app
files from historical #830 `3198549d80d6c59887b82e2c50018ab818217c53`. Current
kernel, gateway and runtime owner sources are retained. A history-only merge
is not implementation delivery.

Read the [current development guide](../../../apps/hepta-native/DEVELOPMENT.md)
for concrete configuration and remaining integration. The separately named
historical guide is reference, not current Windows or product acceptance.
`CURRENT_SOURCE.json` binds native source, lock and documentation bytes;
qualification receipts separately bind checked-out commit, tree and merge base.

## 3. Boundary, responsibilities and non-goals

The UI may keep bounded shell presentation and operation-recovery records.
It cannot issue effect grants, write backend domain stores, select its own
updates or reinterpret fixture receipts as production evidence. Backend facts
continue to flow through existing runtime owners. Missing authority and
unsupported persistence fail closed, rather than selecting a weaker owner.

## 4. Internal architecture and component decomposition

`src/main.rs` bootstraps the executable; `ui.rs` presents native controls.
`backend.rs` consumes signed endpoint metadata and keyring bearer credentials.
`session_store.rs` stores opaque session references, not provider credentials.
`runtime.rs` owns session/view validation and operation lifecycle. `journal.rs`
owns local dispatch persistence. `security.rs` adapts the current kernel final-use
boundary. `platform.rs` implements narrow local policy and OS calls. `updater.rs`
and the independent updater binary implement staged activation and recovery.

## 5. Contracts, ports and compatibility

The registered upstream contract remains `ModulePort::runtime.agentd::ui.native`
and the read-only `DomainRead::runtime_health_observationV1`. The Rust backend
requires authenticated gateway health and versioned runtime state. The current
main gateway lacks that bearer-authenticated product contract: ordinary connected
startup is still an integration blocker, not an external certificate issue.

Candidate entrypoints are `connect_runtime`, `refresh_runtime_view`,
`request_platform_capability` and `reconcile_pending`. Signed update staging is
`UpdateManager::verify_and_stage`. Preserve rejected, indeterminate, failed and
succeeded meanings across native and web clients. Do not infer success from queue
acceptance or process launch alone.

## 6. Data authority, persistence and migrations

The journal retains local shell dispatch facts only; canonical backend domains
remain with their authoritative writers. Each operation binds session incarnation,
operation ID, endpoint, subject, displayed revision, action, serialized payload,
final-use binding and grant digest. Reusing an identity with changed semantics
is rejected. Journal schema is closed; duplicate recovered identities are errors.

Terminal receipts cannot be rewritten. Destructive terminal cleanup is refused
until a durable retirement/deduplication frontier exists. This preserves safety
but does not yet solve long-running retention capacity. New schema migration and
old-backup anti-rollback acceptance require separate fault evidence.

## 7. Runtime, concurrency and transaction model

The runtime receives owned Rust request values and mutably borrows its state;
it does not re-read mutable JavaScript input after a permission await. It writes
Prepared and then Invoking durably before entering the platform adapter.
Concurrent owners are fenced by the journal lock. Same-generation identity and
cross-generation isolation are tested independently.

Current kernel `FinalUseAuthority` remains the authorization owner. The adapter
uses its synchronous-effect fence at physical effect entry. OS permission is an
additional ceiling. Bounded launcher waits, full path-race protection and runtime
revocation behavior on every supported host remain qualification obligations.

## 8. Failure semantics, recovery and rollback

Invoking/Indeterminate records reconcile without blind re-invocation. Journal
persistence failure poisons that owner until reopen and reconciliation. A failed
write cannot be treated as a known no-effect outcome or used to replay an action.

Update manifests bind stable channel, target tuple, package and predecessor
digests, compatibility and independent selector. GUI transitions and the updater
helper share a transition lock. Reopened pending recovery authenticates its
manifest. Rollback refuses an installed binary unrelated to the admitted candidate
or predecessor; failed recovery remains durably RecoveryRequired. Confirmation
binds the actual installed target and digest. Unresolved activation/recovery
cannot be erased by the public clear-pending operation.

## 9. Security, privacy and threat controls

Keep private signing keys out of UI source, native state and general logs.
The UI consumes independent final-use grants and never mints an equivalent local
authority. Matching caller-supplied digests are not authorization. Preserve current
kernel signature, epoch, expiry, nonce and revocation checks at final use.

Payload bodies are not persisted merely to simplify reconciliation. Path roots,
clipboard and notification permissions remain explicit local ceilings. Hostile
symlink races, complete pending-record path trust, keyring lifecycle and the
ordinary authenticated gateway bootstrap still require targeted acceptance.

## 10. Performance, capacity and hot-path policy

The journal hard ceilings are 4096 records and 8 MiB. Unsafe cleanup is refused;
capacity exhaustion must remain explicit rather than silently losing deduplication.
These bounds are not startup, RSS or interaction-latency measurements. OS subprocess
waits and work on the GUI thread still need bounded execution and responsiveness
validation. Measure startup, sustained interaction and long-running growth from
actual installed artifacts on the selected platform matrix.

## 11. Observability and operations

Expose pending/indeterminate/terminal and RecoveryRequired without collapsing
uncertainty into success. Record source identity, operation identifiers, safe
digests and phase transitions without payload or credential leakage. The current
development guide documents absolute configuration paths and owner boundaries.
The historical setup example is not an accepted ordinary-user recipe until
current gateway authentication and installed lifecycle are composed and tested.

## 12. Verification and qualification

Run the committed standalone app with Rust 1.95.0 and its native Cargo.lock:

```sh
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets --all-features -- -D warnings
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets
```

Existing runtime/security/update integration tests remain required.
`tests/journal_regressions.rs` covers immutable terminal observations, endpoint
conflicts, duplicate recovery, unknown fields, I/O-failure fencing, retained
deduplication, generation separation and monotonic phases.

The scoped workflow freezes and commits candidate source/lock metadata before
exact-head and deterministic-merge tests on Linux, macOS and Windows. Lint failure
does not suppress independent native tests. Release-binary self-test and child
process fault profiles use isolated fake adapters; they do not prove physical
OS effects, installed GUI operation or accessibility. Read each actual outcome;
missing, failed and skipped checks are not passes.

## 13. Implementation sequence and work packages

Work packages remain `UI-NATIVE-1-SHELL` and `UI-V5`. First reconcile actual source
and registries, then current-owner build/lock, operation invariants and durable
recovery. Next close authenticated ordinary startup and installed package lifecycle.
Finally obtain target-host interaction, accessibility and performance evidence.
Cross-owner integration changes must preserve current owner contracts and include
integration tests; do not restore obsolete owner trees just to satisfy a build.

## 14. Activation, compatibility and retirement

This candidate is not activated. The retired JS driver is not a second product
entrypoint. Durable journal formats and receipt identities must remain interpretable
across compatible replacements. Rollback cannot erase newer unrelated state.
Current non-Unix kernel persistence and authenticated gateway integration remain
repository blockers. Signing/notarization, operator selection and release custody
are separate externally governed gates, not inferred from passing tests.

## 15. Definition of module completion

Source presence, implemented mapping, product composition, exact-candidate
qualification, physical host acceptance and release are separate facts. Keep
productionImplementation, productExecutionProved, activation and release false
until their specific prerequisites have observed evidence. No workflow, document
or fixture grants filesystem, notification, secret or release authority.

## 16. Readiness and platform acceptance

The primary lane remains LANE-B-RUNTIME. Native AccessKit and focusable widgets
are foundations only: actual keyboard traversal, screen-reader names/states,
Chinese rendering, IME, focus restoration and multi-monitor DPI need physical
acceptance. Preserve independent acceptance and source/merge identity requirements.

## 17. Source implementation receipt

Actual Rust application sources are present in this candidate; that is a
source-location fact. The checked-in implementation map and native fingerprints
are navigation/identity evidence, not proof that every product gate passes.
Use retained workflow receipts for each exact checked-out source and merge tree.
This section grants no activation, acceptance, promotion, merge or release.

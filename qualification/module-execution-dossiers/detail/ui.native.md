# ui.native: current-source implementation dossier

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Canonical branch: `work/ui-native-current-source-20260925`.
Status: source port and qualification in progress; not product accepted.

## 1. Source and work envelope

Root: `apps/hepta-native`. Packages: `UI-NATIVE-1-SHELL`, `UI-V5`.
Restore actual #830 app content onto the current main owner contracts. Do not
restore historical kernel or gateway trees or count merged history as delivery.

## 2. Operations

`connect_runtime`, `refresh_runtime_view`, `request_platform_capability`,
`reconcile_pending`, signed update staging/activation/rollback/confirmation.
Runtime facts and final-use authority remain with their existing owners.

## 3. State and failure semantics

A bounded local journal retains session-generation/operation identity and
complete semantic digests. Invoking/indeterminate records never automatically
replay. The reviewed port rejects changed terminal observations, duplicate
recovered identities and endpoint drift; uncertain persistence fences the
owner. Destructive retirement is refused without a durable dedup frontier.

## 4. Update semantics

Signed manifests and package digests bind target compatibility and predecessor.
GUI and helper share a transition lock. Recovery authenticates the admitted
manifest, cannot overwrite an unrelated current target, and preserves durable
RecoveryRequired when predecessor restoration is not established.

## 5. Capacity and performance

Journal pilot hard limits remain 4096 records and 8 MiB. Refusing unsafe cleanup
is not a scalable retirement solution. Launcher wait bounds, UI responsiveness,
startup, RSS and sustained interaction performance remain to be measured.

## 6. Required acceptance

NATIVE-01: web/native pending, indeterminate and terminal semantics agree.
NATIVE-02: OS denial and current final-use revocation prevent new effects.
NATIVE-03: actual process exit/restart reconciles without duplicate effects.
NATIVE-04: unsigned/incompatible updates fail closed; admitted predecessor can
be restored, and stale recovery cannot overwrite a newer unrelated binary.
These are acceptance requirements, not pass receipts.

## 7. Qualification identity

The scoped workflow commits port changes, formatting, a native lock and source
fingerprints before testing exact candidate and deterministic merge. It retains
actual per-step outcomes. Release-binary fixture profiles do not prove physical
OS effects, authentic gateway integration, installed packages or accessibility.

## 8. Current native implementation

The candidate Rust entrypoint is `apps/hepta-native/src/main.rs`; owner-bound
operations are in `src/runtime.rs`, journal persistence in `src/journal.rs`,
and update lifecycle in `src/updater.rs`. Implementation detail and current
configuration are in `apps/hepta-native/DEVELOPMENT.md`.

Remaining repository blockers include current gateway keyring authentication,
non-Unix kernel durable final-use support/qualification, bounded physical
adapters, complete fault matrices, durable retirement, real packaged lifecycle,
accessibility and performance runs. Independent signing and external acceptance
are separate. No activation, promotion or release is granted by this dossier.

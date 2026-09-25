# ui.native: current-source implementation dossier

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Canonical branch: `work/ui-native-current-source-20260925`.
Status: Rust product and current-owner integration source composed; execution,
physical acceptance and release remain separately evidenced.

## 1. Source and work envelope

The exclusive UI source root is `apps/hepta-native`. The application was
recovered from PR #830 commit
`3198549d80d6c59887b82e2c50018ab818217c53` and adapted against current main,
not delivered through a history-only merge. The candidate preserves current
runtime, gateway and kernel authority ownership.

Current cross-owner source touched for product closure is limited to the
read-only native gateway and the existing kernel final-use durability boundary,
including `codex-rs/hepta-private-state` as a Windows implementation root of
`kernel.authority`.

## 2. Product operations and caller

The named product caller is `apps/hepta-native/src/main.rs`, which composes:

- authenticated `connect_runtime` and `refresh_runtime_view`;
- exact-binding `request_platform_capability`;
- `reconcile_pending` without automatic effect replay; and
- signed update verify/stage/activate/recover/confirm.

The gateway is loopback-only and read-only. It uses the existing OS-keyring capability without sending it as a native bearer, and
reports `native_auth=keyring_mac_v2` to v2 native clients. Final-use authority remains with
`kernel.authority`; the UI cannot issue grants or write domain facts.

## 3. Operation identity and durable recovery

An operation binds endpoint, session ID, session generation, operation ID,
subject, displayed revision, action/destination, canonical payload, final-use
binding and grant digest. Identical retry reuses the record; changed semantics
under the same identity conflict; a new session generation cannot consume an
old receipt.

The journal and updater roots are absolute current-principal private local
state. Unix uses owner mode `0700` plus no-follow directory opening; Windows uses
protected local DACL and no-reparse validation. Root disappearance, redirection
or permission drift fails closed before further local mutation.

The journal persists `Prepared -> Invoking -> Indeterminate/Terminal`; it fsyncs
`Invoking` before adapter entry. Once an effect may have entered the adapter,
restart and retry do not invoke it again. Only reconciliation may establish a
later terminal observation. Persistence failure poisons the journal owner.

Journal v3 migrates v2 on the next persisted change. Terminal compaction moves
exact operation identities into a durable retirement frontier. Retired identities
are rejected before permission, authority claim or dispatch after restart and
under payload drift. Active storage is bounded to 4096 records/8 MiB; the exact
retirement frontier is bounded to 32768 entries and fails closed at capacity.

## 4. Final-use and platform boundary

The effect order is durable prepare, exact kernel claim, durable invoking,
current verified-use fence, local policy, OS entry, then durable observation.
The source preserves Unix durable authority and composes the current v3 snapshot
plus append-only nonce log with a Windows private-directory implementation that
validates owner ACL, reparse-point absence, file identity and durable replacement.

Open/reveal/notification child launchers are bounded to four concurrent processes
and a one-second observation window. Timeout remains indeterminate and cannot be
blindly replayed. Clipboard success requires matching readback. Windows
notification remains disabled without installed AppUserModelID/WinRT identity.

## 5. Update and rollback semantics

Signed manifests bind stable channel, target tuple, package/predecessor/evidence
digests, backend compatibility, independent selector/generator and time bounds.
The GUI stages only after verification and exits before the separate updater
helper performs replacement.

The helper re-verifies the pending state and package, checks the installed
predecessor, creates a backup and replaces through a temporary file. Activation
stays `ActivatedUnconfirmed` until the new binary confirms its running digest.
Stale recovery cannot overwrite an unrelated newer binary. Missing evidence or
rollback failure becomes durable `RecoveryRequired` and cannot be cleared as a
fabricated success.

## 6. Capacity and performance profile

Enforced source ceilings are:

- 4096 active operation records;
- 8 MiB active journal file;
- 32768 exact retired-operation identities;
- four concurrent OS launcher children;
- one-second launcher observation window;
- 64 concurrent authenticated loopback gateway connections; and
- one serialized GUI background task for refresh, reconciliation, effect and
  update-stage I/O.

These are safety ceilings, not target-host performance claims. CI records build,
package and smoke duration plus artifact size. Installed startup, RSS,
interaction latency, sustained operation growth and multi-monitor behavior still
require physical measurements.

## 7. Required verification cases

- **NATIVE-01:** native and web clients preserve rejected, pending,
  indeterminate and terminal meanings.
- **NATIVE-02:** OS policy denial and current final-use revocation both prevent
  physical entry.
- **NATIVE-03:** concurrent retry, acknowledgement loss and actual process death
  preserve one identity without duplicate effect invocation.
- **NATIVE-04:** unsigned/incompatible updates reject; admitted predecessor can
  recover; stale recovery cannot overwrite an unrelated binary; rollback damage
  yields durable `RecoveryRequired`.
- **NATIVE-05:** v2 journal migration and v3 retirement never resurrect a
  compacted operation after restart or semantic drift.
- **NATIVE-06:** missing, wrong, duplicate, expired or replayed native v2 proofs reject
  before runtime facts are returned.
- **NATIVE-07:** refresh, reconciliation, bounded effect entry and package staging
  do not block the native event loop; concurrent UI submissions remain disabled
  until the single worker returns a cached outcome.
- **NATIVE-08:** missing, redirected, group/world-accessible or ACL-drifted native
  state roots reject startup or the next journal/update mutation.
- **NATIVE-09:** the loopback gateway rejects a 65th concurrent connection before
  task allocation and releases capacity after each admitted request completes.

These are requirements until exact-candidate receipts show their executed
results. Test source presence is not a pass.

## 8. Qualification identity and packaging

`CURRENT_SOURCE.json` fingerprints the application and current-owner integration
surfaces. Qualification runs both the exact candidate and a deterministic
synthetic merge with current main on Ubuntu 24.04, macOS 15 and Windows 2025.
Each leg independently reports app and owner-package format, strict Clippy and
tests before release build and fault profiles.

The platform packager creates deterministic unsigned ZIPs for Linux AppDir,
macOS `.app` and Windows directory layouts. Its manifest binds all three binary
digests and explicitly keeps signing, notarization and release false. The ZIP is
validated, extracted into a fresh root and the packaged main binary is smoked
from that extracted archive layout; this is not installation
or physical GUI acceptance.

## 9. Remaining gates

Repository execution evidence remains required for the final committed
exact-head and deterministic merge. Independently governed gates include Apple
notarization, Windows Authenticode/AppUserModelID, Linux repository ownership,
physical screen-reader/keyboard/Chinese IME/DPI acceptance, target-host sustained
performance, release-channel selection, operator acceptance, promotion and
release.

No documentation, workflow, fixture or unsigned package grants activation,
filesystem/notification authority or release authority.


### Current transport and startup refinement

The product native client explicitly selects authenticated-read subprotocol v2:
`codex-rs/hepta-contracts/src/native_gateway.rs` owns the MAC byte contract;
`codex-rs/hepta-native-gateway/src/native_mac.rs` verifies time, incarnation and
single-use request nonces; `apps/hepta-native/src/native_http.rs` verifies response
MAC/status/body with bounded framing and one total deadline. Legacy bearer clients
are a separate compatibility surface, never the native product fallback.

`launch_config.rs` provides ordinary installed-app configuration and bounded
`--check-connection` diagnostics. `startup.rs` records actual authenticated
GUI-startup observations; these do not establish independent or physical-host
acceptance. `update_handoff.rs` plus the existing updater/runtime owner bind normal
new-process readiness to frozen arguments, running binary, PID, session and view.
Static self-test or successful exit alone cannot confirm an update. `Confirmed`
remains queryable, and failed or unobserved startup remains recoverable.

Tests: native gateway shared/adapter proofs; `backend_security.rs`,
`file_input.rs`, `launch_config.rs`, `update_handoff.rs`, `update_product.rs` and
the existing journal/runtime/security suites. `linux_product_qualification.py`
executes a verified unpacked GUI, real keyring and normal gateway against a
private owner-format fixture. Exact-candidate execution, physical accessibility,
real IME/multi-monitor DPI, target-host long-run and independent release/signing
remain distinct evidence gates. See `apps/hepta-native/DEVELOPMENT.md` and
`docs/modules/ui.native/GATEWAY_V2.md` for the current concrete contracts.

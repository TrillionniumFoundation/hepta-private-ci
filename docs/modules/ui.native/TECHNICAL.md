# ui.native technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `ui.native`

**Owner / deputy:** `ui-platform` / `accessibility`

**Lane:** `LANE-B-RUNTIME`

**Canonical candidate:** `work/ui-native-current-source-20260925`

**Status:** Rust product source composed; exact-head, merge, physical acceptance
and release remain separately evidenced states.

## 1. Identity, mission and ownership

`ui.native` provides the native desktop presentation and bounded local platform
adapters over existing runtime owners. It does not become a second execution
spine, domain store, authority issuer, update selector or release owner.

The `ui-platform` owner controls the application source and local presentation
facts. `accessibility` independently reviews interaction semantics and physical
acceptance. Cross-owner changes preserve the canonical writer and authority of
the affected module.

## 2. Source binding and implementation status

The exclusive application root is `apps/hepta-native`. The Rust source was
recovered from PR #830 commit
`3198549d80d6c59887b82e2c50018ab818217c53`, then adapted to the current-main
owner contracts. The retired JavaScript `native.js` and `shell-runtime.js`
interfaces are not product entrypoints. A history-only merge is not delivery.

The candidate also consumes reviewed current-owner integration surfaces in:

- `codex-rs/hepta-native-gateway`;
- `codex-rs/hepta-contracts` final-use APIs; and
- `codex-rs/hepta-private-state`, the Windows durability implementation owned
  by `kernel.authority`.

`apps/hepta-native/CURRENT_SOURCE.json` fingerprints the application and these
integration surfaces. The implementation map binds the committed source commit
and tree; exact-head and deterministic-merge receipts bind their executed
checkout independently.

## 3. Boundary, responsibilities and non-goals

The module may own:

- native window, focus and presentation state;
- bounded local operation/recovery records;
- opaque session references in the OS keyring; and
- native update staging/recovery metadata.

It may not own runtime/domain facts, signing private keys, final-use grants,
provider credentials, release selection or another module's store. Missing or
stale authority, unsupported persistence, endpoint mismatch, payload drift,
reused identities with changed semantics and unknown critical fields fail
closed.

## 4. Internal architecture and component decomposition

- `src/main.rs` — product bootstrap and immutable generation configuration.
- `src/ui.rs` — eframe/egui presentation and AccessKit-native controls.
- `src/backend.rs` — signed endpoint and authenticated loopback client.
- `src/session_store.rs` — opaque session and gateway capability keyring access.
- `src/runtime.rs` — session/view and operation state machine.
- `src/journal.rs` — durable operation log and retirement frontier.
- `src/private_state.rs` — current-principal private local-state root verification.
- `src/security.rs` — exact-binding adapter to kernel final-use authority.
- `src/platform.rs` — local policy and bounded OS adapters.
- `src/updater.rs` — signed staging, activation confirmation and recovery.
- `src/bin/hepta-native-updater.rs` — separate replacement helper.
- `src/bin/hepta-native-credential.rs` — keyring capability provision/delete.

The UI owns no hidden global mutable singleton. One process generation has one
immutable endpoint/trust/policy configuration; changes require restart and a
new session generation.

## 5. Contracts, ports and compatibility

The registered upstream port remains
`ModulePort::runtime.agentd::ui.native`; runtime health is read-only. The native
backend requires a signed `hepta.endpoint-manifest.v1`, protocol compatibility,
loopback address and OS-keyring bearer account.

The product native client requires an explicitly signed protocol-v2 endpoint,
one bounded request MAC and a verified response MAC. It reports
`native_auth=keyring_mac_v2`, remains loopback-only and read-only, and never
falls back to sending the keyring secret as a bearer. Missing, wrong, duplicate,
expired or replayed proofs are rejected before runtime facts are consumed.
Legacy bearer clients remain a separately identified compatibility surface. The gateway admits at most 64 concurrent connections and
drops overload before spawning a request task. The gateway does not issue
final-use authority.

Product operations are:

- `connect_runtime`;
- `refresh_runtime_view`;
- `request_platform_capability`;
- `reconcile_pending`; and
- signed update verify/stage/activate/recover/confirm.

Rejected, indeterminate, failed and succeeded outcomes remain distinct. Process
launch or queue acceptance is never mapped to external success by itself.

## 6. Data authority, persistence and migrations

The native journal stores local dispatch facts only. Its parent and updater
roots are absolute current-principal private directories and are revalidated
before state transitions: Unix requires a no-follow owner mode `0700` directory;
Windows requires the protected local DACL/no-reparse implementation. A missing,
redirected or permission-drifted root fails closed rather than becoming an empty
replacement store. The operation key binds endpoint, session ID, session
generation and operation ID. The semantic record
also binds subject, displayed revision, action/destination, canonical payload,
final-use binding and grant digest.

Journal v3 supports v2 opening and migrates on the next persisted change. It
rejects duplicate active records, malformed fields, endpoint drift, semantic
identity conflict, phase regression and conflicting terminal observations.

Terminal compaction does not forget deduplication identity. It atomically moves
exact, domain-separated operation digests into a durable retirement frontier.
A retired identity is rejected before permission, authority claim or physical
dispatch, including after restart and with changed caller semantics. Active and
retired overlap is invalid. The active journal is bounded at 4096 records and
8 MiB; the exact retirement frontier is bounded at 32768 entries. Capacity
exhaustion fails closed and requires an explicit future migration.

## 7. Runtime, concurrency and transaction model

The runtime consumes owned Rust request values, eliminating the prior mutable
input-after-await class. The GUI snapshots each request and routes refresh,
reconciliation, effect execution and update staging through one serialized
background task slot; the event loop only polls cached results and never performs
those bounded network/OS/package operations directly. The worker uses the same
runtime owner. Journal locking establishes one local writer. The linearization
order for an effect is:

```text
validate immutable request
-> durable Prepared
-> kernel final-use claim for exact binding
-> durable Invoking
-> current verified-use fence
-> local OS policy
-> physical adapter
-> durable observation/reconciliation
```

`Invoking` is persisted and fsynced before adapter entry. Once an adapter may
have received an operation, retry/restart never re-invokes it. Only the adapter
reconciliation API may move an uncertain record to terminal. A persistence
failure poisons the journal until reopen.

Kernel final-use state remains authoritative. The UI cannot mint a token.
Revocation/epoch/expiry is checked at claim and again immediately before effect
entry. Local path, clipboard and notification switches are independent ceilings,
not authority.

## 8. Failure semantics, recovery and rollback

Invoking and indeterminate records recover without blind replay. Unknown effect
state remains visible and queryable. The journal never turns an I/O error into a
known failure or success.

Signed update manifests bind channel, target tuple, package, predecessor,
evidence, compatibility, selector, generator and time window. The GUI and
helper share a transition lock. The helper re-verifies the manifest and staged
package, verifies the installed predecessor, creates a backup and replaces from
a temporary file.

An activated binary remains `ActivatedUnconfirmed` until the new process
confirms its own executable digest. Recovery may restore only the admitted
predecessor over the admitted candidate; it cannot overwrite an unrelated newer
binary. Missing or damaged evidence, rollback failure or uncertain recovery
becomes durable `RecoveryRequired` and cannot be erased by ordinary cleanup.

## 9. Security, privacy and threat controls

Private signing keys never enter UI source, state, logs or keyring session
records. Gateway bearer values are loaded from the OS keyring, zeroized in the
server process and omitted from logs; only their digest is printed by the
provision helper. Duplicate Authorization headers are rejected and token
comparison does not short-circuit over equal-length values.

Native-local journal/update roots preserve current-principal private/no-follow
semantics and are rechecked before mutation. Unix final-use state preserves
owner-only/no-follow and durable file/directory semantics. Windows uses
`codex-hepta-private-state` to validate a private local
root, owner SID/DACL, reparse-point absence, file identity and durable replace.
Both preserve the current v3 authority snapshot and append-only nonce log.
Unsupported platforms fail closed rather than selecting a weaker store.

Payload bodies are not persisted merely to make replay easier. Path operations
must stay under explicit canonical roots. Windows notifications remain disabled
until an installed AppUserModelID/WinRT identity is available.

## 10. Performance, capacity and hot-path policy

OS launchers are limited to four concurrent child processes and a one-second
observation window. Timeout attempts to kill and reap the child but remains
indeterminate because termination cannot prove the OS did not accept the
request. Clipboard becomes terminal only after matching immediate readback.

The journal and retirement limits are enforced, not performance measurements.
CI records build/package/smoke duration and artifact size as observations.
Startup, RSS, interaction latency, long-running resource use and multi-monitor
behavior require measurements from the actual installed artifact on target
hosts.

## 11. Observability and operations

The product surfaces pending, indeterminate, terminal and `RecoveryRequired`
without collapsing them into success. Safe events may include source identity,
operation identity, digests and phase transitions; payload, bearer, private key
and secret material are excluded.

Normal startup uses the credential helper, authenticated `hepta --serve-ui`, a
signed endpoint manifest, trusted public keys and an absolute private state
root. `apps/hepta-native/DEVELOPMENT.md` is the executable operator/developer
companion.

## 12. Verification and qualification

The committed candidate must pass, independently:

```sh
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml --locked \
  --all-targets --all-features -- -D warnings
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml --locked \
  --all-targets
```

The gateway, contracts and private-state owner packages receive their own
format, all-target/all-feature strict Clippy (`--no-deps` keeps unrelated owner
packages under their own gates) and test feedback. Qualification runs exact candidate and
a deterministic synthetic merge on Ubuntu, macOS and Windows. It builds release
binaries, runs self/fault profiles, creates deterministic unsigned packages and
smokes the packaged executable. A failure or skip remains a failure or skip.

Fixture qualification exercises product state machines and process-death cuts
without invoking real user OS effects. It is not physical host or accessibility
acceptance.

## 13. Implementation sequence and work packages

`UI-NATIVE-1-SHELL` and `UI-V5` remain the application work packages. The
convergence sequence is:

1. bind one current source and retire parallel product entrypoints;
2. preserve current owner contracts and reproducible locks;
3. close operation/final-use/concurrency invariants;
4. close durable uncertainty, compaction and updater recovery;
5. qualify ordinary authenticated startup and actual packages; and
6. collect physical accessibility and performance evidence.

Cross-owner implementation changes remain registered under the affected owner
and must not be hidden inside the UI root.

## 14. Activation, compatibility and retirement

The Rust executable is the only candidate product surface. The JavaScript driver
is retired. Journal v2 remains readable and migrates to v3 on the next mutation;
all durable identities remain interpretable across the compatible migration.

Source composition does not activate the product. Activation requires current
exact-head/merge receipts and a named deployment selection. Signing,
notarization, installed notification identity, operator acceptance and release
custody remain externally governed.

## 15. Definition of module completion

Completion facts are separate:

- source and mapping complete;
- named product caller source-composed;
- exact-head product execution proved;
- deterministic merge execution proved;
- physical platform/accessibility/performance accepted;
- independently selected, promoted and released.

No source file, workflow, document or fixture grants release or effect authority.
Canonical status flags remain false until the corresponding retained evidence
exists.

## 16. Readiness and platform acceptance

AccessKit and focusable native controls are implementation foundations. Physical
acceptance still covers keyboard traversal, screen-reader names/state changes,
Chinese rendering and IME, focus restoration, multi-monitor DPI, update restart
and long-running responsiveness from the actual installed package.

Platform signing/notarization and Linux repository ownership are also external
to repository source qualification. The unsigned package manifest explicitly
keeps those gates false.

## 17. Source implementation receipt

The actual Rust application and current owner integration sources are present in
the canonical candidate. `CURRENT_SOURCE.json`, implementation maps and
registries provide source navigation and identity. Retained exact-head and
synthetic-merge artifacts provide execution evidence. Physical acceptance and
release require separate evidence and are not inferred from this section.


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

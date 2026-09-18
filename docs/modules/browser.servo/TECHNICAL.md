# browser.servo technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `browser.servo`  
**Owner:** `browser-platform`  
**Deputy:** `security-authority`  
**Lifecycle:** `existing`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `BROWSER-WEB-C1`

This stable document is the implementation guide for `browser.servo`. Canonical identity, ownership, contract, data-authority and delivery facts remain in the registered JSON documents. Source implementation, exact-head qualification, target-host enforcement, activation, independent acceptance, promotion and release are separate states.

## 1. Identity, mission and ownership

`browser.servo` isolates browser profiles, page observations, typed browser effects and network/credential consequences behind exact grants. `browser-platform` owns the Browser source roots and is accountable for correctness, backward compatibility, durable recovery, resource bounds and rollback. `security-authority` independently reviews authority linearization, persistence, isolation and capability semantics.

The module is an adapter/worker boundary with isolated state. It may own browser profile state and browser-effect operation identities, but it may not mint the final-use authority it consumes, export raw credentials, absorb another module's durable facts or treat page/model text as authority.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `apps/hepta-browser`
- `third_party/servo-patches`

Both roots are present. The canonical upstream source pin is `servo/servo@84bcc9ac701874fa9819e5cdee06356b961d736c` in `third_party/servo-patches/MANIFEST.json`.

The current repository-owned implementation includes `browser.js`, `action.js`, `bridge.js`, `runtime.js`, `runtime-host.js`, `runtime-contract.js`, `runtime-boundary.js`, `journal.js`, `worker-protocol.js`, `worker-driver.js`, the Agentd parent protocol/service, and `servo-worker/`. Cross-owner composition source is present in `codex-rs/hepta-agentd/src/browser_servo.rs` plus the named `hepta-agentd-browser` caller.

A worker source tree is not a qualified worker artifact. The candidate still requires exact-SHA build/SBOM receipts, target-host evidence and the independently governed activation/acceptance decisions.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `kernel.authority`
- `runtime.agentd`

Authoritative write domain:

- `browser_profile_state`

Explicitly denied capabilities:

- `credential_export`
- `ungranted_network`

The Browser owner accepts only bounded typed inputs. Unknown critical action/protocol fields, stale page generations, digest drift, authority drift and scope escape fail closed. The Browser owner may retain durable effect identity and terminal observations; raw secret bytes, arbitrary host paths, caller-provided JavaScript and unrestricted WebDriver/CDP commands are not legal module inputs.

## 4. Internal architecture and component decomposition

The current source is decomposed into bounded authority-free proposal/projection ingress; typed-action normalizer and payload digest binder; provenance-preserving proposal/effect bridge; per-profile bounded single-writer queue; live final-use authority handshake; strict durable pre-dispatch journal; private parent protocol and Browser service; private Browser/Servo worker protocol; exact-artifact subprocess driver; current-pin one-Servo/one-WebView worker; Linux namespace launch contract and real sandbox probe; and reconciliation/terminal receipt reporter.

For a new effect, the live revocation fence is held from Agentd `authority_enter` through Browser durable-intent fsync until the Servo worker has dequeued the command, revalidated page/document/navigation epoch plus the actionable DOM surface, reserved the operation identity and emitted `dispatch_boundary` immediately before effect execution. A worker-side pre-dispatch rejection emits `dispatch_rejected` with `localDispatchCrossed=false`; only a real worker admission boundary releases the fence as crossed. Agentd also applies bounded parent-side frame read/write deadlines; if Browser stops consuming `authority_enter` or stops producing the boundary, the production transport signals termination of the Browser child before returning an indeterminate outcome and releasing the revocation fence. Remote completion remains a separate terminal/reconciliation observation.

## 5. Contracts, ports and compatibility

Produced contract:

- `DomainRead::browser_profile_stateV1`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::runtime_health_observationV1`
- `ModulePort::kernel.authority::browser.servo`
- `ModulePort::runtime.agentd::browser.servo`
- `VerifiedUseTokenWitnessV1`

Critical package-local protocols are explicit:

- `hepta.browser.worker-frame.v1` — Browser <-> Servo worker canonical length-prefixed frames;
- `hepta.browser.agentd-stdio-frame.v1` — Agentd <-> Browser private parent frames;
- `hepta.browser.semantic-observation.v1` — bounded page semantic observation carried inside `PageObservationV1`.

The worker frame binds protocol version, session, generation, monotonic sequence, request identity and canonical payload digest. Before a new effect, the worker emits a dedicated `dispatch_boundary` frame only after stale-snapshot/action-surface revalidation and operation reservation; ordinary responses additionally echo the original request kind and request payload digest. A mismatch kills/fails the private channel. The parent protocol carries authority challenge/enter plus `dispatch_boundary` or a proven `dispatch_rejected` rather than serializing a reusable `VerifiedUseToken`.

Typed browser actions are closed-world: `navigate`, `click`, `type`, `credential`, `upload`, `focus`, `scroll`, `wait`, `download`. Navigation binds normalized URL, `policyDigest` and `expectedRevision`; the bridge uses the proposal `navigationId` as the operation identity. Thus policy revision and proposal identity are included in the final request digest rather than being dropped at adapter handoff.

## 6. Data authority, persistence and migrations

Owned/recoverable data is `browser_profile_state` plus Browser-owned effect identities/observations. The effect owner requires a persistent journal by default; the in-memory journal is accepted only through an explicit test-only opt-in. The file journal provides exact field/schema validation for every hydrated record; no unknown fields and no persisted `typedAction`; checksum-bound canonical envelopes; bounded line/file sizes; fsync before the external dispatch boundary; non-symlink/private Unix file and parent-directory checks; semantic-identity conflict detection; atomic snapshot compaction before capacity exhaustion; and clean-close retirement that fsyncs a durable per-profile generation high-water before operation records are compacted away, preventing a retired generation from being resurrected after restart.

Admission additionally rejects reopening a profile generation that still has any durable operation history and rejects advancing the same profile to another generation while a different generation has unresolved effects. Crash recovery uses `reconcilePersistedOperation`; once every persisted operation in that recovered generation is terminal, Browser retires the generation automatically before it can be reused.

`type { selector, text }` may contain sensitive user-entered text at the live effect boundary, but the durable journal stores only the typed action's final payload digest and immutable effect semantics. Raw `type.text`, credential values, upload bytes and page contents are not journal fields.

Each worker generation receives a fresh random private profile directory. Browser keeps the mode-0600 `hepta.browser.profile-owner.v1` manifest in the host-private profile root, outside the profile directory mounted read/write into the worker sandbox; the manifest binds profile ID, principal ID, generation, Browser manifest digest and profile grant digest. Only its digest crosses the session boundary. Stale profile bytes are never implicitly reopened under a different principal; successful close removes both host-private metadata and the private profile directory, then retires that journal generation.

## 7. Runtime, concurrency and transaction model

One profile is one serialization domain. The bounded per-profile mutation queue rejects excess queued work with `BrowserBackpressureError` instead of allowing unbounded promise growth.

New effect algorithm:

1. validate profile/principal/generation and current page/document generation;
2. normalize typed action, bind proposal provenance and recompute final payload digest;
3. verify destination, registered effect grant, epoch and deadline;
4. challenge Agentd with the exact request digest;
5. Agentd enters real `FinalUseAuthority::with_verified_use` while holding the live revocation fence;
6. Browser binds the witness and fsyncs an indeterminate durable dispatch record;
7. Browser writes exactly one request to the current private worker pipe;
8. the Servo worker dequeues it, revalidates page generation, document digest, navigation epoch and actionable-surface digest, reserves the operation, and emits `dispatch_boundary` immediately before execution;
9. Browser forwards that boundary and Agentd releases final-use authority; a proven worker pre-effect rejection instead emits `dispatch_rejected` and is persisted as terminal failed/no-dispatch;
10. terminal/unknown worker/business outcome is persisted and reconciled separately.

An already-dispatched identity never re-enters final-use authority and never redispatches. Browser invalidates its own page observation as soon as the worker admission boundary crosses, so every later new effect must observe again. Reconciliation remains available after the old grant/deadline expires because it observes prior work rather than authorizing new work.

The generic owner hard ceiling is 1024 nonterminal operation identities, but the current one-WebView subprocess driver advertises a stricter ceiling of one outstanding effect. That prevents a later WebView mutation from making an older unknown operation unreconcilable; alternate injected drivers must explicitly declare any wider safe outstanding-effect capacity.

## 8. Failure semantics, recovery and rollback

Before worker admission, validation, authority denial, invalid protocol, persistence failure or stale page/action-surface rejection cannot claim a crossed effect. A worker-confirmed pre-dispatch rejection is persisted as terminal failed. After the worker emits `dispatch_boundary`, driver timeout, channel loss, worker crash or unknown response remains `indeterminate` until reconciliation. In-process reconciliation uses the live worker. After Browser-process loss, `reconcile_persisted_operation` uses a distinct trusted driver reconciliation port; the current subprocess driver has no generic remote-business oracle and therefore remains indeterminate unless an explicit trusted persisted reconciler is injected.

Profile close refuses while any live or durable operation is nonterminal. Once all effects are terminal and worker stop is observed, retirement first fsyncs the profile-generation high-water and only then removes the generation's bulky operation records. A crash may therefore leave redundant terminal records but cannot make a clean-retired generation admissible again. If journal retirement fails after worker stop, the host reports `BrowserJournalRetirementError`.

Worker framing fails closed on non-canonical JSON, wrong protocol/session/generation, sequence drift, invalid payload digest, unexpected frame kind, unbound response echo or unknown request identity. Worker stderr is always drained without copying page/worker logs into receipts.

## 9. Security, privacy and threat controls

Owned threat entry:

- `browser_ungranted_network`

Security controls include final payload/provenance binding, live revocation linearization, durable exactly-once/no-redispatch identity, principal-bound fresh profile roots, origin quarantine with immediate worker containment, exact worker artifact digest verification, bounded canonical private protocols, response echo binding, stderr drain and default-deny capability vocabularies.

`LinuxBubblewrapLauncher` describes a **source launch contract**, not an independent statement that a target kernel enforced it. It starts from an empty tmpfs root, clears environment, uses `--unshare-all` without network sharing, exposes selected runtime libraries/fonts/TLS data rather than whole `/usr`, and hides general `/usr/bin`, `/usr/local`, `/var/lib`, user homes and service roots. The exact Bubblewrap and `prlimit` host executables are separately SHA-256-bound before spawn. `prlimit` installs explicit RLIMIT_AS, RLIMIT_CPU, RLIMIT_NOFILE and RLIMIT_NPROC ceilings before Bubblewrap execs the worker. `scripts/linux-sandbox-probe.js` exercises the same launcher on a real Linux host and checks host-secret invisibility, absence of general shell/Python binaries, denied direct external IPv4 connection, private-profile write/fsync, exact inherited RLIMIT values and observed cleanup of Bubblewrap plus every reported sandbox descendant after parent death.

## 10. Performance, capacity and hot-path policy

Current hard source bounds include <=1 active profile/worker process per Browser service by default (configurable only up to 64 for a compatible injected driver); <=128 origins/profile; <=1024 effect grants/profile; a generic owner ceiling of <=1024 nonterminal operations/profile with the current one-WebView subprocess driver restricted to 1 outstanding effect; <=256 terminal operations retained in host memory; <=64 queued mutations per serialization key; <=1 MiB host observation request; <=256 KiB semantic observation returned by the real Servo worker; <=1 MiB private worker frame; <=64 MiB file journal with automatic compaction beginning at 48 MiB; bounded action fields; explicit Browser driver/authority deadlines; and Linux worker defaults of 8 GiB RLIMIT_AS, 300 seconds RLIMIT_CPU, 4096 RLIMIT_NOFILE and 256 RLIMIT_NPROC. Agentd binds the exact `prlimit` path/digest and these numeric ceilings into the Browser child environment.

The current worker is one WebView/profile generation. The dossier's <=16 concurrent-tab pilot target is not a current claim and requires a later measured scheduler/profile.

## 11. Observability and operations

Safe observations include profile/process/page generations, operation/request/semantic digests, profile-owner digest, worker artifact identity and terminal/indeterminate state. Raw credential values, `type.text`, upload content/host paths, raw page HTML and worker stderr are excluded from durable receipts.

`observePage` carries a digest-bound `hepta.browser.semantic-observation.v1` produced by the real Servo WebView using a fixed worker-owned script. It exposes bounded title, visible text, HTTP(S) links, forms, unique page-local CSS selectors for visible actionable controls and viewport metadata; password inputs, hidden controls and control values are not exported. For click/type/focus, the worker requires the requested selector to exist in that freshly revalidated admitted control surface and rejects disabled controls; generic type additionally rejects password and non-text-entry targets. The fixed execution script repeats visibility/disabled/password checks immediately before mutation. The worker stores a digest of the actionable surface (links/controls/forms), re-evaluates that surface immediately before admitting an effect, rejects navigation/document/action-surface drift before `dispatch_boundary`, and invalidates the observation after every effect so the next new effect requires a fresh observation.

Operating references:

- [apps/hepta-browser/README.md](../../../apps/hepta-browser/README.md)
- [SERVO_WORKER.md](SERVO_WORKER.md)
- [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json)
- [implementation dossier](../../../qualification/module-execution-dossiers/detail/browser.servo.md)

## 12. Verification and qualification

Run the complete Browser source suite:

```sh
node --test apps/hepta-browser/test/*.test.js
node --check apps/hepta-browser/src/*.js
```

Coverage includes canonical proposals, action/provenance binding, worker-admission authority linearization, bounded parent-channel read/write timeout with revocation-fence release, explicit pre-dispatch rejection, page/document/navigation/action-surface drift, exact observed-target admission, hidden/disabled/password target rejection, host-side observation invalidation after effects, durable generation-resurrection fencing, recovered-generation auto-retirement, volatile-journal rejection, one-WebView outstanding-effect capacity, secret-free durability, semantic-observation digest/budget, bounded serialization backpressure, strict journal hydration/compaction/retirement, private protocol canonicality, response-request echo binding, worker artifact/profile ownership, stderr drain, exact Bubblewrap/prlimit artifact identity, Linux launch allowlist and in-sandbox RLIMIT observation.

Cross-owner qualification additionally runs:

```sh
cd codex-rs
cargo test --locked -p codex-hepta-agentd browser_servo --lib
cargo check --locked -p codex-hepta-agentd --bin hepta-agentd-browser
cargo clippy --locked -p codex-hepta-agentd --lib --bin hepta-agentd-browser --no-deps -- -D warnings
```

The current-pin worker build/real sandbox path is governed by `.github/workflows/hepta-browser-servo-worker-dev.yml`; Agentd composition is governed by `.github/workflows/hepta-browser-agentd-composition.yml`; Lane-B source/synthetic-merge coverage is `.github/workflows/hepta-lane-b-truth.yml`.

## 13. Implementation sequence and work packages

Applicable work package:

- `BROWSER-WEB-C1`

Repository-side Browser/Servo worker source, private protocols, real final-use handoff and named Agentd caller source are present. Remaining sequence is evidence/platform oriented: produce/review the exact `Cargo.lock`, execute the reproducible worker build/SBOM gate, execute real Linux sandbox/worker tests on the exact candidate, bind target measurements, add platform equivalents where targeted, then obtain independent activation/acceptance/promotion/release decisions.

Credential/upload/download brokers remain separate follow-on capabilities and stay fail-closed until their authority and terminal observer are implemented.

## 14. Activation, compatibility and retirement

The named one-shot Agentd caller is source-present but does not activate the default long-running daemon or invent a trusted verifying key, authority epoch, revocation frontier or worker selection. Activation still requires a trusted live authority/revocation owner, qualified exact worker artifact, target sandbox identity, durable journal/profile root configuration, resource limits and successful cross-owner/source checks.

## 15. Definition of module completion

Documentation completion requires current guide/map/dossier and closed-world validation. Source completion requires exact source plus candidate tests. Composition source now includes a named Agentd caller and live final-use handoff. Qualification requires the exact worker/build/host tuple and current CI receipts. Independent acceptance, activation, promotion and release remain separately governed.

The current candidate may claim hardened Browser owner source; real current-pin Servo worker source; bounded semantic page observation source; strict durable recovery; private worker/parent protocols; Linux sandbox/probe source; and named Agentd caller source. It may **not** claim a reproducibly qualified worker artifact, deployed target-host isolation, long-running production activation, functional secret broker, real remote business terminality, independent operator acceptance, promotion or release.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `browser.servo` to `LANE-B-RUNTIME`. Mandatory shared specifications remain [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md), [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md) and [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md). Owned readiness protocols: none. Consumed readiness protocol: `SensorCalibrationManifestV1`.

## 17. Source implementation receipt

The declared Browser roots are present and the candidate includes current-pin Servo worker source plus the Browser-side/private Agentd composition boundary. The consolidated source gate, dedicated Browser worker gate, Agentd composition gate and Lane-B source/synthetic-merge gate must execute on the exact candidate before source qualification is treated as current.

This source receipt grants no production writer, deployed network/filesystem/credential authority, independent acceptance, selection, promotion, merge or release authority.

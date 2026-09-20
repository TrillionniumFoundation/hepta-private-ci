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

Both roots are present. The selected upstream qualification candidate is `servo/servo@b5a1f5e6ec6f8685d40cd389802ced7abe4980f6` in `third_party/servo-patches/MANIFEST.json`, replacing immediate predecessor candidate `5cc5bd32d02619acdec5736055515e38c5840ce1`. The 13-commit advance deliberately includes upstream `07777aaa...`, whose general WebView double-borrow hardening changes `WebView::load()`, a direct Hepta worker callsite. Because that window also changes Servo's Cargo graph, the existing worker lock is predecessor evidence only: exact-head worker CI must generate the b5a1 candidate lock, that exact lock must be reviewed and committed, and then locked build/E2E/reproducibility must rerun before target qualification; see [SERVO_PIN_AUDIT.md](SERVO_PIN_AUDIT.md).

The current repository-owned implementation includes `browser.js`, `action.js`, `bridge.js`, `runtime.js`, `runtime-host.js`, `runtime-contract.js`, `runtime-boundary.js`, the versioned durable `journal.js`, authenticated `persisted-reconciler.js`, `worker-protocol.js`, `worker-driver.js`, the Agentd parent protocol/service, and `servo-worker/`. Cross-owner product composition is present in `codex-rs/hepta-agentd/src/browser_servo.rs`, `browser_revocation_feed.rs`, `runtime.rs` and `state_control.rs`. The one-shot `hepta-agentd-browser` binary is diagnostic/qualification only.

The strict implementation map binds the exact mapped source/evidence snapshot at `f1c54a5238409d6c078ab0315f77c1ec246baff3` / tree `161556cc80bbe9ab82aba8baa1b5aad4c785bae4`. Because a Git commit cannot embed its own future SHA/tree, later map/verifier/document-only commits are admissible only when the strict verifier proves zero drift under every mapped Browser root, test and Agentd callee.

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

The current source is decomposed into bounded authority-free proposal/projection ingress; typed-action normalizer and payload digest binder; provenance-preserving proposal/effect bridge; per-profile bounded single-writer queue; live final-use authority handshake; Agentd-owned protected monotonic revocation feed; strict versioned durable pre-dispatch journal; authenticated persisted terminal observer; private parent protocol and Browser service; private Browser/Servo worker protocol; exact-artifact subprocess driver; current-pin one-Servo/one-WebView worker; Linux namespace launch contract and real sandbox probe; and reconciliation/terminal receipt reporter.

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

The worker frame binds protocol version, session, generation, monotonic sequence, request identity and canonical payload digest. Before a new effect, the worker emits a dedicated `dispatch_boundary` frame only after stale-snapshot/action-surface revalidation and operation reservation; ordinary responses echo the original request kind, request payload digest and original request sequence, and success/error payloads reject unknown fields. A mismatch kills/fails the private channel. The parent protocol carries a secret-minimized authority challenge containing only request digest plus authority epoch, then authority enter plus `dispatch_boundary` or a proven `dispatch_rejected`; it does not duplicate typed actions into the authority plane or serialize a reusable `VerifiedUseToken`. Final Browser-to-Agentd responses are exact-key closed as either `{ok,result}` or `{ok,error}`; mixed success/error shapes, missing fields and unknown fields fail closed.

The currently admitted effect actions are closed-world: `navigate`, `click`, `type`, `focus`, `scroll`, and `wait`. `credential`, `upload`, and `download` are explicitly out of scope for the current release and fail at Browser ingress before final-use authority or worker admission. Reintroducing any of them requires a separately versioned secret/file broker, final-use binding and terminal observer. Navigation binds normalized URL, `policyDigest` and `expectedRevision`; the bridge uses the proposal `navigationId` as the operation identity.

The closed product RPC set is exactly seven methods: `open_profile`, `admit_effect_grant`, `observe_page`, `navigate_or_act`, `reconcile_operation`, `reconcile_persisted_operation`, and `close_profile`. The global implementation-map verifier rejects missing, duplicate or additional Browser operations.

## 6. Data authority, persistence and migrations

Owned/recoverable data is `browser_profile_state` plus Browser-owned effect identities/observations. The effect owner requires a persistent journal by default; the in-memory journal is accepted only through an explicit test-only opt-in. The operation journal is now `hepta.browser.operation-journal.v2`; v2 adds `terminalEvidenceDigest` and does not silently reinterpret the old v1 record shape. The file journal provides exact field/schema validation for every hydrated record; no unknown fields and no persisted `typedAction`; checksum-bound canonical envelopes; bounded line/file sizes; fsync before the external dispatch boundary; non-symlink/private Unix file and parent-directory checks; semantic-identity conflict detection; atomic snapshot compaction before capacity exhaustion; and clean-close retirement that fsyncs a durable per-profile generation high-water before operation records are compacted away. The **first** `O_CREAT` append is not considered durable until both the file and its parent directory are fsynced. Recovery accepts only a crash-torn, unterminated final JSON fragment: it restores the complete validated prefix and atomically rewrites that prefix before any later append, so a torn tail cannot be converted into permanent newline-terminated corruption on the next reopen. Newline-terminated malformed records, checksum drift and semantic substitution still fail closed. Qualification-only fault hooks exercise first-create durability, torn-prefix repair, pre/post-rename compaction and retirement cuts without exposing a product input.

Admission additionally rejects reopening a profile generation that still has any durable operation history and rejects advancing the same profile to another generation while a different generation has unresolved effects. Crash recovery uses `reconcilePersistedOperation`; once every persisted operation in that recovered generation is terminal, Browser retires the generation automatically before it can be reused. Post-process-loss success/failure may be accepted only from `hepta.browser.persisted-effect-observation.v2`, signed by the configured independent Ed25519 observer and binding observer identity/generation, observation time, frontier digest, exact profile/generation/operation/request/semantic identity and outcome. Signature validity is necessary but not sufficient: product configuration also freezes a minimum acceptable observer generation, minimum observation timestamp, exact current frontier digest and bounded future-clock skew. Generation rollback, stale time, frontier substitution and excessive future timestamps remain indeterminate. The signed evidence hash is retained as `terminalEvidenceDigest`.

`type { selector, text }` may contain sensitive user-entered text at the live effect boundary, but the durable journal stores only the typed action's final payload digest and immutable effect semantics. Raw `type.text`, credential values, upload bytes and page contents are not journal fields.

Each worker generation receives a fresh random private profile directory. Browser keeps the mode-0600 `hepta.browser.profile-owner.v1` manifest in the host-private profile root, outside the profile directory mounted read/write into the worker sandbox; the manifest binds profile ID, principal ID, generation, Browser manifest digest and profile grant digest. Only its digest crosses the session boundary, and the Browser owner independently recomputes that digest from the admitted profile/principal/generation/manifest/grant tuple before accepting driver startup. If the driver returns a mismatched post-start ownership observation, Browser requests immediate containment before returning the startup failure. Stale profile bytes are never implicitly reopened under a different principal; successful close removes both host-private metadata and the private profile directory, then retires that journal generation.

## 7. Runtime, concurrency and transaction model

One profile is one serialization domain. The bounded per-profile mutation queue rejects excess queued work with `BrowserBackpressureError` instead of allowing unbounded promise growth.

`expiresAtMs` is a physical process/network lease. The subprocess driver arms an independent expiry timer; expiry kills the Servo worker and closes its profile egress broker even if page JavaScript is still issuing background requests. The current early-revocation ceremony for a profile lease is the existing owner `close_profile` RPC; no hidden second revocation API exists. Final-use effect-grant revocation remains independent and linearizes before `dispatch_boundary`.

New effect algorithm:

1. validate profile/principal/generation and current page/document generation;
2. normalize typed action, bind proposal provenance and recompute final payload digest;
3. verify destination, registered effect grant, epoch and deadline;
4. the persistent Agentd owner synchronously refreshes its protected `hepta.browser.revocation-feed.v1` file before an effect request while a background watcher continuously advances valid monotonic heads;
5. Browser challenges Agentd with the exact request digest, and Agentd enters real `FinalUseAuthority::with_verified_use` while holding the same live revocation fence used by feed updates;
6. Browser binds the witness and fsyncs an indeterminate durable dispatch record;
7. Browser writes exactly one request to the current private worker pipe;
8. the Servo worker dequeues it, revalidates page generation, document digest, navigation epoch and actionable-surface digest, reserves the operation, and emits `dispatch_boundary` immediately before execution;
9. Browser forwards that boundary and Agentd releases final-use authority; a proven worker pre-effect rejection instead emits `dispatch_rejected` and is persisted as terminal failed/no-dispatch;
10. terminal/unknown worker/business outcome is persisted and reconciled separately.

An already-dispatched identity never re-enters final-use authority and never redispatches. Browser invalidates its own page observation as soon as the worker admission boundary crosses, so every later new effect must observe again. Reconciliation remains available after the old grant/deadline expires because it observes prior work rather than authorizing new work.

The generic owner hard ceiling is 1024 nonterminal operation identities, but the current one-WebView subprocess driver advertises a stricter ceiling of one outstanding effect. That prevents a later WebView mutation from making an older unknown operation unreconcilable; alternate injected drivers must explicitly declare any wider safe outstanding-effect capacity.

## 8. Failure semantics, recovery and rollback

Before worker admission, validation, authority denial, invalid protocol, persistence failure or stale page/action-surface rejection cannot claim a crossed effect. A worker-confirmed pre-dispatch rejection is persisted as terminal failed. After the worker emits `dispatch_boundary`, driver timeout, channel loss, worker crash or unknown response remains `indeterminate` until reconciliation. In-process reconciliation uses the live worker. After Browser-process loss, `reconcile_persisted_operation` uses a distinct authenticated observer path; the current subprocess driver has no generic remote-business oracle and a replacement Servo process is never accepted as evidence of prior terminality. The observer receives only the journal's non-secret durable identity and must return the signed v2 receipt described above; any missing, invalid, wrong-observer, stale/misbound or signature-failing receipt leaves the operation indeterminate.

Profile close refuses while any live or durable operation is nonterminal. Once all effects are terminal and worker stop is observed, retirement first fsyncs the profile-generation high-water and only then removes the generation's bulky operation records. A crash may therefore leave redundant terminal records but cannot make a clean-retired generation admissible again. If journal retirement fails after worker stop, the host reports `BrowserJournalRetirementError` while retaining the stopped profile state so retirement can be retried without restarting or re-stopping the worker; new effects remain denied during that state.

Worker framing fails closed on non-canonical JSON, wrong protocol/session/generation, sequence drift, invalid payload digest, unexpected frame kind, unbound response echo or unknown request identity. Worker stderr is always drained without copying page/worker logs into receipts.

## 9. Security, privacy and threat controls

Owned threat entry:

- `browser_ungranted_network`

Security controls include final payload/provenance binding, live revocation linearization, durable exactly-once/no-redispatch identity, principal-bound fresh profile roots, origin quarantine with immediate worker containment, exact worker artifact digest verification, bounded canonical private protocols, response echo binding, stderr drain and default-deny capability vocabularies.

`LinuxBubblewrapLauncher` describes a **source launch contract**, not an independent statement that a target kernel enforced it. It starts from an empty tmpfs root, clears environment, uses `--unshare-all` without network sharing, exposes selected runtime libraries/fonts/TLS data rather than whole `/usr`, and hides general `/usr/bin`, `/usr/local`, `/var/lib`, user homes and service roots. The exact Bubblewrap and `prlimit` host executables are separately SHA-256-bound before spawn. `prlimit` installs explicit RLIMIT_AS, RLIMIT_CPU, RLIMIT_NOFILE and RLIMIT_NPROC ceilings before Bubblewrap execs the worker. `scripts/linux-sandbox-probe.js` exercises the same launcher on a real Linux host and checks host-secret invisibility, absence of general shell/Python binaries, denied direct external IPv4 connection, private-profile write/fsync, exact inherited RLIMIT values and observed cleanup of Bubblewrap plus every reported sandbox descendant after parent death.

## 10. Performance, capacity and hot-path policy

Current hard source bounds include a profile-affine worker pool with 16 active profiles/workers by default and a hard configured ceiling of 64; each current one-WebView subprocess worker permits 1 outstanding effect; <=128 origins/profile; <=1024 effect grants/profile; a generic owner ceiling of <=1024 nonterminal operation identities/profile for alternate compatible drivers; <=256 terminal operations retained in host memory; <=64 queued mutations per serialization key; <=1 MiB host observation request; <=256 KiB semantic observation returned by the real Servo worker; <=1 MiB private worker frame; <=64 MiB file journal with automatic compaction beginning at 48 MiB; bounded action fields; explicit Browser driver/authority deadlines; and Linux worker defaults of 8 GiB RLIMIT_AS, 300 seconds RLIMIT_CPU, 4096 RLIMIT_NOFILE and 256 RLIMIT_NPROC. Agentd binds the exact `prlimit` path/digest and these numeric ceilings into the Browser child environment.

The current worker is one WebView/profile generation. The 16-profile pool is resident process/profile capacity, not a claim of 16 parallel Agentd RPCs: the current private parent port intentionally admits one in-flight Browser call at a time, so cross-profile calls can head-of-line block behind a bounded long operation. Parallel parent-channel multiplexing requires a separately versioned/qualified protocol. The dossier's <=16 concurrent-tab pilot target is not a current claim and requires a later measured scheduler/profile.

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

Coverage includes canonical proposals, action/provenance binding, worker-admission authority linearization, bounded parent-channel read/write timeout with revocation-fence release, explicit pre-dispatch rejection, page/document/navigation/action-surface drift, exact observed-target admission, effect-scoped top-level redirect fencing even when the second origin is profile-allowed, hidden/disabled/password target rejection, host-side observation invalidation after effects, durable generation-resurrection fencing, recovered-generation auto-retirement, first-create parent-directory fsync, repaired torn-tail reopen→append→reopen, volatile-journal rejection, observer generation/time/frontier rollback rejection, asynchronous profile-expiry containment, owner-close containment of background fetch/timer/navigation, one-WebView outstanding-effect capacity, secret-free durability, semantic-observation digest/budget, bounded serialization backpressure, strict journal hydration/compaction/retirement, private protocol canonicality, response-request echo binding, worker artifact/profile ownership, stderr drain, exact Bubblewrap/prlimit artifact identity, Linux launch allowlist and in-sandbox RLIMIT observation.

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

Repository-side Browser/Servo worker source, private protocols, real final-use handoff and persistent Agentd ownership are present. The b5a1 `Cargo.lock` is not yet committed: the first exact-head worker run must generate and retain the candidate lock, those exact bytes must be reviewed and committed, and a second exact-head locked run must then pass build/E2E/reproducibility/SBOM before target qualification can consume the artifact. After that, trusted Linux target qualification must execute the real sandboxed Servo public-DNS/certificate-validating HTTPS oracle and the remaining target measurements before independent activation/acceptance/promotion/release decisions.

Credential/upload/download brokers remain separate follow-on capabilities and stay fail-closed until their authority and terminal observer are implemented.

## 14. Activation, compatibility and retirement

The normal product topology is now the long-running Agentd process owning one persistent private Browser service and a bounded per-profile Servo worker pool behind the existing owner-only Agentd UDS. The one-shot `hepta-agentd-browser` binary remains a compatibility/qualification helper, not the product lifecycle owner. Product Browser configuration requires an owner-private absolute `revocation_feed_path`; the same `FinalUseAuthority` is continuously advanced from that monotonic feed and synchronously refreshed before effects. Persisted terminalization, when enabled, additionally requires reconciliation root + observer identity + Ed25519 verification key + minimum observer generation + minimum observation timestamp + exact current frontier digest + bounded future-clock skew as one closed configuration tuple. Browser activation remains explicit via `--browser-servo-config`; absence is fail-closed and no verifier key, authority epoch, revocation frontier, artifact, observer or network scope is invented.

## 15. Definition of module completion

Documentation completion requires current guide/map/dossier and closed-world validation. Source completion requires exact source plus candidate tests. Composition source now includes a named Agentd caller and live final-use handoff. Qualification requires the exact worker/build/host tuple and current CI receipts. Independent acceptance, activation, promotion and release remain separately governed.

The current candidate may claim hardened Browser owner source; real current-pin Servo worker source; bounded semantic page observation source; strict durable recovery; private worker/parent protocols; Linux sandbox/probe source; persistent Agentd ownership with owner-UID/single-link protected live revocation feed; signed persisted-terminal observer verification; and named Agentd caller source. It may **not** claim a reproducibly qualified worker artifact, deployed target-host isolation, long-running production activation, functional secret broker, real remote business terminality, independent operator acceptance, promotion or release.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `browser.servo` to `LANE-B-RUNTIME`. Mandatory shared specifications remain [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md), [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md) and [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md). Owned readiness protocols: none. Consumed readiness protocol: `SensorCalibrationManifestV1`.

## 17. Source implementation receipt

The declared Browser roots are present and the candidate includes current-pin Servo worker source plus the Browser-side/private Agentd composition boundary. The consolidated source gate, dedicated Browser worker gate, Agentd composition gate and Lane-B source/synthetic-merge gate must execute on the exact candidate before source qualification is treated as current.

This source receipt grants no production writer, deployed network/filesystem/credential authority, independent acceptance, selection, promotion, merge or release authority.


## 18. 2026-09-19 product-closure overlay

The repository candidate additionally closes the source-side gaps that previously
separated the hardened owner boundary from a usable browser lifecycle:

- **Persistent owner:** Agentd can explicitly load a private Browser runtime
  configuration and retain one `BrowserServoPort` for the Agentd generation.
  Calls over the existing Agentd UDS therefore preserve
  `open -> observe -> act/reconcile -> close` state.
- **Worker pool:** `PooledSubprocessBrowserDriver` retains one isolated Servo
  process/profile per admitted profile, default capacity 16 and hard ceiling 64.
- **Grant-scoped egress:** Servo keeps an unshared external network namespace.
  Its HTTP(S) proxy preferences point to a sandbox-loopback relay which can only
  reach a private Unix socket in the profile bind. The host-side
  `GrantScopedEgressBroker` binds the profile network grant by resolving each
  admitted origin once when that broker generation starts, rejecting
  loopback/private/link-local/special destinations, and freezing the exact
  DNS/IP answer set under the profile grant digest. Later HTTP requests and
  CONNECT tunnels never re-resolve those names and can connect only to the
  frozen addresses. For HTTPS CONNECT to a DNS destination it also parses a
  bounded TLS ClientHello and requires SNI to match the granted host before any
  upstream TCP connection. Independently of the profile network allowlist, the
  Servo delegate pins every top-level navigation to the current effect's exact
  `destinationOrigin`; redirecting to a second origin that is profile-allowed
  but not selected by this effect is denied before navigation admission.
- **Terminal pipeline:** final-use authority ends at the worker admission
  boundary, but the driver retains the bound worker response. Terminal
  settlement is persisted without holding the revocation fence; bounded late
  settlement can also refine the journal.
- **Crash reconciliation:** a replacement process may consume only an exact
  `hepta.browser.persisted-effect-observation.v2` receipt authenticated by the
  configured Ed25519 observer. The signature binds observer identity/generation,
  observation time/frontier, profile generation, operation, request/semantic
  digests, terminal status and outcome; its evidence digest is retained in the
  v2 operation journal. Missing or unauthenticated evidence remains indeterminate.
- **Real E2E:** the worker gate now exercises the built Servo binary through
  Bubblewrap for `open -> navigate -> observe -> type -> observe -> click ->
  observe -> close`, checks an ungranted subresource cannot reach its server,
  and checks persisted crash reconciliation.
- **Capability truth:** credential, upload and download are not current Browser
  capabilities; ingress rejects them as future capability instead of allowing a
  later worker failure.

The selected b5a1 Servo candidate and its 13-commit delta from the 5cc5 predecessor
are documented in [SERVO_PIN_AUDIT.md](SERVO_PIN_AUDIT.md). The b5a1 candidate
lock is **not yet committed**. The first exact-head worker run must generate and
retain that lock candidate; after review the exact bytes must be committed and a
second exact-head locked run must pass build, real-E2E, reproducibility/SBOM
before target qualification can consume the artifact.

External gates still include terminal-success real sandboxed-Servo public HTTPS target evidence, retained cross-profile cookie/localStorage/cache
isolation evidence, target soak/resource measurements, platform equivalents where
targeted, independently trusted remote business terminal observations, operator
acceptance, promotion and release.


### Post-closure recovery and egress qualification notes

A private-channel protocol, unavailable-child or indeterminate failure never
retries the current Browser semantic call. Agentd drops the failed Browser child;
the next call starts a clean private Browser service against the same durable
journal, allowing an explicit `reconcile_persisted_operation` request to
consume trusted recovery evidence without redispatch.

The real Browser qualification path also checks HTTP subresource escape, a
redirect to a second profile-allowed origin that is outside the current effect
destination grant, exact HTTPS CONNECT authority/port/ClientHello-SNI admission,
same-profile cookie persistence, cross-profile cookie/localStorage/HTTP-cache isolation,
absence of non-loopback worker listeners, and a 32-cycle worker RSS/FD soak with
hard peak/terminal RSS-growth ceilings of 512 MiB / 256 MiB and FD-growth ceiling
of +32. These are source qualification oracles until an exact target-host run
produces retained evidence.


### Current platform scope

The repository product launcher is intentionally **Linux-only** at this stage: `agentd-service-main.js` rejects non-Linux hosts and the qualified isolation design is Bubblewrap + prlimit. macOS and Windows are outside the current qualified deployment scope; they may enter scope only after equivalent filesystem/network/process/resource isolation adapters and exact-host evidence exist. The 16-profile pool is resident worker capacity, while the current parent Browser port remains one-in-flight; parent RPC multiplexing is a later capacity design and is not required to claim the current serialized control semantics.


### Revocation race evidence split

The Agentd final-use suite updates the real owner-private `hepta.browser.revocation-feed.v1` file and proves its monotonic revision cannot advance through the same `FinalUseAuthority` fence before the Browser dispatch/rejection boundary. Separately, the real-Servo E2E proves a revocation race against an actual worker stays blocked until that worker reaches `dispatch_boundary`. Exact-head closure requires both receipts; neither is substituted for the other.

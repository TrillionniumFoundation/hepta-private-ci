# browser.servo technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `browser.servo`  
**Owner:** `browser-platform`  
**Deputy:** `security-authority`  
**Lifecycle:** `existing`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `BROWSER-WEB-C1`

This is the current implementation guide for `browser.servo`. It describes the exact repository source topology, transaction semantics, operating controls and qualification boundaries. Machine-readable truth is projected by [`GENERATED_SOURCE_REGISTRY.json`](GENERATED_SOURCE_REGISTRY.json) and [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json). Source presence never self-issues deployment qualification, operator acceptance, activation, promotion or release.

## 1. Mission, ownership and trust boundary

`browser.servo` owns bounded browser profiles, page observations, typed browser effects and the durable identity of those effects. It isolates browser execution behind exact profile grants, effect grants and live final-use authority. It does not mint authority, interpret page/model text as authority, export raw credentials, expose arbitrary WebDriver/CDP commands or become a general-purpose filesystem/network executor.

The primary owner `browser-platform` controls `apps/hepta-browser/**` and `third_party/servo-patches/**`. The deputy `security-authority` independently reviews final-use linearization, journal monotonicity, process/network/filesystem isolation, secret handling, artifact provenance and activation evidence. Cross-owner Agentd source remains under its own owner and is consumed through the registered private module port.

Authoritative write domain:

- `browser_profile_state`;
- Browser-owned effect identities and terminal/indeterminate observations;
- Browser journal generation-retirement high-water.

Explicitly denied capabilities:

- `credential_export`;
- `ungranted_network`;
- caller-provided arbitrary JavaScript;
- ambient host-file access;
- public Browser discovery or control listeners.

## 2. Canonical source and current implementation state

The selected Servo qualification pin is:

```text
servo/servo@b5a1f5e6ec6f8685d40cd389802ced7abe4980f6
```

It is declared by `third_party/servo-patches/MANIFEST.json`. The exact reviewed `apps/hepta-browser/servo-worker/Cargo.lock` for this pin is committed and is mandatory. Browser worker workflows fail if the lock is missing, generated during CI, or does not contain the selected pin.

The Browser-owned source consists of:

- `browser.js` — authority-free proposal/presentation helpers;
- `action.js` — closed bounded typed actions;
- `bridge.js` — proposal provenance to exact effect request;
- `runtime.js`, `runtime-host.js`, `runtime-contract.js`, `runtime-boundary.js` — serialized owner state machine and bounded queues;
- `journal.js` — monotonic version-2 durable effect journal;
- `persisted-reconciler.js` — authenticated post-process-loss terminal observer;
- `worker-protocol.js`, `worker-driver.js` — private framed worker transport, worker admission and Linux process containment;
- `egress-broker.js` — grant-scoped host network broker;
- `agentd-protocol.js`, `agentd-service.js`, `agentd-service-main.js` — Browser side of the inherited Agentd parent boundary;
- `servo-worker/` — one-Servo/one-WebView worker at the exact pin;
- `scripts/` — real sandbox, E2E, public-egress, soak, SBOM, registry and target-evidence qualification tools.

The current Agentd-side source is intentionally split:

- `codex-rs/hepta-agentd/src/browser_servo.rs` and `hepta-agentd-browser` remain the legacy/diagnostic compatibility path;
- `browser_servo_persistent.rs` is the persistent Browser port implementation;
- `browser_revocation_feed.rs` owns the protected monotonic revocation feed;
- `hepta-agentd-browser-service` is the named long-lived inherited-stdio product-shaped service that retains one persistent Browser control across multiple calls.

The persistent service is source-composed and separately compiled/tested. It is **not** silently enabled inside the default Agentd daemon and does not create a listener. Activation still requires an external supervisor/product caller to start the named service with a complete trusted configuration.

The exact seven-RPC set, capability matrix and source-object map are generated from source by:

```sh
npm --prefix apps/hepta-browser run verify:registry
```

The generated registry and complete Browser test suite are mandatory dependencies of `CI required`.

## 3. Closed contracts and RPC surface

Produced contract:

- `DomainRead::browser_profile_stateV1`.

Consumed contracts:

- `DomainRead::authority_leaseV1`;
- `DomainRead::capability_revocationV1`;
- `DomainRead::runtime_health_observationV1`;
- `ModulePort::kernel.authority::browser.servo`;
- `ModulePort::runtime.agentd::browser.servo`;
- `VerifiedUseTokenWitnessV1`.

The closed product RPC set is exactly:

1. `open_profile`;
2. `admit_effect_grant`;
3. `observe_page`;
4. `navigate_or_act`;
5. `reconcile_operation`;
6. `reconcile_persisted_operation`;
7. `close_profile`.

Unknown methods and unknown critical fields fail closed. The generated registry rejects missing, duplicate or additional methods.

Package-local protocols:

- `hepta.browser.agentd-stdio-frame.v1` — Agentd ↔ Browser canonical bounded parent frames;
- `hepta.browser.worker-frame.v1` — Browser ↔ Servo canonical bounded worker frames;
- `hepta.browser.semantic-observation.v1` — bounded semantic page projection;
- `hepta.browser.operation-journal.v2` — durable effect state;
- `hepta.browser.persisted-effect-observation.v2` — independently signed post-process-loss terminal receipt;
- `hepta.browser.revocation-feed.v1` — protected monotonic revocation-head file.

## 4. Typed effect boundary

Currently admitted action kinds are:

- `navigate { url, policyDigest, expectedRevision }`;
- `click { selector }`;
- `type { selector, text }`;
- `focus { selector }`;
- `scroll { deltaX, deltaY }`;
- `wait { condition, timeoutMs }`.

`credential`, `upload` and `download` remain explicit future capabilities and are rejected at Browser ingress before final-use authority or worker admission. Reintroducing one requires a versioned broker, secret/file transfer protocol, final-use binding, bounded terminal observer and separate target qualification.

Every new effect binds:

- profile ID, principal ID, process ID and profile generation;
- page generation, document digest, page revision and actionable-surface digest;
- operation ID and proposal provenance;
- normalized typed action and final payload digest;
- exact destination origin;
- profile grant and effect grant digests;
- authority epoch and deadline.

Raw `type.text` exists only at the live effect boundary. The journal stores the final payload digest and immutable semantic identity, not the full typed action. Raw secret values, page HTML, upload bytes, ambient paths and worker stderr are excluded from durable receipts.

## 5. Final-use and worker-admission linearization

A successful private-pipe write is not effect admission. The exact sequence is:

1. Browser validates profile/page/action/grant/epoch/deadline and computes the request digest.
2. Browser emits a secret-minimized `authority_challenge` containing only request digest and authority epoch.
3. Agentd verifies the independently signed grant and exact `FinalUseBinding`.
4. Agentd enters `FinalUseAuthority::with_dispatch_boundary`; revocation updates use the same live fence.
5. Browser binds the witness and fsyncs an indeterminate dispatch record.
6. Browser writes exactly one command to the private Servo pipe.
7. Servo dequeues and revalidates page generation, document digest, navigation epoch, exact destination and actionable-surface digest.
8. Servo reserves the operation identity.
9. Servo emits `dispatch_boundary` immediately before effect execution, or emits `dispatch_rejected { localDispatchCrossed:false }` for a proven pre-effect rejection.
10. Browser forwards the bound admission/rejection receipt to Agentd; only then may Agentd release final-use authority.
11. Remote/page/business terminality is persisted and reconciled separately.

If the parent channel times out before a proven admission/rejection receipt, the production transport terminates the Browser child before returning `Indeterminate`; the worker parent-death contract then contains descendants. AbortSignal delivery alone is never considered proof of containment.

A crossed operation identity never re-enters final-use authority and is never blindly redispatched. A proven rejection is terminal no-dispatch. Any uncertainty after worker admission remains `indeterminate` until a valid terminal observation is recorded.

## 6. Durable effect journal and recovery

The default owner requires `FileBrowserOperationJournal`; the memory journal is test-only. Version 2 enforces:

- immutable operation/request/semantic identity;
- exact duplicate dispatch/observation as a no-op;
- terminal-state monotonicity;
- rejection of conflicting terminal outcomes;
- strict record/envelope field validation and canonical checksums;
- private non-symlink file and parent directories;
- file fsync plus required parent-directory barriers;
- recovery only for an unterminated crash-torn final fragment;
- atomic validated-prefix repair before any later append;
- I/O failure fencing of subsequent ordinary reads/writes until explicit owner recovery;
- bounded in-memory index, file size and record size;
- atomic compaction before the hard ceiling;
- crash-safe generation retirement and non-resurrection;
- schema-version rejection rather than silent reinterpretation;
- secret-free durable records.

Profile admission rejects reopening a generation with durable history and rejects advancing while another generation retains unresolved effects. Close refuses while any live or durable operation is nonterminal.

In-process reconciliation queries the live worker. After Browser/worker loss, a replacement process is not evidence of an earlier external outcome. `reconcile_persisted_operation` accepts only an Ed25519-signed v2 receipt binding:

- observer identity and generation;
- observation time and exact current frontier;
- profile/generation/operation;
- request and semantic digests;
- terminal status and outcome digest.

Configuration freezes minimum observer generation/time, exact frontier and maximum future skew. Missing, stale, rollback, future, wrong-observer, misbound or invalidly signed evidence leaves the operation indeterminate. The evidence hash is persisted as `terminalEvidenceDigest`.

## 7. Semantic observation and action revalidation

The real worker produces a bounded `hepta.browser.semantic-observation.v1` using fixed worker-owned logic. It may contain:

- title and bounded visible text;
- HTTP(S) links;
- forms and non-secret control metadata;
- unique page-local selectors for visible actionable controls;
- viewport metadata;
- frame/origin provenance;
- semantic and actionable-surface digests.

Password inputs, hidden controls and control values are not exported. Browser verifies observation size and digest before publishing it.

Immediately before worker admission, Servo recomputes page/document/navigation/actionable-surface state. Click/type/focus must target a selector from the exact admitted visible control surface. Disabled, hidden, password or non-text-entry targets fail closed. Every crossed effect invalidates the old observation, so the next effect requires a fresh observation.

This prevents an observe→DOM-drift→act selector substitution from crossing the final-use boundary unnoticed.

## 8. Grant-scoped egress

Servo keeps an unshared external network namespace. It reaches the host-side `GrantScopedEgressBroker` only through a private profile-scoped channel. The broker:

- admits only exact profile-granted origins;
- resolves each admitted DNS name once per broker generation;
- rejects loopback, private, link-local, multicast and special addresses;
- freezes the DNS/IP answer set under the profile grant digest;
- does not re-resolve on subsequent requests;
- binds HTTP origin and HTTPS CONNECT authority;
- parses a bounded TLS ClientHello and requires SNI to match the granted hostname;
- applies response/header/body/time bounds;
- rejects redirect/subresource escape;
- records per-operation network observations without secret payloads.

Top-level navigation is also effect-scoped: a redirect to a second origin is denied even when that origin is generally profile-allowed unless the current effect selected it.

Profile expiry and explicit close terminate the worker and broker lease, containing background fetch/timer/navigation. Direct external networking from inside Bubblewrap remains denied.

## 9. Private protocols and process containment

Both private protocols use a four-byte big-endian length prefix and canonical JSON with a 1 MiB hard frame limit. Frames bind protocol version, sequence, request identity, payload digest, session and generation where applicable. Responses echo request kind, request payload digest and request sequence. Unknown kinds, unknown fields, non-canonical payloads, sequence drift and cross-session/generation data fail the channel.

Worker stderr is continuously drained into a bounded diagnostic tail and is not journaled. Channel corruption, admission-timeout containment and profile expiry terminate the private process tree.

The Linux launcher:

- starts from an empty tmpfs root;
- clears the ambient environment;
- uses `--unshare-all` without `--share-net`;
- exposes a narrow read-only runtime/font/CA closure;
- hides general `/usr/bin`, `/usr/local`, `/var/lib`, service roots and user homes;
- mounts one private writable profile and one verified read-only worker;
- binds exact Bubblewrap and `prlimit` executables by SHA-256;
- uses parent-death cleanup;
- applies RLIMIT_AS, RLIMIT_CPU, RLIMIT_NOFILE and RLIMIT_NPROC.

Current default worker ceilings are:

- address space: 8 GiB;
- CPU: 300 seconds;
- open files: 4096;
- processes/threads: 256.

These are source controls until the exact target-host probe observes them.

## 10. Capacity, performance and backpressure

Current source bounds:

- default 16 active profile-affine workers, hard configurable ceiling 64;
- one WebView per profile generation;
- one outstanding effect for the current subprocess worker;
- 128 origins/profile;
- 1024 effect grants/profile;
- generic owner ceiling of 1024 nonterminal operation identities for compatible alternate drivers;
- 256 terminal operations retained in host memory;
- 64 queued mutations per serialization key;
- 1 MiB host observation request;
- 256 KiB semantic observation;
- 1 MiB private frame;
- 64 MiB journal, with compaction beginning before the ceiling;
- explicit driver, authority, channel and effect deadlines.

The 16-worker pool is resident capacity, not parent-channel parallelism. `hepta-agentd-browser-service` intentionally processes one private parent call at a time; cross-profile calls can head-of-line block behind a bounded operation. Multiplexing requires a separately versioned protocol and qualification.

Target qualification runs a 32-cycle real-worker soak and enforces bounded RSS/FD growth. Source constants are not performance evidence until a retained target receipt exists.

## 11. Product-shaped Agentd ownership

`hepta-agentd-browser-service` is the named long-lived source composition. It:

- owns one `PersistentBrowserServoControl` for its lifetime;
- accepts bounded length-prefixed JSON only over inherited stdin/stdout;
- exposes the exact seven methods;
- retains Browser profile/session state across calls;
- maintains the protected live revocation feed;
- requires signed final-use authority only for `navigate_or_act`;
- rejects authority on non-effect calls;
- has no TCP, UDS, WebDriver, CDP or discovery listener;
- returns bounded errors and leaves indeterminate operations for explicit reconciliation.

The one-shot `hepta-agentd-browser` remains a diagnostic/compatibility caller. The default Agentd daemon is not modified to fabricate or auto-enable Browser configuration. A supervisor/product process must explicitly select and start the long-lived service with exact artifact paths/digests, authority state, revocation feed, journal/profile roots, observer tuple and resource limits.

## 12. Reproducible artifacts, SBOM and signed provenance

The primary worker workflow requires:

- exact source SHA and committed b5a1 lock;
- Rust 1.88.0 and explicit Servo prerequisites;
- feature graph capture and `webdriver_server` rejection;
- `cargo check --locked` and worker tests;
- complete Browser Node suite;
- real Bubblewrap/resource/descendant probe;
- two same-runner exact-input release builds with byte equality;
- dynamic-library closure;
- real worker smoke, Browser E2E and 32-cycle soak;
- deterministic SPDX 2.3 SBOM;
- build receipt and worker/SBOM digests.

The receipt truthfully distinguishes same-runner determinism from independent reproducibility. A second workflow rebuilds the same SHA and lock on a separate ephemeral GitHub-hosted runner. On `main`, both workflows generate Sigstore/GitHub OIDC SLSA provenance; the primary workflow also signs the SPDX 2.3 SBOM.

The manual main-only target gate requires two different successful run IDs, compares worker bytes, verifies exact lock/source/tree/pin, and cryptographically verifies:

- primary SLSA provenance;
- primary SPDX 2.3 SBOM attestation;
- independent SLSA provenance;
- exact signer workflow;
- exact `main` source SHA/ref;
- non-self-hosted signing builders;
- verified transparency/timestamp witness and signing certificate.

Only then does it emit a multi-builder receipt with `reproducibleIndependentBuilds=true`. The trusted target runner itself does not sign the build artifact.

## 13. Verification matrix

Required source checks:

```sh
npm --prefix apps/hepta-browser run verify:registry
node --test apps/hepta-browser/test/*.test.js
node --check apps/hepta-browser/src/*.js
```

The Node suite includes journal durability/monotonicity, crash cuts, effect admission/rejection, timeout containment, observation drift, egress policy, profile isolation, protocol closure, worker-driver resources, persisted signed reconciliation and Python verifier syntax.

Agentd composition checks:

```sh
cd codex-rs
cargo fmt --package codex-hepta-agentd -- --check
cargo test --locked -p codex-hepta-agentd browser_servo --lib
cargo test --locked -p codex-hepta-agentd --bin hepta-agentd-browser-service
cargo check --locked -p codex-hepta-agentd \
  --bin hepta-agentd-browser \
  --bin hepta-agentd-browser-service
cargo clippy --locked -p codex-hepta-agentd \
  --lib \
  --bin hepta-agentd-browser \
  --bin hepta-agentd-browser-service \
  --no-deps -- -D warnings
```

Dedicated workflows:

- `.github/workflows/hepta-browser-agentd-composition.yml`;
- `.github/workflows/hepta-browser-servo-worker-dev.yml`;
- `.github/workflows/hepta-browser-servo-independent-rebuild.yml`;
- `.github/workflows/hepta-browser-servo-deployment-qualification.yml`;
- global `CI required`, `Architecture required`, document/integrity and Lane-B exact-head/synthetic-merge gates.

Queued, cancelled, skipped-applicable or prior-head runs are not pass evidence.

## 14. Operating procedure

### Startup

1. Verify exact Browser service, worker, Bubblewrap and `prlimit` digests.
2. Verify owner-private canonical journal/profile/revocation paths and modes.
3. Open persistent final-use authority with the trusted issuer key set and current epoch/frontier.
4. Open the monotonic revocation feed; initial refresh must succeed.
5. Configure persisted observer identity/key/generation/time/frontier tuple when post-process-loss terminalization is enabled.
6. Start `hepta-agentd-browser-service` as a private child using inherited pipes.
7. Admit profiles only after health and artifact checks succeed.

### Normal operation

- record profile/worker counts, queue depth and journal utilization;
- refresh revocations synchronously before effect calls and continuously in the watcher;
- alert on indeterminate age, repeated containment, journal fencing, profile expiry, protocol corruption and egress denial rates;
- reconcile crossed operations; never convert timeout into redispatch;
- close profiles explicitly when no longer needed.

### Shutdown and rollback

1. Stop admitting new profiles/effects.
2. Reconcile or quarantine all crossed indeterminate operations.
3. Close terminal profiles and observe worker/broker/process-tree termination.
4. Preserve unresolved journals and signed evidence; do not delete them to free capacity.
5. Roll back source/artifacts only with the journal schema and selected worker/pin compatibility checked.
6. Keep operator acceptance, activation, promotion and release decisions external to the module.

## 15. Metrics, SLOs and alerts

Required metrics:

- active/opening/closing profiles;
- active workers and pool saturation;
- per-profile queue depth and backpressure rejects;
- effect admissions, proven rejections, terminal outcomes and indeterminate count;
- oldest indeterminate age;
- reconciliation success/failure/latency;
- journal bytes, compaction count/latency, fenced state and retirement failures;
- authority challenge/admission latency and revocation-feed revision lag;
- worker restarts, containment actions and descendant-cleanup failures;
- egress connects/denials/redirect denials/SNI denials and response bytes;
- semantic observation bytes/latency and stale-surface rejections;
- worker RSS/FD/process counts and expiry/close containment latency.

Initial qualification objectives, not automatic release guarantees:

- no duplicate external dispatch for one semantic operation identity;
- zero accepted stale/misbound authority or signed observer receipts;
- zero direct external worker egress outside the broker;
- zero cross-profile cookie/storage/cache transfer in the real E2E oracle;
- all target qualification process trees gone after close/parent death;
- bounded queue, frame, observation, journal, RSS and FD growth;
- every current target receipt bound to exact source/tree/lock/artifact/workflow identities.

Any violation of an authority, duplicate-effect, profile-isolation or direct-egress invariant is a release blocker, not merely an SLO miss.

## 16. Fault-injection and operational drills

The qualification plan covers:

- crash before/after dispatch-record fsync;
- torn append and reopen→append→reopen;
- first-create file and parent-directory fsync failures;
- compaction temp fsync, rename and parent-fsync cuts;
- generation-retirement high-water and journal-rewrite cuts;
- authority denial/revocation races;
- parent write/read timeout before admission;
- worker admission rejection and post-admission loss;
- malformed/cross-session/sequence/payload-digest protocol frames;
- journal capacity/fencing and disk I/O failures;
- profile expiry and explicit close during background network activity;
- worker/process/Browser service kill and signed persisted reconciliation;
- DNS/private-address/redirect/subresource/SNI policy attacks;
- profile cookie/localStorage/cache isolation;
- worker RSS/FD/process soak;
- parent death and descendant cleanup.

Production drills must retain exact source, artifact, host and receipt identities. A fixture-only result is not target evidence.

## 17. Pin and CVE lifecycle

For each Servo/toolchain or major dependency refresh:

1. record old/new exact commits and audited delta in `SERVO_PIN_AUDIT.md`;
2. review direct WebView, networking, proxy, storage, permission, rendering and feature-graph changes;
3. regenerate and review the exact committed worker lock outside CI source mutation;
4. reject forbidden/default/WebDriver features;
5. run complete Browser/Agentd tests and both independent builders;
6. verify byte-identical artifacts and signed provenance/SBOM;
7. rerun trusted target isolation, real public HTTPS, cross-profile isolation and soak;
8. obtain the external operator/promotion/release decisions.

A CVE response may revoke an artifact/pin immediately, but may not bypass exact-lock review, authority semantics, target qualification or signed provenance for the replacement.

## 18. Activation and completion boundary

Current repository source may claim:

- seven-RPC Browser owner source;
- monotonic durable effect journal and signed persisted reconciliation;
- worker-side effect admission/rejection boundary;
- bounded semantic observation and action-surface revalidation;
- grant-scoped egress source and real E2E oracles;
- Linux Bubblewrap/prlimit source controls and probes;
- committed b5a1 lock;
- two-builder and signed-provenance qualification workflows;
- named long-lived Agentd Browser service source;
- required source/registry/Agentd/worker checks.

It may not claim until exact retained evidence exists:

- successful exact-head and synthetic-merge qualification for the final candidate;
- successful signed primary and independent `main` artifacts;
- successful main-only trusted Linux target receipt;
- production activation by a trusted supervisor/product caller;
- functional credential/upload/download brokers;
- independently trusted remote-business terminal observations where such terminality is claimed;
- operator acceptance, promotion or release;
- macOS/Windows support unless those platforms are separately implemented and qualified.

Canonical current booleans remain:

```text
source_root_present = true
production_implementation = false
deployment_qualification = false
operator_acceptance = false
activation = false
promotion = false
release = false
```

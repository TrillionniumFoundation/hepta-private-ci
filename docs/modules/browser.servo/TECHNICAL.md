# browser.servo technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `browser.servo`  
**Owner:** `browser-platform`  
**Deputy:** `security-authority`  
**Lifecycle:** `existing`  
**Source status:** `existing_bound`  
**Work package:** `BROWSER-WEB-C1`

This guide describes the current repository source, not a historical PR narrative. Exact RPCs, worker capabilities and source objects are generated into [`GENERATED_SOURCE_REGISTRY.json`](GENERATED_SOURCE_REGISTRY.json). Source implementation, exact-head qualification, trusted-target enforcement, activation, independent acceptance, promotion and release are separate states.

## 1. Identity, mission and ownership

`browser.servo` owns the checked browser adapter boundary: isolated profiles, bounded semantic page observations, typed effects, durable operation identities, private Servo workers and grant-scoped network use. It consumes final-use authority but cannot mint it. It never interprets page text or model output as authority.

`browser-platform` owns `apps/hepta-browser/**` and `third_party/servo-patches/**`. `security-authority` independently reviews final-use linearization, persistence, isolation, credential handling, network policy and activation. Cross-owner Agentd code remains owned by `runtime.agentd` and is consumed through the private product port.

## 2. Source binding and current implementation

Declared roots:

- `apps/hepta-browser`
- `third_party/servo-patches`

The current Servo source pin is `servo/servo@b5a1f5e6ec6f8685d40cd389802ced7abe4980f6`. The worker lock is committed at `apps/hepta-browser/servo-worker/Cargo.lock`; qualification workflows fail if it is absent, generated during CI or does not contain the selected pin.

Current source components include:

- `action.js` and `bridge.js` — bounded typed actions and proposal provenance;
- `runtime.js`, `runtime-host.js`, `runtime-contract.js`, `runtime-boundary.js` — serialized owner state machine;
- `journal.js` plus `journal-core.js` — monotonic durable journal v2 and core storage engine;
- `persisted-reconciler.js` — signed post-process-loss terminal observations;
- `agentd-protocol.js` and `agentd-service.js` — private parent protocol;
- `verified-service-bootstrap.js` and `service-manifest.json` — transitive service artifact verification before module import;
- `agentd-service-production-main.js` — fail-closed production Browser service;
- `worker-protocol.js` and `worker-driver.js` — private worker protocol and profile-affine worker pool;
- `egress-broker.js` — grant-scoped DNS/IP/origin/TLS/redirect/subresource enforcement;
- `production-launcher.js` — exact-digest Bubblewrap/prlimit plus cgroup-v2 and seccomp enforcement;
- `servo-worker/` — one Servo, software rendering context and WebView per profile generation;
- `codex-rs/hepta-agentd/src/browser_servo.rs` — restartable persistent Agentd Browser port;
- `browser_revocation_feed.rs` — owner-private monotonic live revocation feed;
- `hepta-agentd-browserd` — long-running product owner over inherited stdio;
- `hepta-agentd-browser` — one-shot diagnostic caller.

The generated source registry is the current source-object map. `IMPLEMENTATION_MAP.json` records design-to-source traceability and deliberately keeps activation/release false until external gates pass.

## 3. Boundary, responsibilities and non-goals

Produced contract:

- `DomainRead::browser_profile_stateV1`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::runtime_health_observationV1`
- `ModulePort::kernel.authority::browser.servo`
- `ModulePort::runtime.agentd::browser.servo`
- `VerifiedUseTokenWitnessV1`

Owned durable/recoverable facts are profile-generation state and Browser operation identities/observations. Raw credentials, upload bytes, arbitrary host paths, unrestricted caller JavaScript, WebDriver/CDP and another module's durable facts are outside the boundary.

Non-goals are becoming a general state store, exposing a browser-debugging listener, treating queue acknowledgement as terminal business success, or converting CI/source presence into deployment authority.

## 4. Architecture and component decomposition

The production topology is:

```text
trusted parent
  -> hepta-agentd-browserd
     -> PersistentBrowserServoControl
        -> verified-service-bootstrap.js
           -> verified ESM closure
           -> agentd-service-production-main.js
              -> BrowserProfileHost
              -> operation journal v2
              -> profile-affine worker pool
              -> grant-scoped egress broker
              -> prlimit + Bubblewrap + cgroup-v2 + seccomp
                 -> one Servo/WebView worker per profile generation
```

The long-running owner creates no Browser TCP/HTTP discovery listener. Parent and worker control paths are canonical length-prefixed private frames. Browser-to-Servo and Agentd-to-Browser identities bind protocol version, sequence, request identity, generation and payload digest.

A profile has one private writable profile directory, one host-private ownership manifest, one Servo worker and one egress broker. The service can own several profiles through a bounded profile-affine pool; each current one-WebView worker admits one outstanding effect.

## 5. RPCs, actions and compatibility

The exact product RPC set is:

1. `open_profile`
2. `admit_effect_grant`
3. `observe_page`
4. `navigate_or_act`
5. `reconcile_operation`
6. `reconcile_persisted_operation`
7. `close_profile`

The generated registry rejects missing, duplicate or additional methods.

Registered actions are `navigate`, `click`, `type`, `credential`, `upload`, `download`, `focus`, `scroll` and `wait`. The current executable set is `navigate`, `click`, `type`, `focus`, `scroll` and `wait`. `credential`, `upload` and `download` fail closed before final-use authority or worker admission. They require separately versioned brokers and terminal observers before enablement.

Actions are exact-key closed and byte bounded. URL-bearing actions use normalized HTTP(S) URLs without embedded credentials. Navigation binds policy digest and expected revision. Secret-bearing values are live-only inputs and are not durable journal fields.

## 6. Durable data, journal v2 and migration

The product path requires `FileBrowserOperationJournal`; the memory journal is test-only. Journal schema `hepta.browser.operation-journal.v2` provides:

- immutable `requestDigest` and `semanticDigest` per operation identity;
- terminal state monotonicity;
- exact dispatch/observation duplicate no-op;
- canonical checksum-bound records and exact field validation;
- file fsync and parent-directory fsync before durable acknowledgement;
- recognition and repair of a physically torn final append;
- fail-closed rejection of newline-terminated malformed or conflicting history;
- I/O-failure fencing for the live owner;
- fail-closed cross-process owner lock with bounded dead-owner recovery;
- bounded file and record sizes;
- atomic snapshot compaction with rename and directory barriers;
- durable generation retirement preventing resurrection;
- secret-free durable records;
- signed terminal evidence digest for post-process-loss settlement.

Historical v2 duplicate histories are projected through the monotonic fold and physically migrated to one snapshot per operation. Semantic substitution and terminal rollback are never repaired into acceptance; they fail closed.

A profile generation cannot reopen while durable unresolved operations exist. Once all operations are terminal, retirement persists the generation high-water before bulky records are removed.

## 7. Concurrency, authority and effect admission

One profile is one bounded serialization domain. Queue capacity and active profile limits provide backpressure.

New effect sequence:

1. validate profile, principal, generation, current page/document revision and deadline;
2. normalize the typed action and bind final payload, proposal provenance, destination and effect grant;
3. synchronously refresh the owner-private revocation feed;
4. challenge Agentd with request digest and authority epoch only;
5. enter live `FinalUseAuthority::with_verified_use`;
6. bind the witness and fsync the durable indeterminate intent;
7. write one exact command to the selected worker;
8. worker revalidates page generation, document digest, navigation epoch, origin and actionable-surface digest;
9. worker reserves the operation and emits the exact dispatch/admission boundary immediately before effect execution;
10. Browser forwards that receipt and Agentd releases the final-use fence;
11. terminal or unknown outcome is persisted and reconciled separately.

A successful pipe write is not effect admission. A timeout without a proven negative or admitted identity terminates/quarantines the private child before the final-use fence is released. Delivering an AbortSignal alone is not containment proof.

A crossed identity never enters new-effect authority and is never blindly redispatched. Every crossed effect invalidates the previous page observation; the next new action must observe again.

## 8. Page observation, network policy and recovery

The worker emits bounded redacted semantic observations containing current origin/frame provenance, page and navigation revision, digest-bound visible text, links, forms and actionable handles with visibility/actionability. Raw page secrets are not observation or metric fields.

Immediately before click/type/focus/scroll/navigation, the worker rechecks the exact page/document/navigation revision and actionable surface. Drift is a terminal pre-effect rejection requiring re-observation.

The worker has no ordinary external network namespace. Network use is mediated by the grant-scoped broker, which bounds DNS answer count, rejects private/special addresses, freezes admitted resolution, binds exact origin and HTTPS SNI, constrains redirects/subresources and enforces response/resource limits. Profile expiry and close terminate broker and worker leases, including background traffic.

Live reconciliation asks the original worker about an admitted identity. Post-process-loss reconciliation uses a configured Ed25519 observer receipt bound to observer identity/generation, observation time, exact frontier, profile/generation/operation/request/semantic identity and outcome. Stale, future-skewed, wrong-frontier or misbound evidence remains indeterminate.

## 9. Security and privacy controls

Owned threat:

- `browser_ungranted_network`

Controls include least-authority typed actions, final-payload/provenance binding, live revocation fencing, worker-side admission, origin/page-revision checks, monotonic durable identity, fresh principal-bound profile roots, exact service/worker/launcher identities and default-deny protocols.

`verified-service-bootstrap.js` is the only production service entry. Agentd verifies that bootstrap's SHA-256. Before importing Browser code, the bootstrap verifies an embedded expected SHA-256 for `service-manifest.json`, then recomputes the Git blob ID of every transitive ESM dependency. A one-byte dependency change prevents module execution.

The production Linux launcher adds:

- exact SHA-256 for Bubblewrap, `prlimit` and reviewed seccomp BPF;
- RLIMIT_AS, CPU, NOFILE and NPROC;
- empty-root Bubblewrap namespace and restricted read-only runtime closure;
- no shared external network namespace;
- cgroup-v2 memory, PID and CPU ceilings per worker;
- seccomp FD passed directly to Bubblewrap;
- parent-death cleanup and bounded stderr drain.

The owner-private isolation policy is exact-key closed. Target qualification must prove the selected kernel, cgroup delegation, seccomp profile and launcher tuple; source posture alone is not host enforcement evidence.

## 10. Performance, capacity and hot-path policy

Hard/default source bounds include:

- 16 active profiles by default, hard configurable ceiling 64;
- one outstanding effect per current one-WebView worker;
- 128 origins/profile;
- 1024 effect grants/profile;
- 1024 generic nonterminal operation identities for compatible alternate drivers;
- 256 terminal operations retained in host memory;
- 64 queued mutations per serialization key;
- 1 MiB private frame;
- 256 KiB semantic worker observation;
- 64 MiB journal with compaction before exhaustion;
- bounded selectors, text, URLs, waits and response sizes;
- explicit authority/driver deadlines;
- default 8 GiB address-space, 300 CPU seconds, 4096 FDs and 256 processes/threads;
- production cgroup memory, PID and CPU limits from reviewed policy.

These are ceilings, not throughput claims. Exact-target soak and SLO evidence are required before activation. Parallel parent-channel multiplexing is not inferred from the profile pool; the current private parent port intentionally serializes one request at a time.

## 11. Observability and operations

`hepta-agentd-browserd` emits redacted `hepta.browser.service-metric.v1` events to stderr. Request events contain only request ID, registered method, success boolean and elapsed microseconds. Shutdown summary contains request/failure counts, maximum latency and per-method counts. URLs, selectors, typed text, page content, credentials and raw errors are excluded.

Operational policy, SLOs, alert thresholds, fault-injection matrix, CVE/pin procedure, incident response, rollback and evidence retention are normative in [`OPERATIONS.md`](OPERATIONS.md).

Safe audit fields include exact source/artifact/launcher identities, profile and worker generation, operation/request/semantic digests, admission/terminal state, terminal evidence digest, capacity and redacted failure class.

## 12. Verification and qualification

Source checks:

```sh
node apps/hepta-browser/scripts/browser-source-registry.js --check
node --test apps/hepta-browser/test/*.test.js
find apps/hepta-browser/src apps/hepta-browser/scripts -type f -name '*.js' -print0 \
  | sort -z | xargs -0 -n1 node --check
cargo metadata --locked --manifest-path apps/hepta-browser/servo-worker/Cargo.toml \
  --format-version 1 >/dev/null
```

Agentd checks:

```sh
cd codex-rs
cargo test --locked -p codex-hepta-agentd browser_servo --lib
cargo test --locked -p codex-hepta-agentd browser_revocation_feed --lib
cargo check --locked -p codex-hepta-agentd \
  --bin hepta-agentd-browser --bin hepta-agentd-browserd
cargo clippy --locked -p codex-hepta-agentd \
  --lib --bin hepta-agentd-browser --bin hepta-agentd-browserd \
  --no-deps -- -D warnings
```

Required Browser workflows are:

- `Browser required` — exact source, generated registry, committed lock, syntax and full Node suite;
- `Browser Agentd composition` — final-use/revocation tests plus diagnostic and long-running owners;
- `Browser worker exact-head evidence` — real worker, sandbox, E2E, soak and deterministic SBOM/build receipt;
- `Worker reproducibility required` — two independent hosted builders and byte comparison;
- trusted main-only deployment qualification.

Real E2E covers navigation, semantic observation, type/click, exact-origin egress, redirect/subresource denial, lease containment, revocation race, persisted recovery, cross-profile storage/cookie/cache isolation and listener absence.

## 13. Implementation sequence and completed source stages

The canonical source sequence is dependency ordered:

- **A — one source line:** seven RPCs, current worker, generated source/capability map and stable Browser required check;
- **B — durable effect core:** journal v2 monotonic identity, barriers, torn-tail repair, fencing, interprocess ownership, compaction and migration;
- **C — worker admission:** final-use release only after worker admission/boundary receipt and containment of uncertain timeout paths;
- **D — real browser observation/network:** bounded semantic observation, revision/handle revalidation and grant-scoped egress;
- **E — production source:** long-running Agentd owner, profile worker pool, lease supervisor, strong Linux launcher, verified service closure, independent reproducibility, metrics and operations runbook.

These stages are implemented in repository source. Their exact-head and target-host evidence remain independently evaluated.

## 14. Activation, compatibility and retirement

Activation requires a selected exact commit, verified bootstrap/closure, committed lock, reproducible worker/SBOM, trusted target isolation receipt, owner-private authority/revocation configuration, durable journal/reconciliation paths, capacity policy and independent operator approval.

The one-shot caller and fake/fixture launchers are not the production topology. Linux source does not certify macOS or Windows. Those platforms require separate adapters only if they enter product scope.

Retirement stops new admissions, reconciles or quarantines every unresolved operation, preserves durable history and signed evidence, terminates worker/broker leases and records an independent operator decision. It never deletes unresolved operations to regain capacity.

## 15. Definition of module completion

Documentation completion means the guide, generated registry, implementation map, worker contract and operations runbook are current and closed-world. Source completion means exact code and tests exist in declared roots. Product composition means the long-running Agentd owner and verified service path compile and pass exact-head tests. Target qualification means the exact artifact/host/policy tuple executes the required probes. Independent acceptance, activation, promotion and release remain separate.

Current source can claim implementation of the durable Browser owner, real Servo worker, worker-side admission, semantic observation, grant-scoped egress, persistent Agentd service, strong Linux launcher and qualification gates. It cannot claim current exact-head success while checks are queued/failed, trusted-target enforcement without the target receipt, actual external business terminality without the independent observer, or operator/release approval.

## 16. V8.2 implementation-readiness overlay

Primary lane: `LANE-B-RUNTIME`.

Shared readiness specifications:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Consumed readiness protocol: `SensorCalibrationManifestV1`. Ordinary owner-authorized coding follows the repository's normal protected-branch path. Runtime activation and external effects additionally require frozen artifact/policy identities and designated evidence. This overlay grants no new authority.

## 17. Source implementation receipt

Work package `BROWSER-WEB-C1` is represented in:

- `apps/hepta-browser`
- `third_party/servo-patches`
- Browser-owned documentation and qualification workflows
- the explicit cross-owner Agentd Browser port

Current source truth is generated by `apps/hepta-browser/scripts/browser-source-registry.js`; operations traceability is in `IMPLEMENTATION_MAP.json`; the worker implementation contract is in [`SERVO_WORKER.md`](SERVO_WORKER.md); production procedures are in [`OPERATIONS.md`](OPERATIONS.md).

This source receipt grants no deployment, independent acceptance, activation, promotion, merge or release authority.

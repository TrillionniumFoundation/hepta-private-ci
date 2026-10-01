# browser.servo technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `browser.servo`

**Owner:** `browser-platform`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `BROWSER-WEB-C1`

This stable document is the implementation guide for `browser.servo`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Isolate browser profiles, credentials and network effects behind exact grants.

The primary owner `browser-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `adapter`, kind `worker`, state model `isolated_stateful` and architecture role `checked_adapter` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `apps/hepta-browser`
- `third_party/servo-patches`

Existing declared roots at this source candidate:

- `apps/hepta-browser`
- `third_party/servo-patches`

Non-authoritative implementation evidence roots: none. Declared roots not yet present: none.

`existing_bound` is a source-location fact. It does not establish runtime composition, operator acceptance, selection, promotion or release.

### Native source and scope

The registered navigation source remains [apps/hepta-browser/src/browser.js](../../../apps/hepta-browser/src/browser.js). The owner operation anchors remain explicit in [apps/hepta-browser/src/runtime.js](../../../apps/hepta-browser/src/runtime.js), which delegates to the hardened state machine in `runtime-host.js` while preserving the implementation-map symbols.

Current repository-owned implementation components are:

- `browser.js` — authority-free navigation/page projections;
- `action.js` — closed bounded typed browser effects;
- `bridge.js` — navigation-intent to exact effect-payload bridge;
- `runtime.js` / `runtime-host.js` — serialized owner state machine and effect/recovery boundary;
- `journal.js` — durable browser operation journal;
- `worker-protocol.js` — private bounded worker framing;
- `worker-driver.js` — exact-artifact subprocess driver and Linux Bubblewrap launch path;
- `agentd-protocol.js` / `agentd-service.js` / `agentd-service-main.js` — private inherited parent service and final-use challenge/dispatch-boundary handshake;
- `servo-worker/` — current-pin Rust Servo embedder source with one software-rendered WebView.

The exact current Servo source pin remains `third_party/servo-patches/MANIFEST.json`. The worker and Agentd caller source are present. Source presence does **not** establish current-pin compilation or a qualified worker artifact; see [SERVO_WORKER.md](SERVO_WORKER.md) and the [module implementation dossier](../../../qualification/module-execution-dossiers/detail/browser.servo.md). The cross-owner caller is `codex-rs/hepta-agentd/src/browser_servo.rs` plus the named `hepta-agentd-browser` executable. Its one-shot host path is distinct from a long-running product runtime with a live revocation owner.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `kernel.authority`
- `runtime.agentd`

Authoritative write domains:

- `browser_profile_state`

Explicitly denied capabilities:

- `credential_export`
- `ungranted_network`

The module accepts only bounded typed inputs, rejects unknown critical action/frame fields and never interprets page/model prose as authority. Cross-owner facts remain externally owned. The browser owner may retain durable operation identities and terminal observations, but cannot mint the authority it consumes.

Non-goals include becoming a general state store, exposing raw WebDriver/CDP as the Hepta API, exporting profile/cookie/storage state, bypassing the Codex execution spine or converting qualification evidence into deployment authority.

## 4. Internal architecture and component decomposition

The implemented bounded components are:

- authority-free proposal/projection ingress;
- typed action normalizer and digest binder;
- proposal-to-effect bridge;
- per-profile single-writer runtime state machine;
- final-use authority/effect linearization boundary;
- durable operation journal and reconciliation path;
- private framed worker protocol;
- exact-artifact subprocess driver;
- Linux namespace launcher;
- parent-only Agentd module-port service;
- current-pin Servo event/render loop source;
- terminal receipt reporter.

A browser effect cannot reach `driver.dispatch` until its page generation, typed payload, destination, grant, epoch and deadline are validated. The runtime then enters `authority.withVerifiedUse(request, callback)`. Inside that final-use fence it binds the VerifiedUse witness, fsyncs the durable dispatch identity and performs one local worker dispatch. A successful revocation update therefore cannot race between final validation and effect dispatch.

An authority callback that arrives after cancellation cannot enter the consumer. The final dispatch deadline is the minimum of action, profile and effect-grant expiry, checked at authority entry and again before the driver call. Historical replay validates immutable request semantics against the durable record rather than applying a fresh deadline or minting a new identity. Crossing an effect boundary consumes the admitted page/document snapshot; another effect requires a fresh observation.

The subprocess boundary returns after the local worker-pipe write, without waiting for browser/page execution. The Agentd parent receives a separate dispatch-boundary acknowledgement so it can release live final-use authority. Remote/browser/business completion is outside that authority fence. Dispatch acknowledgement and terminal outcome are separate facts; unknown outcomes remain indeterminate and are reconciled using the original operation identity.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::browser_profile_stateV1`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::runtime_health_observationV1`
- `ModulePort::kernel.authority::browser.servo`
- `ModulePort::runtime.agentd::browser.servo`
- `VerifiedUseTokenWitnessV1`

The private worker frame is package-local implementation protocol, not a new cross-module authority contract. It binds protocol version, session, generation, sequence, request identity and canonical payload digest. Unknown/non-canonical frames fail closed.

Typed browser actions are closed-world: `navigate`, `click`, `type`, `credential`, `upload`, `focus`, `scroll`, `wait`, `download`. Navigation binds normalized URL, policy digest and expected revision. Credential/upload actions accept only references plus bounded metadata; raw secret values and ambient host paths are not legal action fields.

## 6. Data authority, persistence and migrations

Owned authoritative/recoverable domain:

- `browser_profile_state`

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `runtime_health_observation`

Profile/page state remains process-local for the live generation. Effect identities and observations have a durable path through `FileBrowserOperationJournal`:

- append-only records;
- SHA-256 checksum per envelope;
- bounded line/file sizes;
- fsync before effect dispatch;
- private mode on Unix;
- non-regular/symlink journal rejection;
- private owner/permissions and single-hard-link validation;
- immutable scalar snapshots and non-zero semantic/result digest validation;
- monotonic terminal observations: an intent/retry cannot roll a terminal result back;
- strict UTF-8, checksum and complete newline-terminated record replay;
- conflicting reused operation identities fail closed.

A restart can reconcile a persisted indeterminate operation without issuing another dispatch. Terminal operation objects are bounded in memory; their durable tombstones remain available for idempotent replay. Journal format changes require versioned migration rather than silent reinterpretation.

Journal instances for one canonical path share a process-local serialization tail. Each journal access also takes an atomic `<journal>.writer-lock` directory, so another process cannot race intent lookup and append. An uncertain write/fsync or process crash preserves that lock; no reader/writer steals it based on elapsed time or PID guesses. The durable file and its parent directory are synced before dispatch admission completes.

Owner recovery must first confirm the old writer has stopped, inspect and reconcile the durable prefix and any unresolved effect identities, establish the reviewed journal state, and sync it before explicitly removing the retained lock. A complete-looking line after failed fsync is not proof of durable admission. Recovery cannot clear an unresolved identity or authorize redispatch. There is no automatic stale-lock recovery API.

On a qualified local filesystem, replay caching binds `dev`, `ino`, `size`, `mtimeNs` and `ctimeNs`; an external append, replacement or timestamp change forces full validated replay. Filesystems without reliable coherent metadata/durability semantics need separate qualification. An identical intent/observation retry appends zero bytes.

Raw credential bytes are not journal fields. Credential references remain external identities until a separately qualified credential broker resolves them at the isolated use boundary.

## 7. Runtime, concurrency and transaction model

One profile identity is one serialization domain. `openProfile`, `admitEffectGrant`, `observePage`, `navigateOrAct`, reconciliation and close cannot race each other inside the same host instance.

Persisted and live reconciliation use that same profile lock, and a terminal durable result is synchronized into the live cache before later calls or boot replay. Terminal cache eviction cannot make a completed operation dispatch again.

For new effects:

1. admit immutable request semantics;
2. consult memory and durable journal for an existing operation identity;
3. enter final-use authority fence;
4. bind witness, fsync durable intent, dispatch locally once;
5. persist terminal/indeterminate observation;
6. never redispatch an identity that may already have crossed the effect boundary.

Driver exceptions and deadlines after durable dispatch become `indeterminate`. Reconciliation does not re-enter new-effect authorization and remains available after the original profile/effect deadline expires. Expiry/revocation blocks new mutation, not observation/cleanup of prior mutation.

A page observation outside the allowed-origin set is quarantined by removing it from actionable document state rather than merely reporting an informational flag.

## 8. Failure semantics, recovery and rollback

The runtime distinguishes pre-effect rejection from post-boundary uncertainty. Before durable dispatch, validation or authority denial rejects without claiming an external effect. After durable dispatch, timeout, transport loss or driver error retains the operation and requires reconciliation.

Profile close refuses while any durable or live operation lacks a terminal observation. A process restart uses `reconcilePersistedOperation()` against the original request/semantic digest; it cannot fabricate a fresh identity to retry the action.

Worker protocol corruption, sequence drift, cross-session/generation frames, artifact-digest drift and malformed/non-canonical payloads fail closed. The subprocess driver refuses launchers that do not state the required inherited-channel/network/environment/home/parent-death isolation posture.

Malformed response bodies, UTF-8 errors, partial/clean unexpected EOF and pipe failures permanently close the private worker channel and reject pending requests. Concurrent starts cannot overwrite an existing session; failed startup cleans its private artifact/profile state. The Node parent service cancels a pending authority read when its request expires, so a late authority frame cannot authorize another request.

The native Agentd child transport uses bounded queues and read/write deadlines. An incomplete or invalid exchange poisons the port and closes its transport; subsequent calls cannot reuse a desynchronized channel. Cleanup drops queue endpoints and does not join a blocked pipe reader/writer indefinitely.

Rollback never exports credentials and never deletes an unresolved effect merely to free capacity. Deployment rollback must preserve or quarantine the operation journal until terminal reconciliation or explicit operator disposition.

## 9. Security, privacy and threat controls

Owned threat entry:

- `browser_ungranted_network`

Security controls now include typed final-payload binding, per-profile serialization, final-use authority fencing, durable no-redispatch identity, origin quarantine, artifact SHA-256 verification and a private worker protocol with no TCP/WebDriver control surface.

Agentd's `service_sha256` currently binds the Node entrypoint file only. It does not bind imported JavaScript modules, Node itself, Bubblewrap or the complete filesystem runtime closure. Those bytes must be controlled and separately bound by a reviewed installation/build manifest before claiming immutable service deployment; hashing one entry file cannot establish that claim.

The Linux launcher uses Bubblewrap `--unshare-all` without `--share-net`, clears the environment, starts from an empty tmpfs root, mounts private `/home`, `/root`, `/run`, `/tmp`, `/proc` and `/dev` views, binds a private profile directory and uses parent-death cleanup. Its read-only allowlist exposes runtime libraries, font/fontconfig data and TLS configuration; the host root and general `/usr` tree are not bound. Exact-host qualification must inventory that allowlist and prove namespace, egress and descendant-cleanup behavior. This launcher denies all direct external networking, including networking to an admitted origin; functional web access requires a separately authorized broker rather than enabling ambient network access.

These source controls are not evidence that a real Servo worker or credential broker has passed isolation testing. Cross-profile cookie/cache/storage tests, secret-use tests and listener/egress probes against the real worker remain mandatory.

## 10. Performance, capacity and hot-path policy

Current hard source bounds include:

- <=128 origins/profile;
- <=1024 admitted effect grants/profile;
- <=1024 nonterminal operations/profile;
- <=256 terminal operations retained in memory;
- <=1 MiB page observation budget at the host API;
- <=1 MiB private worker frame;
- <=64 MiB browser operation journal;
- <=1024 pending worker requests and <=1024 abandoned-response identities;
- <=64 queued Agentd parent frames and <=4 MiB queued parent bytes;
- <=4096 stored operation identities and <=16 queued host events in the Servo worker source;
- bounded selector/text/URL/wait/upload/download fields;
- explicit driver/authority call deadlines.

Direct `SubprocessBrowserDriver` callers must supply an `AbortSignal` with a bounded deadline; the owner host supplies one through its deadline adapter. The real-worker smoke uses separate start/stop deadlines, and the sandbox probe has a bounded subprocess lifetime. These are source bounds rather than target latency/resource measurements.

The dossier pilot target of <=16 concurrent tabs/profile remains a target rather than a measured current worker capability. Real Servo RSS, renderer descendants, descriptors, observation cost, reconciliation latency and download behavior require target measurements.

## 11. Observability and operations

Safe source-level observations include profile/process/page generations, operation/request/semantic digests, worker artifact digest, terminal/indeterminate state and redacted failure reason. Raw credential values, upload host paths and raw page secrets are not observability fields.

The private subprocess path is artifact-bound before launch and allocates a fresh private profile directory. The current Linux launcher is executable host code, but no source statement upgrades it to deployed isolation evidence. The actual selected Bubblewrap/kernel/worker tuple must be probed for egress, listener, descendant cleanup and filesystem exposure.

Operating references:

- [apps/hepta-browser/README.md](../../../apps/hepta-browser/README.md)
- [SERVO_WORKER.md](SERVO_WORKER.md)
- [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json)
- [implementation dossier](../../../qualification/module-execution-dossiers/detail/browser.servo.md)

## 12. Verification and qualification

Run all browser package tests from the repository root:

```sh
node --test apps/hepta-browser/test/*.test.js
```

Focused sources cover:

- `agentd-main.test.js` — the actual Node service entry accepts the real owner class and ends a persistent fixture worker on parent EOF; this is not real Servo or Bubblewrap qualification.

- `browser.test.js` — canonical authority-free proposal and page projection inputs;
- `action.test.js` — typed payload/policy/secret-reference bounds;
- `bridge.test.js` — proposal -> exact effect binding;
- `runtime.test.js` — duplicate exclusion, final-use fencing, timeouts, expiry recovery, durable crash reconciliation and bounded retention;
- `journal.test.js` — reopen, permissions and tamper failure;
- `worker-protocol.test.js` — frame canonicalization, digest/size/partial-frame failure;
- `worker-driver.test.js` — artifact binding, private subprocess request path and Linux namespace argv posture.
- `agentd-service.test.js` — parent final-use challenge, witness binding and dispatch-boundary handshake.
- `journal-monotonicity.test.js` / `journal-durability.test.js` — terminal immutability, scalar snapshots, strict replay, shared-path/cross-process locking and uncertain-durability fencing;
- `worker-evidence.test.js` — exact canonical pin/repository consistency, resolved feature policy and source/tree/lock/SBOM/smoke artifact bindings.

The exact-source Rust composition checks target `codex-hepta-agentd` and `hepta-agentd-browser`; they exercise the real `FinalUseAuthority` fence with a deterministic transport. Worker source additionally requires its separate locked current-pin build, feature-graph, reproducibility, SBOM and real-sandbox smoke gate. Node fixture-worker results do not compile or execute Servo.

These remain source tests. Completion of BROWSER-01..04 against the real current-pin Servo worker requires exact worker artifact/build evidence plus target isolation and real terminal observations.

## 13. Implementation sequence and work packages

Applicable work package:

- `BROWSER-WEB-C1`

The bootstrap package remains `BROWSER-WEB-C1`. Development, activation and evidence predecessor graphs are distinct. The current source hardening does not change the canonical delivery registry's state by itself.

The next qualification sequence is defined in [SERVO_WORKER.md](SERVO_WORKER.md): compile the existing worker source against the exact current pin and reviewed lock, inspect the feature graph, bind reproducible artifact/SBOM evidence, execute the real worker inside the Linux sandbox, then qualify Agentd composition and terminal effect/recovery behavior. Equivalent macOS/Windows launchers, credential/upload/download brokers and authorized network delivery remain separate implementation work when those capabilities are targeted.

## 14. Activation, compatibility and retirement

Activation requires the existing named non-test caller through `runtime.agentd` / authority ports to execute against an exact qualified worker artifact, target sandbox configuration, durable journal path, live final-use/revocation owner, resource limits and failure/recovery evidence. The one-shot `hepta-agentd-browser` source caller is present; it does not establish a persistent open/observe/act session or daemon activation.

Shadow/fake drivers and protocol fixture workers are not production callers. A Linux sandbox result does not certify macOS/Windows. A source-complete module remains inactive until activation predecessors and evidence gates pass.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and exact-candidate tests. Composition requires a named caller. Qualification requires the current worker/build/host tuple and independent evidence. Acceptance, selection, promotion and release remain separately governed.

Current source contains a durable owner boundary, private worker and parent protocols, an artifact-bound Linux subprocess launch path, a current-pin Servo embedding/event/render implementation and a named Agentd source caller. A passing exact-candidate test establishes only the behavior it actually exercises. The repository cannot claim a qualified worker binary, real Servo WebView execution evidence, credential/upload/download integration, authorized web access, cross-platform sandbox qualification, activated persistent product caller, real external-effect completion, operator acceptance, promotion or release without the corresponding receipts.

### Work-package execution envelope

#### `BROWSER-WEB-C1`

- State: `planned`; priority: `2`; parallel class: `independent_source_preparation`.
- Owner/deputy: `browser-platform` / `security-authority`.
- Allowed write paths: `apps/hepta-browser/**`, `third_party/servo-patches/**`.
- Development predecessor: `DOC-1-V8-SEMANTIC-UPGRADE`.
- Activation predecessor: `P0.7B-B2-TOOL-NET-FS`.
- Required deliverables: exact source identity/inventory; static/focused/package tests; all-target/lint/clean-tree evidence; exact-head and merge-candidate execution; source baseline/root/doc/source-binding updates.
- Stop conditions: authority violation, base drift, claim/evidence mismatch, cross-owner write, unbounded resource/retry.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `browser.servo` to `LANE-B-RUNTIME`. Mandatory shared specifications remain:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols: none. Consumed readiness protocol: `SensorCalibrationManifestV1`.

Ordinary authorized coding identifies the Git baseline, contracts, owned paths, fixtures, deterministic fallback and rollback. A runtime coordinator still verifies current source receipt, frozen digests, expiry and zero authority delta. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `browser.servo` is implemented by work package `BROWSER-WEB-C1` in:

- `apps/hepta-browser`
- `third_party/servo-patches`

`.github/workflows/hepta-consolidated-source.yml` defines inventory, package tests, all-target compilation, strict Clippy and clean-state checks. The separate Browser worker and Agentd composition workflows define deeper opt-in gates. A workflow definition is not a successful execution receipt and does not by itself prove aggregate CI selected the affected Browser tests. Use actual exact-candidate logs and artifacts to identify executed checks. Source implementation evidence grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority. The current audit and its verification boundary are recorded in [AUDIT.md](AUDIT.md).

`blocking-ci.yml` now selects Browser Node regression tests for Browser sources, relevant Agentd caller sources and canonical Servo patch inputs, and includes the job in its required fan-in. The Cargo impact planner explicitly maps the private-process Browser runtime to its Agentd caller and reverse consumers instead of treating it as an unowned input that expands to the entire Rust workspace. Expensive native Servo artifact/target qualification remains opt-in; passing Node source checks cannot substitute for it.

# browser.servo isolated worker implementation contract

**Module:** `browser.servo`  
**Current upstream pin:** `servo/servo@b5a1f5e6ec6f8685d40cd389802ced7abe4980f6`  
**Canonical pin source:** `third_party/servo-patches/MANIFEST.json`  
**Lock state:** exact reviewed b5a1 `apps/hepta-browser/servo-worker/Cargo.lock` committed  
**Status:** worker source, private protocols, admission boundary, semantic observation, grant-scoped egress and persistent Agentd service source implemented; exact-main signed artifacts, target qualification, activation and independent acceptance remain gated

This contract is subordinate to [`TECHNICAL.md`](TECHNICAL.md), the generated source registry and the implementation map. Historical branches, pull-request descriptions and older Servo pins are provenance only.

## 1. Process and authority topology

One admitted profile generation owns:

- one private profile directory;
- one private Servo worker process;
- one Servo instance;
- one software rendering context;
- one WebView;
- one profile-scoped host egress broker;
- one Browser journal generation.

The worker has no public WebDriver/CDP/TCP/HTTP control listener. It receives only canonical bounded commands over inherited stdin/stdout. Caller-provided arbitrary JavaScript is not a legal Browser action; worker-owned fixed templates implement bounded click/type/focus/scroll behavior.

The parent chain is:

```text
trusted supervisor/product caller
  -> hepta-agentd-browser-service
  -> private Browser service
  -> profile-affine Servo worker
  -> private profile-scoped egress broker
```

`hepta-agentd-browser-service` retains one persistent Browser control across bounded inherited-stdio calls. The one-shot `hepta-agentd-browser` remains diagnostic/compatibility source. The default Agentd daemon does not automatically activate Browser and no component invents a permissive authority, artifact, network scope or observer configuration.

## 2. Current worker source

`apps/hepta-browser/servo-worker` is an out-of-tree Hepta-owned worker using Servo's public embedding API. It is pinned with `default-features = false` and the reviewed feature set declared in `Cargo.toml`/`SERVO_CURRENT_PIN_TOPOLOGY.json`.

The worker:

- creates one `Servo`, one `SoftwareRenderingContext` and one `WebView`;
- denies unregistered navigation and permission requests;
- pumps Servo's event loop and paints software frames;
- accepts canonical `start`, `observe`, `dispatch`, `reconcile` and `stop` commands;
- stores bounded operation admission/terminal state for the live generation;
- emits dedicated worker-admission or proven rejection frames;
- exports bounded semantic observations;
- rejects credential/upload/download as disconnected capabilities.

The exact reviewed lock is committed. CI is prohibited from generating a candidate lock and then treating it as reviewed source.

## 3. Private worker protocol

`hepta.browser.worker-frame.v1` consists of a four-byte big-endian length prefix and at most 1 MiB canonical JSON. Every frame binds:

- schema and protocol version;
- session ID and profile generation;
- monotonic sequence;
- request ID and kind;
- canonical payload digest;
- bounded payload.

Response frames additionally bind the original request kind, request payload digest and request sequence. Unknown keys, unsafe numbers, non-canonical JSON, partial frames, digest drift, sequence drift, cross-session/generation data and unknown request identities fail the channel.

Worker stderr is continuously drained into a bounded diagnostic tail and never copied into effect journals or terminal receipts.

## 4. Worker admission, not pipe-write admission

For `navigate_or_act`, Browser first persists the immutable operation as indeterminate under live final-use authority. It then writes one worker request. The worker must:

1. decode and verify the exact frame;
2. verify profile/session/generation;
3. verify operation identity has not changed semantics;
4. revalidate current page generation, document digest and navigation epoch;
5. recompute and compare the actionable-surface digest;
6. validate the selected destination and typed action;
7. reserve the operation identity;
8. emit `dispatch_boundary` immediately before execution.

A known pre-effect failure emits `dispatch_rejected { localDispatchCrossed:false }`. A pipe write by itself is not a crossed effect and is never forwarded to Agentd as the final-use boundary.

If Browser cannot prove either admission or rejection before its hard parent deadline, it terminates/contains the private child and returns an indeterminate outcome. An AbortSignal without observed process containment is not sufficient proof.

## 5. Semantic page observation

The worker's fixed observation projection returns bounded `hepta.browser.semantic-observation.v1` data:

- page origin and revision;
- title and bounded visible text;
- HTTP(S) links;
- forms;
- visible actionable controls with unique page-local selectors;
- non-secret input metadata;
- viewport dimensions;
- frame/origin provenance;
- semantic and actionable-surface digests.

Password values, hidden controls, control values, raw HTML and unrestricted DOM are not exported. Browser rechecks the canonical digest and observation byte budget.

Immediately before effect admission, the worker recomputes the document/actionable surface. Click/type/focus must refer to the exact admitted surface. Disabled, invisible, password or non-text-entry targets fail closed. A crossed effect invalidates the prior observation, requiring a fresh observation for the next effect.

## 6. Typed action implementation state

Implemented and admitted:

- `navigate`;
- `click`;
- `type`;
- `focus`;
- `scroll`;
- `wait`.

Registered but deliberately rejected at Browser ingress:

- `credential`;
- `upload`;
- `download`.

Those future actions cannot consume final-use authority or cross worker admission until a separately versioned and qualified broker/terminal observer exists.

## 7. Grant-scoped network architecture

The worker's Bubblewrap network namespace has no direct external route. Servo is configured to use a sandbox-loopback relay that reaches a private Unix socket in the profile bind. The host-side broker:

- admits only exact profile-granted origins;
- freezes DNS answers under the profile grant;
- rejects loopback/private/link-local/multicast/special addresses;
- does not re-resolve names after admission;
- validates HTTP origin;
- validates HTTPS CONNECT authority/port and bounded ClientHello SNI;
- applies response/header/body/time limits;
- blocks redirect, subresource and profile-scope escape;
- closes on profile expiry or explicit close.

Top-level navigation is additionally bound to the current effect's exact destination origin. A redirect to another generally allowed profile origin is denied unless that effect selected it.

## 8. Profile state and isolation

Every worker generation receives a fresh random profile directory. Browser stores the mode-0600 `hepta.browser.profile-owner.v1` manifest outside the writable sandbox bind and independently recomputes its digest from:

- profile ID;
- principal ID;
- generation;
- Browser manifest digest;
- profile grant digest.

A mismatched startup ownership observation triggers containment. Profile bytes are not reopened under another principal or silently reused after clean retirement.

The real E2E oracle checks cookie, localStorage and cache isolation across profiles. Source tests are not a substitute for a successful exact target-host receipt.

## 9. Linux launch and resources

`LinuxBubblewrapLauncher` starts from an empty tmpfs root, clears the environment and uses `--unshare-all` without sharing external networking. It exposes only the verified worker and a narrow read-only runtime/font/CA closure plus one writable private profile. General host binaries, user homes, service roots and ambient `/var/lib` are absent.

Before Bubblewrap exec, exact SHA-256-bound `prlimit` applies default ceilings:

- RLIMIT_AS: 8 GiB;
- RLIMIT_CPU: 300 seconds;
- RLIMIT_NOFILE: 4096;
- RLIMIT_NPROC: 256.

Parent death cleanup is mandatory. The real sandbox probe verifies host-secret invisibility, general-binary absence, direct-egress denial, private-profile durability, exact resource limits and disappearance of Bubblewrap plus reported descendants.

macOS and Windows are outside the current deployment target. They require equivalent isolation adapters and exact-host evidence before entering scope.

## 10. Durable identity and terminality

Browser records a version-2 durable dispatch identity before worker admission. The worker's live operation map assists in-process reconciliation, but it is not accepted as cross-process terminal evidence.

After process loss, a new worker may not assert what the old worker or remote business system did. Terminalization requires `hepta.browser.persisted-effect-observation.v2`, signed by the configured independent Ed25519 observer and bound to exact observer/profile/operation/request/semantic/frontier/time/outcome fields. Missing, stale, future, rollback, misbound or unauthenticated receipts remain indeterminate.

The durable journal is monotonic, exact-duplicate idempotent, crash-torn-tail aware, parent-directory fsynced, I/O-fenced, compacted and generation-retirement fenced. It excludes the full typed action and raw sensitive payloads.

## 11. Primary build qualification

`.github/workflows/hepta-browser-servo-worker-dev.yml` requires the exact source SHA and committed lock, then performs:

- Rust 1.88.0 setup and explicit prerequisites;
- dependency/feature graph capture;
- `webdriver_server` rejection;
- `cargo check --locked` and worker tests;
- complete Browser tests and syntax checks;
- real Bubblewrap/resource/descendant probe;
- two same-runner exact-input release builds and byte equality;
- dynamic-library closure;
- real worker start/stop;
- real Browser lifecycle/egress/profile-isolation E2E;
- 32-cycle RSS/FD soak;
- deterministic SPDX 2.3 SBOM;
- exact digests and primary build receipt.

The primary receipt states `sameRunnerByteIdenticalBuilds=true` but does **not** claim independent reproducibility.

On `main`, the workflow uses pinned `actions/attest` to create:

- SLSA build provenance for the worker;
- SPDX 2.3 SBOM attestation for the worker.

## 12. Independent rebuild and trusted target gate

`.github/workflows/hepta-browser-servo-independent-rebuild.yml` rebuilds the same exact source, pin, lock, toolchain and deterministic flags on a separate ephemeral GitHub-hosted runner. On `main`, it emits separate signed SLSA provenance.

The manual main-only deployment workflow requires two different successful run IDs and the reviewed worker digest. It verifies:

- both runs belong to exact `main` SHA and expected workflow;
- exact source tree, pin and committed lock;
- byte-identical worker artifacts;
- primary and independent receipts;
- primary SLSA provenance;
- primary SPDX 2.3 SBOM attestation;
- independent SLSA provenance;
- exact signer workflows and source ref/digest;
- non-self-hosted signing builders;
- verified timestamp/transparency witness and signing certificate.

Only after cryptographic verification does it emit a multi-builder receipt with `reproducibleIndependentBuilds=true`. It then reruns real sandbox, worker, E2E, public HTTPS and soak probes on the trusted target and emits a target receipt that keeps operator acceptance, activation, promotion and release false.

## 13. Agentd composition gate

`.github/workflows/hepta-browser-agentd-composition.yml` verifies:

- generated source registry;
- complete Browser Node suite;
- JavaScript syntax;
- Agentd formatting;
- legacy and persistent final-use/revocation tests;
- persistent service binary unit target;
- diagnostic and persistent caller compilation;
- strict Clippy with no warnings.

The persistent service is a source composition, not a deployment claim. It has no listener and must be started by a trusted supervisor/product caller with exact artifacts and a closed trusted configuration.

## 14. Failure semantics

Pre-admission failures cannot claim an effect. Proven worker rejection is terminal no-dispatch. Post-admission timeout, channel loss, worker crash or unknown terminal response remains indeterminate.

No path turns:

- timeout into retry authority;
- replacement worker state into prior terminal evidence;
- profile expiry into permission to discard unresolved operations;
- journal capacity pressure into semantic deletion;
- source/CI presence into activation or release authority.

Rollback preserves unresolved journals and observer evidence until reconciliation or explicit externally governed disposition.

## 15. Operational checklist

Before starting the persistent service:

1. verify service, worker, Bubblewrap and `prlimit` digests;
2. verify private canonical journal/profile/revocation paths and modes;
3. open final-use authority with trusted issuer keys and current epoch/frontier;
4. require the initial revocation-feed refresh to succeed;
5. freeze the observer tuple when persisted terminalization is enabled;
6. apply profile/worker/resource limits;
7. start only through inherited private pipes;
8. retain exact source/artifact/host identities in evidence.

During operation monitor profile/worker counts, queue depth, indeterminate age, journal utilization/fencing, revocation lag, admission latency, containment actions, network denials, semantic-observation size, RSS/FD/process counts and descendant cleanup.

On shutdown stop admission, reconcile/quarantine crossed operations, close terminal profiles, observe worker/broker/descendant termination and preserve unresolved journals. Do not delete unresolved state to make rollback appear successful.

## 16. Remaining gates

Repository source is present for durable effects, worker admission, semantic observation, grant-scoped egress, Linux isolation, persistent Agentd ownership, committed b5a1 lock, independent rebuild and signed-provenance verification.

Still required before a production/release claim:

- terminal-success exact-head and synthetic-merge checks for the final candidate;
- successful signed primary and independent artifacts produced from merged `main`;
- successful manual trusted Linux target qualification;
- trusted product/supervisor activation of the named service;
- independent operator acceptance, promotion and release;
- independently trusted remote-business terminal receipts where business terminality is claimed;
- credential/upload/download brokers if those capabilities are enabled;
- platform-equivalent isolation only if macOS/Windows enter product scope.

Current truth remains:

```text
productionImplementation = false
deploymentQualification = false
operatorAcceptance = false
activation = false
promotion = false
release = false
```

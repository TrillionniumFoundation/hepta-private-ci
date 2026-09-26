# browser.servo isolated Servo worker contract

**Module:** `browser.servo`  
**Selected upstream:** `servo/servo@b5a1f5e6ec6f8685d40cd389802ced7abe4980f6`  
**Lock:** committed `apps/hepta-browser/servo-worker/Cargo.lock`  
**Source state:** implemented  
**Exact-head, trusted-target and independent activation state:** separately governed

This document is the current Browser/Servo implementation contract. Historical branch and PR descriptions are not capability evidence. Exact RPCs, capabilities and source objects are generated in [`GENERATED_SOURCE_REGISTRY.json`](GENERATED_SOURCE_REGISTRY.json).

## 1. Trust and process boundary

One admitted profile generation owns one private Servo worker, one private profile directory and one grant-scoped egress broker. The Browser owner holds profile/page/operation state and the durable journal. Agentd owns final-use authority and its monotonic revocation feed.

The worker exposes no TCP, HTTP, WebDriver or CDP listener. It accepts only canonical length-prefixed frames over inherited stdin/stdout. Caller-provided arbitrary JavaScript is not an action. Worker-owned fixed templates implement bounded element actions.

The Browser service is also private-parent-only. Production uses long-running `hepta-agentd-browserd`; the one-shot binary is diagnostic.

## 2. Exact source pin and dependency closure

The worker manifest uses Servo with `default-features = false` and the reviewed selected features. The exact upstream commit appears in `Cargo.toml`, committed `Cargo.lock`, `third_party/servo-patches/MANIFEST.json`, pin audit and topology registry.

Qualification fails if the lock is absent, generated during CI or does not contain the selected commit. The dependency graph is captured and rejects the WebDriver server capability.

A pin update is a new qualification cycle: manifest, committed lock, feature graph, worker tests, real E2E, independent reproducibility, SBOM, target qualification and operator decision all rerun. See [`OPERATIONS.md`](OPERATIONS.md).

## 3. Private worker protocol and admission boundary

Protocol `hepta.browser.worker-frame.v1` binds:

- protocol version;
- profile/session identity;
- worker generation;
- monotonic request and response sequence;
- request identity;
- canonical payload digest;
- exact response echo of request kind, request sequence and payload digest.

Unknown fields, non-canonical JSON, digest drift, sequence drift, wrong session/generation, duplicate live request identity or unexpected frame type terminate/fail the channel.

For a new effect, Browser first persists the immutable indeterminate intent. The worker then:

1. decodes and validates the exact request;
2. verifies profile and generation;
3. revalidates page/document/navigation revision and actionable surface;
4. checks operation identity reuse;
5. reserves the operation;
6. emits the exact worker admission/dispatch-boundary frame immediately before execution.

Agentd does not release final-use authority merely because bytes were written to a pipe. It releases only after Browser forwards the worker boundary. A worker-confirmed stale-state rejection is a terminal pre-effect negative outcome. Timeout/channel uncertainty terminates or quarantines the child and retains the durable identity.

## 4. Servo and WebView topology

The worker owns:

- one `Servo`;
- one software rendering context;
- one `WebView`;
- one allowed-origin set;
- one monotonic page/navigation generation;
- one bounded operation registry;
- one private protocol event loop.

Navigation uses the public Servo embedding API. Permission requests default deny. Unregistered navigation origins are denied. The worker pumps Servo events, paints the software context and reports load/terminal state through the private protocol.

Each profile generation starts from a fresh host-created private directory. Browser keeps the principal/profile ownership manifest outside the worker's writable bind and independently checks its digest before accepting startup.

## 5. Semantic observation and actions

The worker returns bounded `hepta.browser.semantic-observation.v1` data, including origin and frame provenance, page/navigation revision, digest-bound visible text, links, forms and actionable handles with visibility/actionability. Observation size is hard bounded and sensitive values are redacted/omitted.

Implemented effects:

- `navigate`
- `click`
- `type`
- `focus`
- `scroll`
- `wait`

Registered but fail-closed:

- `credential`
- `upload`
- `download`

Before an element action, the worker verifies the exact current document and actionable-surface digest. DOM/navigation drift rejects the request before effect execution and requires a new observation. A selector or handle from a prior page revision cannot silently act on a replacement element.

## 6. Grant-scoped network path

The worker has no ordinary host or external network authority. Network requests use the Browser-owned broker, which is scoped to the current profile/effect grant and enforces:

- bounded DNS answer sets;
- frozen admitted DNS/IP result;
- private, loopback, link-local, multicast and special-address denial;
- exact HTTP(S) origin;
- HTTPS CONNECT/ClientHello SNI binding;
- redirect and cross-origin escape denial;
- bounded subresource policy;
- bounded response/body/time resources;
- broker termination on profile expiry or close.

Page JavaScript cannot turn a profile-level origin allowance into an unbounded network capability. Real E2E probes cover exact-origin use, redirect escape, cross-origin subresources, background traffic at expiry/close and listener absence.

## 7. Durable identity and reconciliation

Browser journal v2 persists secret-free operation semantics before worker admission. It provides immutable semantic identity, terminal monotonicity, exact-duplicate no-op, file and parent-directory barriers, torn-tail prefix repair, I/O fencing, interprocess ownership, bounded compaction and retired-generation fencing.

The worker retains admitted operation identities during its lifetime. Live reconciliation queries that original worker identity. A replacement worker is not accepted as evidence that an old effect completed.

After Browser/worker process loss, terminalization requires a signed `hepta.browser.persisted-effect-observation.v2` receipt from the configured independent observer. It binds observer generation/time/frontier and exact operation/request/semantic/outcome identity. Missing, stale, future, wrong-frontier or invalid evidence leaves the operation indeterminate.

## 8. Linux launch and containment

The base launcher verifies exact Bubblewrap and `prlimit` binaries and applies:

- an empty tmpfs root;
- selected read-only runtime libraries/fonts/TLS data;
- hidden general host binaries and user/service roots;
- cleared environment;
- private proc/dev/tmp/run/home/root views;
- no shared external network namespace;
- one private writable profile bind;
- one read-only verified worker artifact;
- parent-death cleanup;
- RLIMIT_AS, CPU, NOFILE and NPROC.

The production launcher additionally verifies a reviewed seccomp classic-BPF file, passes it by inherited FD, creates a per-worker cgroup-v2 child and applies memory, OOM-group, PID and CPU ceilings before recording the process in `cgroup.procs`.

These are executable source controls. Trusted-target qualification must prove the exact kernel, delegation, seccomp and launcher tuple.

## 9. Service artifact closure and Agentd ownership

Agentd configuration selects `verified-service-bootstrap.js` and verifies that file's SHA-256. The bootstrap has no Browser imports. Before loading the production service, it:

1. reads fixed `service-manifest.json` without following a final symlink;
2. verifies its embedded expected SHA-256;
3. validates exact manifest schema and bounded file count;
4. recomputes the Git blob identity of every listed ESM dependency;
5. imports `agentd-service-production-main.js` only after all objects match.

This closes the prior gap where hashing only the entry file did not bind its imported modules.

`hepta-agentd-browserd` retains `PersistentBrowserServoControl`, the private Browser child, live revocation watcher and restart policy for multiple bounded requests over inherited stdio. Its stderr metrics are redacted and contain method, status and latency only.

## 10. Build, reproducibility and provenance

`Hepta Browser Servo worker dev` requires the committed lock and produces:

- exact source/tree identity;
- toolchain identity;
- locked metadata and feature graph;
- worker check/tests;
- all Browser Node tests and generated registry validation;
- real sandbox probe;
- two same-host clean-target builds and byte comparison;
- dynamic library closure;
- real worker smoke;
- real Browser E2E;
- 32-cycle resource soak;
- deterministic SPDX-2.3 SBOM;
- checksum-bound build receipt.

`Hepta Browser worker reproducibility` builds the exact committed-lock source on two independent hosted runners and requires byte-identical artifacts in a third comparison job. The comparison receipt does not self-issue operator acceptance or release.

## 11. Target qualification

Trusted Linux target qualification must consume a successful exact-main build/reproducibility artifact and revalidate:

- source, lock, worker, SBOM and service closure identity;
- Bubblewrap, `prlimit`, cgroup delegation and seccomp policy;
- host secret invisibility and general-binary absence;
- direct-network denial and broker-mediated public HTTPS;
- no externally reachable worker listener;
- profile and cross-profile isolation;
- revocation/admission races;
- crash reconciliation;
- parent/descendant cleanup;
- bounded RSS, FDs, processes and journal behavior.

The target receipt keeps operator acceptance, activation, promotion and release false unless separately issued.

## 12. Remaining external decisions

Repository source does not prove:

- that the current exact PR/main workflows are terminal-success until GitHub reports them so;
- that a particular production host enforced cgroup/seccomp/namespace policy without its target receipt;
- actual remote business terminality without the independent observer's current signed receipt;
- operator acceptance, activation, promotion or release.

Credential, upload and download also remain disabled until their dedicated security and terminal-observation designs are implemented and qualified.

See [`TECHNICAL.md`](TECHNICAL.md), [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json), [`SERVO_CURRENT_PIN_TOPOLOGY.json`](SERVO_CURRENT_PIN_TOPOLOGY.json), [`SERVO_PIN_AUDIT.md`](SERVO_PIN_AUDIT.md) and [`OPERATIONS.md`](OPERATIONS.md).

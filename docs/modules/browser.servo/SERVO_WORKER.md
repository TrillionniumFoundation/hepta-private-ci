# browser.servo isolated worker implementation contract

**Status:** hardened Browser owner boundary + current-pin Servo worker source + private Agentd final-use handoff implemented; exact artifact/target qualification and independent acceptance remain gated  
**Module:** `browser.servo`  
**Current upstream pin:** `servo/servo@84bcc9ac701874fa9819e5cdee06356b961d736c`  
**Canonical pin source:** `third_party/servo-patches/MANIFEST.json`

This is the current implementation-level Browser/Servo contract. Historical WEB-C1 documents that name older Servo commits are provenance only unless explicitly revalidated here. Source presence, CI configuration and author statements are never deployment/release evidence.

## 1. Trust and process boundary

One admitted profile generation owns one private Servo worker process and one fresh private profile directory. Browser owns the live profile/page state, durable effect identities, worker artifact binding and Browser/Servo protocol. The verified worker copy is stored outside the profile directory mounted read/write into the sandbox and is exposed to the worker only through the read-only `/hepta-worker` bind; cleanup removes both the executable copy and profile directory. The worker exposes no public WebDriver/CDP/TCP/HTTP listener and accepts no caller-provided arbitrary JavaScript.

Agentd owns the parent-side composition. The Browser service is inherited stdio only:

- `src/agentd-protocol.js` — bounded canonical parent frames;
- `src/agentd-service.js` — request dispatch plus authority challenge/enter and worker-admission `dispatch_boundary` / proven pre-dispatch `dispatch_rejected` handshake;
- `src/agentd-service-main.js` — private Browser service executable;
- `codex-rs/hepta-agentd/src/browser_servo.rs` — Agentd private-child port and real final-use authority handoff;
- `codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs` — named one-shot non-test caller source.

There is no Browser discovery listener. The default long-running Agentd daemon remains fail-closed unless a trusted owner supplies the authority/revocation and artifact configuration required for activation.

## 2. Implemented source surfaces

| Surface | Source | State |
| --- | --- | --- |
| bounded typed actions | `src/action.js` | implemented |
| proposal -> effect bridge | `src/bridge.js` | implemented with proposal provenance binding |
| serialized profile/effect host | `src/runtime-host.js` | implemented |
| bounded mutation queue | `src/runtime-boundary.js` | implemented |
| durable operation journal | `src/journal.js` | implemented with strict hydration, compaction and retirement |
| Browser -> Servo private protocol | `src/worker-protocol.js` | implemented |
| artifact-bound subprocess driver | `src/worker-driver.js` | implemented |
| Agentd -> Browser private protocol | `src/agentd-protocol.js` | implemented |
| Agentd parent service | `src/agentd-service.js` | implemented |
| real Agentd final-use handoff | `codex-rs/hepta-agentd/src/browser_servo.rs` | implemented in source |
| named Agentd Browser caller | `hepta-agentd-browser` | implemented in source |
| Linux Bubblewrap + prlimit source contract | `src/worker-driver.js` | implemented; exact host executables and resource ceilings bound; target evidence required |
| real Linux sandbox/resource probe | `scripts/linux-sandbox-probe.js` | implemented |
| current-pin Servo worker | `servo-worker/` | implemented in source; reproducible artifact receipt required |
| semantic page observation | `servo-worker/src/main.rs` | implemented in source |
| build/repro/SBOM gate | `.github/workflows/hepta-browser-servo-worker-dev.yml` | implemented |
| Agentd composition gate | `.github/workflows/hepta-browser-agentd-composition.yml` | implemented |
| trusted Linux deployment evidence gate | `.github/workflows/hepta-browser-servo-deployment-qualification.yml` | implemented main-only gate |
| macOS / Windows equivalent launchers | none | not implemented |
| functional credential secret broker | none | not connected; action fails closed |

## 3. Exact final-use linearization

For a new effect Browser first validates page/document generation, typed action, proposal provenance, destination, final payload digest, operation identity, grant, epoch and deadline. It then emits an exact authority challenge to Agentd.

Agentd verifies that challenge against the independently signed final-use binding and calls the real persistent `FinalUseAuthority::with_verified_use`. While the live revocation mutex is held:

1. Agentd sends `authority_enter`;
2. Browser binds the current VerifiedUse witness;
3. Browser fsyncs an indeterminate durable dispatch record;
4. Browser writes exactly one command to the private Servo-worker pipe;
5. the Servo worker dequeues the command, revalidates page generation, document digest, navigation epoch and actionable-surface digest, reserves the operation identity and emits `dispatch_boundary` immediately before effect execution;
6. Browser forwards the worker admission boundary to Agentd. A worker-confirmed stale-state rejection instead produces `dispatch_rejected { localDispatchCrossed:false }`.

A successful pipe write is not the final-use boundary. Only the worker-side admission ACK releases the revocation fence as crossed, so queue wait and final worker-side stale-state validation remain inside the live revocation fence. Worker/page/business terminality after admission is a separate observation and reconciliation claim.

A concurrent revocation update cannot become current between final-use validation and worker admission. A worker-confirmed pre-dispatch rejection is a terminal failed/no-dispatch outcome; timeout, channel loss or other uncertainty without such proof remains indeterminate. A post-boundary timeout/error cannot make the operation identity fresh or authorize redispatch.

## 4. Proposal provenance and typed action boundary

`BrowserNavigationIntentV1` remains authority-free. The effect bridge preserves:

- `navigationId` -> `operationId`;
- `policyDigest` -> typed `navigate.policyDigest`;
- `expectedRevision` -> typed `navigate.expectedRevision`;
- normalized URL -> typed `navigate.url` and destination origin.

The canonical typed-action digest is the `finalPayloadDigest`; the operation request digest includes operation/page/profile identity and typed-action semantics. Thus the final authority request is bound to the exact proposal revision, not merely to a destination URL.

Registered action kinds are bounded forms of:

- `navigate { url, policyDigest, expectedRevision }`;
- `click { selector }`;
- `type { selector, text }`;
- `credential { selector, credentialRef }`;
- `upload { selector, fileRef, fileDigest, maxBytes }`;
- `focus { selector }`;
- `scroll { deltaX, deltaY }`;
- `wait { condition, timeoutMs }`;
- `download { url, maxBytes }`.

Credential/upload actions carry opaque references, not host paths or raw secrets. The current worker rejects credential/upload/download as `capability_not_connected` until their dedicated broker/terminal observer is qualified.

## 5. Secret-free durability and profile ownership

The durable operation record deliberately excludes the full `typedAction`. It persists the final payload digest and immutable request/effect identity, so `type.text` is not copied into the journal even when the live action carries sensitive text. Raw credential bytes, upload bytes, page HTML and worker stderr are also excluded from durable records. Browser requires persistent durability by default; the memory journal is a deliberate test-only opt-in.

The file journal performs exact field validation on every hydrated record, rejects unknown fields, validates checksum envelopes and semantic identity, fsyncs before dispatch, uses private non-symlink files and parent directories, compacts atomically before the file ceiling and retires a fully terminal profile generation only after fsyncing a separate private generation high-water, so deleting bulky terminal records cannot resurrect the same profile generation after restart. A profile generation with durable operation history cannot be reopened into a fresh worker; unresolved durable effects from another generation block profile advancement. Persisted recovery observes the old identity without redispatch, and automatically retires the generation once all recovered operations are terminal.

Every subprocess worker generation receives a fresh random private directory. Browser writes a mode-0600 `hepta.browser.profile-owner.v1` manifest binding:

- profile ID;
- principal ID;
- profile generation;
- Browser manifest digest;
- profile grant digest.

Stale cookie/cache/profile bytes are not implicitly reopened by reusing `${profileId}.${generation}`. An observed origin outside the grant immediately quarantines the profile and invokes driver containment, killing the private worker before any new effect can be admitted; reconciliation and final cleanup remain available. Successful stop removes that private directory. Real cross-principal cookie/cache/storage isolation is still independently tested on the real qualified worker/host tuple.

## 6. Semantic page observation

The real worker `observe` path executes one fixed worker-owned script through Servo's public embedding API and returns `hepta.browser.semantic-observation.v1`. The bounded observation may contain title, visible text, HTTP(S) links, forms, unique page-local CSS selectors for visible actionable controls, non-secret control metadata and viewport dimensions. Password inputs, hidden controls and control values are not exported.

The worker canonicalizes the observation, computes `semanticDigest`, and incorporates that digest into the document digest. `BrowserProfileHost` rechecks both the digest and the caller's observation budget before publishing the observation.

Each admitted observation advances page generation and stores an actionable-surface digest over links, controls and forms. Immediately before worker admission the same fixed semantic projection is reevaluated; page generation, document digest, navigation epoch and actionable-surface digest must still match. Click/type/focus must name a selector from that exact revalidated visible control surface; disabled controls fail closed and generic type cannot target password/non-text-entry controls. The fixed execution script repeats visibility/disabled/password checks immediately before mutation. Every crossed effect invalidates both worker and Browser-host copies of the prior observation, so a later new effect requires a fresh observation. Because the current subprocess worker owns one WebView, it advertises a one-outstanding-effect ceiling until the prior identity becomes terminal.

## 7. Private worker protocol and response binding

`hepta.browser.worker-frame.v1` uses a four-byte big-endian length prefix followed by <=1 MiB canonical JSON. Every frame binds protocol version, session, generation, monotonic sequence, request identity and canonical payload digest.

For dispatch, the worker first emits a dedicated `dispatch_boundary` frame only after worker-side snapshot/action-surface revalidation and operation reservation. Ordinary responses carry `requestKind` equal to the original request kind and `requestPayloadDigest` equal to the original request payload digest. A bound parent-side `dispatch_rejected` is emitted only for a worker-confirmed no-dispatch rejection. The Browser client rejects and kills/fails the channel on cross-session/generation frames, sequence drift, unregistered frame kinds, unknown request identity or request/response binding drift.

Worker stderr is always drained so a full pipe cannot deadlock the process. Stderr is deliberately not retained in Browser journals/receipts because page and worker logs may contain sensitive data.

## 8. Linux filesystem/network isolation

`LinuxBubblewrapLauncher` exposes a **source launch contract**. Its posture fields describe the intended command construction; they are not treated as an independent observation that an arbitrary target kernel enforced namespaces or filesystem denial.

The launcher starts from an empty tmpfs root and does not bind host `/` or `/usr` wholesale. The allowlist is restricted to the worker's runtime closure and rendering data: runtime libraries, fonts/fontconfig data, loader configuration, public CA certificates / OpenSSL configuration (never the whole host `/etc/ssl` tree), fontconfig cache, private proc/dev/tmp/run/home/root views, one private writable profile and one exact verified worker artifact. General `/usr/bin`, `/usr/local`, `/var/lib`, `/etc/ssl/private`, service roots and ambient user homes are absent.

The launcher separately binds the exact host `prlimit` executable by SHA-256 and applies worker-scoped kernel ceilings before Bubblewrap exec: 8 GiB address space, 300 CPU seconds, 4096 open files and 256 processes by default. Agentd passes both the selected prlimit digest and every numeric ceiling to Browser.

`scripts/linux-sandbox-probe.js` compiles a tiny host-side C probe and executes it through the same production launcher. Inside the sandbox it requires host-secret invisibility, absence of `/usr/bin/sh` and `/usr/bin/python3`, denied direct external IPv4 connect, writable/fsynced private profile state, exact RLIMIT_AS/RLIMIT_CPU/RLIMIT_NOFILE/RLIMIT_NPROC values, and observed `--die-with-parent` cleanup of Bubblewrap plus every reported sandbox descendant after a helper parent exits. Only that execution receipt on an exact host is enforcement evidence.

## 9. Resource and backpressure policy

Profile mutations use a bounded single-writer queue. By default one Browser service admits at most one active profile/worker process; compatible injected drivers may raise that constructor ceiling only up to 64. No more than 64 operations may be queued for one serialization key; overload fails with `BrowserBackpressureError` rather than allowing unbounded promise growth.

Independent hard bounds cover origins, admitted grants, nonterminal operations, terminal in-memory replay cache, action fields, semantic observation bytes, protocol frame bytes, journal bytes and driver/authority call deadlines. Linux launch also carries exact RLIMIT_AS/RLIMIT_CPU/RLIMIT_NOFILE/RLIMIT_NPROC ceilings; these are source defaults until the real probe observes them on the selected target. The current worker is one-WebView/one-profile-generation; the <=16-tab pilot target remains a future measured capability, not a current claim.

## 10. Reproducible worker artifact and composition gates

`.github/workflows/hepta-browser-servo-worker-dev.yml` runs on exact Browser/Servo candidate changes and requires pinned Rust/toolchain and Servo prerequisites, exact current Servo pin, rejection of `webdriver_server`, current-pin `cargo check --locked` plus worker unit tests, complete Browser Node tests, real Bubblewrap isolation probe, two independent release builds with byte equality, dynamic library closure, real worker start/stop, worker SHA-256, deterministic SPDX 2.3 SBOM and a build receipt.

`.github/workflows/hepta-browser-agentd-composition.yml` binds the exact Browser+Agentd source and runs full Browser tests, real `FinalUseAuthority` handoff tests, named caller compilation and Clippy.

A generated `Cargo.lock` is a candidate until reviewed/committed. A successful source workflow is not target-host or operator acceptance.

## 11. Target qualification and capability gaps

`.github/workflows/hepta-browser-servo-deployment-qualification.yml` remains manual and main-only. It executes only the workflow-dispatch `github.sha` on `refs/heads/main`, verifies the referenced successful worker-build run came from the expected workflow on that exact main SHA, requires `cargoLockCommitted=true`, rehashes Cargo.lock/worker/SPDX/source tree, records kernel/Bubblewrap identity, reruns sandbox/worker checks and emits target execution evidence without self-issuing operator acceptance, promotion or release.

Still separately required where applicable: reviewed exact `Cargo.lock` and terminal-success reproducible worker artifact/SBOM receipt; independent Linux no-listener/no-egress/descendant/profile isolation evidence; macOS/Windows equivalent isolation if targeted; functional credential-reference broker if credential use is enabled; real upload/download terminal observers if enabled; real remote business terminal reconciliation; target resource/soak measurements; trusted long-running authority/revocation feed for default daemon activation; and independent operator acceptance/promotion/release.

## 12. Claim boundary

This candidate can establish repository-owned Browser correctness, current-pin worker source, semantic observation source, real final-use handoff source, named Agentd caller source, strict private protocols, durable recovery and Linux sandbox/probe source. It cannot self-certify a reproducibly qualified artifact, deployed OS enforcement, functional secret delivery, remote business terminality, independent acceptance, production activation, selection, promotion or release.

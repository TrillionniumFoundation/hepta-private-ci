# browser.servo isolated worker implementation contract

**Status:** hardened Browser owner boundary + current-pin Servo worker source + private parent handoff implemented; artifact/deployment evidence remains gated
**Module:** `browser.servo`
**Current upstream pin:** `servo/servo@84bcc9ac701874fa9819e5cdee06356b961d736c`
**Canonical pin source:** `third_party/servo-patches/MANIFEST.json`

This is the current implementation-level Browser/Servo contract. Historical WEB-C1 design material remains reference-only when it names an older Servo commit. No source, CI file or author statement is deployment/release evidence.

## 1. Trust and process boundary

One admitted browser profile generation owns one isolated Servo worker. The Browser owner holds profile/page/operation state, the durable effect journal, the verified worker artifact and the private worker protocol. The worker has no public WebDriver/CDP/TCP/HTTP control listener and no raw caller-script surface.

The Browser owner also exposes a **parent-only inherited stdio service** for the Agentd owner:

- `src/agentd-protocol.js` — bounded canonical parent protocol;
- `src/agentd-service.js` — request dispatch + final-use challenge/dispatch-boundary handshake;
- `src/agentd-service-main.js` — Linux service source entry; deployment uses the standalone `.mjs` artifact from `scripts/build-service.mjs`.
- `src/replay-evidence.js` — owner-created historical observation proof, with no new authority.

There is still no Browser UDS/TCP discovery endpoint. Parent death closes the Browser service/worker ownership chain.

## 2. Implemented source surfaces

| Surface                                | Source                                                               | State                                                         |
| -------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------- |
| bounded typed actions                  | `src/action.js`                                                      | implemented                                                   |
| proposal -> effect bridge              | `src/bridge.js`                                                      | implemented                                                   |
| serialized profile/effect host         | `src/runtime-host.js`                                                | implemented                                                   |
| stable owner facade                    | `src/runtime.js`                                                     | implemented                                                   |
| durable operation journal              | `src/journal.js`                                                     | implemented                                                   |
| Browser -> Servo private protocol      | `src/worker-protocol.js`                                             | implemented                                                   |
| artifact-bound subprocess driver       | `src/worker-driver.js`                                               | implemented                                                   |
| Agentd -> Browser private protocol     | `src/agentd-protocol.js`                                             | implemented                                                   |
| Agentd parent service boundary         | `src/agentd-service.js`                                              | implemented                                                   |
| Linux Bubblewrap isolation             | `src/worker-driver.js`                                               | implemented in source; exact-host evidence required           |
| current-pin Hepta Servo worker         | `servo-worker/`                                                      | implemented in source; reproducible artifact receipt required |
| build/repro/SBOM evidence gate         | `.github/workflows/hepta-browser-servo-worker-dev.yml`               | implemented gate                                              |
| trusted Linux deployment evidence gate | `.github/workflows/hepta-browser-servo-deployment-qualification.yml` | implemented main-only gate                                    |
| macOS / Windows equivalent launchers   | none                                                                 | not implemented                                               |
| functional credential secret broker    | none                                                                 | not connected; action fails closed                            |

## 3. Effect correctness and local-dispatch linearization

For a new effect the host:

1. validates profile/page/document generation, typed action, destination, payload digest, operation identity, grant, epoch and deadline;
2. reserves the operation identity before any external dispatch;
3. enters final-use authority;
4. fsyncs the durable dispatch identity;
5. writes exactly one command to the private Servo worker pipe;
6. ends the final-use fence at the successful **local worker-pipe write boundary**;
7. records the result as terminal or `indeterminate` and reconciles separately.

`SubprocessBrowserDriver.dispatch()` deliberately does **not** wait for page execution or a long `wait` action before returning the local-dispatch observation. A late worker response is drained safely; remote effect terminality is obtained through `reconcile()`.

This prevents duplicate concurrent dispatch, retry-after-unknown dispatch and a revocation mutex being held across arbitrary browser/page execution. Expired/revoked authority prevents a new effect but does not remove the right to observe/reconcile a previously dispatched identity.

Cancelled authority verification rejects a late consumer, and dispatch uses the minimum action/profile/grant deadline. Live and persisted recovery share the profile serialization lock. Immutable historical semantics and terminal receipts survive replay/cache eviction; each admitted effect consumes its page snapshot before another effect can be proposed against it.

The journal enforces terminal monotonicity, immutable scalar snapshots, non-zero semantic/result digests, strict UTF-8 and complete newline-terminated replay. Same-path instances share a serialization tail, and all journal accesses take an atomic `<journal>.writer-lock`. Uncertain durability or a crashed owner leaves the lock in place. Recovery requires confirming that the prior writer stopped, reviewing/reconciling the durable prefix and unresolved effects, syncing the reviewed state, then explicitly clearing the lock. No time-based lock stealing or redispatch is permitted. Reliable local-file metadata (`dev`, `ino`, `size`, `mtimeNs`, `ctimeNs`) guards the replay cache; external changes force full replay and identical retries append no bytes. Once this owner has loaded history, its admitted-prefix anchor rejects live deletion, truncation, rollback or rewriting. Complete erasure before its first admitted load still requires an external trusted history anchor.

Malformed worker responses, UTF-8 errors, EOF and pipe failures close the channel and reject pending calls. Concurrent startup fails without losing the live session. Pending requests and abandoned responses are each bounded at 1024; direct driver callers must pass a bounded `AbortSignal`.

## 4. Parent final-use handshake

The kernel `VerifiedUseToken` is intentionally non-serializable. The Browser service therefore never accepts a long-lived JSON token as authority.

For `navigate_or_act`:

1. Agentd sends a normal Browser request over inherited stdio.
2. Browser performs all owner-local admission and emits `authority_challenge` containing the exact request digest and authority epoch.
3. The trusted Agentd caller must validate the challenge against its `FinalUseBinding` and independently signed grant.
4. Only while Agentd holds live final-use authority does it send `authority_enter`.
5. Browser binds the returned witness, fsyncs durable intent and crosses the local Servo-worker pipe boundary.
6. Browser emits `dispatch_boundary` immediately after that boundary.
7. Agentd can release the live revocation fence before browser/page execution continues.
8. Browser sends the ordinary response separately; remote terminality remains a later reconciliation claim.

`test/agentd-service.test.js` exercises challenge-before-dispatch ordering and fail-closed witness drift. The cross-owner Rust caller is present in `codex-rs/hepta-agentd/src/browser_servo.rs`, with `FinalUseAuthority` handoff tests and the named `hepta-agentd-browser` executable. Historical stacked PR #611 is provenance, not the current composition or qualification status. A terminal-success exact-source test is required before claiming the mutex proof passed on a candidate.

The parent service limits queued input to 64 frames and 4 MiB, strictly decodes UTF-8, cancels expired authority reads and fences stream/protocol errors. The native child transport has bounded read/write queues and deadlines, and shutdown does not wait indefinitely for a descendant-retained pipe. A partial or invalid exchange permanently poisons the native port so it cannot resume on a desynchronized frame stream. Parent EOF aborts the active authority context; the actual driver-entry path rechecks that context and the final deadline after awaited journal persistence.

Private parent v1 canonical JSON uses strict UTF-8 byte-lexical key order and finite mathematical integers within ±(2^53−1), normalized to integer spelling. This package-private format is not RFC JCS. An exact historical effect may respond before a fresh challenge only with validated `{ok,result,replay}` observation evidence binding profile/principal/generation/operation and the original request/semantic digests. Its three authority flags remain false. Caller and service must deploy matching private v1 semantics; replay cannot reauthorize or redispatch.

## 5. Typed action boundary

Registered actions are bounded forms of:

- `navigate { url, policyDigest, expectedRevision }`;
- `click { selector }`;
- `type { selector, text }`;
- `credential { selector, credentialRef }`;
- `upload { selector, fileRef, fileDigest, maxBytes }`;
- `focus { selector }`;
- `scroll { deltaX, deltaY }`;
- `wait { condition, timeoutMs }`;
- `download { url, maxBytes }`.

Credential/upload actions carry references, not host paths or raw secret bytes. The current Servo worker rejects credential/upload/download as `capability_not_connected`; this is intentional fail-closed behavior until each dedicated broker/terminal observer is qualified.

## 6. Linux filesystem/network isolation

`LinuxBubblewrapLauncher` starts from an **empty tmpfs root**. It does not bind the host root and does not expose `/usr` as a whole. The current runtime allowlist is limited to the dynamically linked runtime closure and rendering data needed by the worker:

- `/usr/lib`, optional `/usr/lib64`;
- font/fontconfig data under `/usr/share`;
- `/etc/ld.so.cache`, fonts and TLS configuration;
- `/var/cache/fontconfig` only;
- private `/proc`, `/dev`, `/tmp`, `/run`, `/home` and `/root` views;
- one writable Browser profile bind;
- one read-only verified worker artifact.

General `/usr/bin`, `/usr/local`, `/var/lib`, service roots, user homes and arbitrary host mounts are absent. The environment is cleared, `--unshare-all` is used without `--share-net`, a new session is created and parent-death cleanup is required. The namespace denies direct external network access even to origins in `allowedOrigins`; the origin list narrows admissible actions and does not open egress. A functioning network broker must separately bind each request and redirect/subresource to authority before web navigation can be activated.

`scripts/linux-sandbox-probe.js` compiles a tiny host-side C ELF and runs that exact probe through the production launcher. Inside the sandbox it requires:

- a host-only `/var/tmp` secret is invisible;
- `/usr/bin/sh` and `/usr/bin/python3` are invisible;
- direct external IPv4 connect cannot succeed;
- the private profile is writable and fsynced.

A successful probe is evidence only for the exact host/kernel/Bubblewrap tuple that executed it.

## 7. Current-pin Servo worker

`servo-worker/` contains an out-of-tree Hepta-owned worker bound to the repository's exact Servo pin with `default-features = false` plus the selected `background_hang_monitor` and `bundled` features. Its source creates one Servo, one software rendering context and one WebView, pumps the event/render loop, denies unregistered navigation origins and permission requests, and accepts only the private framed protocol over stdin/stdout. The embedding API compatibility and selected feature closure require a successful current-pin build. Navigation-origin filtering does not constitute a complete request/subresource network policy.

Caller-provided arbitrary JavaScript is not a Browser action. Worker-owned fixed templates may use Servo's embedding API for bounded click/type/focus/scroll operations. Navigation uses `WebView::load`.

Worker source now binds page/document identity and navigation-result ownership, reserves the operation before executing an effect and caps stored operation identities at 4096 and queued host events at 16. The second round also tightens current-URL/load-completion and stale document callback guards; 13 pure Rust state tests pass. Atomic renderer-pipeline admission and execution-time deadline enforcement are still adapter work. These state tests do not compile Servo; current-page completion cannot stand in for evidence about a different navigation request.

## 8. Reproducible worker artifact gate

`.github/workflows/hepta-browser-servo-worker-dev.yml` requires an exact source SHA and:

- Rust 1.88.0 plus explicit Servo prerequisites;
- Node 24 with locked esbuild 0.28.1/acorn 8.15.0 dependencies installed using `npm ci --prefix apps/hepta-browser --ignore-scripts`;
- two independent standalone service `.mjs` builds with identical bundle and receipt bytes;
- exact current Servo repository/pin consistency across canonical patch manifest, topology, worker dependency and resolved metadata;
- structured Cargo resolved-feature admission, including required/forbidden Servo features and rejection of `webdriver_server`;
- `cargo check --locked` and all Browser Node tests;
- the real Bubblewrap secret/egress probe;
- two independent release builds with the same source date and remapped source path;
- byte-for-byte equality of the two worker binaries;
- dynamic-library closure inspection;
- real worker start/stop through Bubblewrap and the private protocol;
- worker SHA-256, deterministic SPDX-2.3 dependency SBOM and build receipt;
- separate `serviceSha256` / `serviceReceiptSha256`, source-input/recipe/npm-lock bindings and `reproducibleServiceBuilds` evidence.

The service recipe admits at most 64 source files, 1 MiB per file, a 2 MiB total source closure and an 8 MiB bundle. It emits one `.mjs` without a source map or package-metadata dependency. AST checks cover reviewed static imports and recognized loader escapes; they do not sandbox arbitrary reflective JavaScript.

A generated `Cargo.lock` is only a candidate until its exact bytes are reviewed and committed. Until a terminal-success exact-head run exists, the worker artifact is **not qualified**. The start/stop smoke exercises boot and the private protocol only; it does not prove navigation success, DOM action correctness, cross-profile isolation, terminal reconciliation, resource bounds or absence of all listeners. These workflow definitions remain opt-in and their presence is not proof that aggregate blocking CI invoked them.

Ordinary affected source changes now select the Browser Node regression job in `blocking-ci.yml`'s required fan-in. That fast source check leaves the native Servo artifact/target gate opt-in. The current SPDX generator emits a minimal dependency inventory with unasserted license/source fields; its deterministic hash identifies that artifact and does not certify complete supply-chain compliance.

## 9. Credential isolation versus credential use

Ambient host credential-store visibility is denied by the Linux filesystem allowlist. That closes the browser process's default host-filesystem credential exposure path.

Functional credential use is a separate capability and remains disconnected. The intended implementation reuses the existing trusted `secrets.heptabao` / `FinalUseAuthority` model: resolve `credentialRef` only inside live final-use authority, transfer only the minimum secret bytes over a dedicated private inherited side channel, never place raw secret bytes in Browser JSON, journals, logs or receipts, and zeroize after use. Until that broker exists, credential actions remain fail-closed.

## 10. Production caller composition

The Browser-side half of the module port is implemented by the parent-only service above. The Agentd-owned concrete caller is also present in the current source tree: `BrowserServoPort` / `ChildBrowserTransport` in `codex-rs/hepta-agentd/src/browser_servo.rs` and the named `hepta-agentd-browser` executable. That binary performs one module-port call in a fresh service process. It does not maintain an open/observe/act session across invocations and is not a composed long-running daemon. The current implementation map keeps product activation claims false while recording this source route.

That caller must keep the real kernel revocation mutex only through `authority_enter -> Browser durable intent -> local worker pipe write -> dispatch_boundary`. It must not wait for remote page execution while holding the mutex, and it must not substitute a serialized prior verification receipt for the live authority.

`service_path` selects a fresh standalone `.mjs` built by the pinned recipe, and `service_sha256` binds its complete JavaScript bytes. New Linux Rust snapshot/config source copies and hashes one opened non-symlink, nonblocking regular file into a private owner snapshot before launching it; the transport retains that snapshot through child lifetime and cleanup. The original mutable service path is not executed. This round's isolated actual-source harness passed its offline test build, 27 default tests (one ignored), the separately invoked actual Rust-port-to-Node-owner fixture and scoped Rust 1.95.0 Clippy. It uses the actual contracts path, with every dependency name/version/source matched to the repository `Cargo.lock`. The fixture proves signed first dispatch, revocation, same-request historical replay and changed-deadline rejection with one authority entry and one dispatch. Full Agentd all-target checks and real Servo/host qualification remain separate gates.

The worker artifact reader enforces actual byte limits and stages the verified executable in a separate private artifact directory outside the writable profile bind, removing its prior writable alias. Node, Bubblewrap, runtime libraries and OS behavior remain trusted installation dependencies outside the service digest. Exact reviewed installation and runtime qualification are still required.

## 11. Deployment qualification

`.github/workflows/hepta-browser-servo-deployment-qualification.yml` defines a **main-only** trusted Linux target gate. Its reusable entry inherits its caller's event/ref and therefore preserves manual `workflow_dispatch` and main-branch admission; no automatic trigger or extra permission is needed. It requires exact source SHA/tree, an exact successful worker build run and reviewed worker SHA-256. The evidence verifier binds canonical Servo identity, actual worker/lock/SBOM digests, the smoke worker digest and the build lock to the checked-out committed source lock. It also verifies the service bundle/receipt and independently rebuilds the service from the checked-out pinned recipe, comparing the bundle digest and complete input receipt. This rejects omitted-import manifests and self-consistent substituted bundles; manifest hashes alone are not compiler-semantics evidence. Generated lock candidates are ineligible for target qualification. It observes kernel, Node and Bubblewrap identities, reruns the filesystem/IPv4-egress probe and worker start/stop, and emits a target execution receipt only after those steps pass. The service artifact is reproduced, but `serviceExecutionQualified=false`: this workflow does not start or qualify the complete Agentd/Node/Servo service path. Observed Node/Bubblewrap executable hashes are not installation qualification. This is a boot/isolation probe boundary, not complete browser deployment qualification.

That receipt deliberately leaves `operatorAcceptance=false`, `promotion=false` and `releaseQualified=false`. Independent operator/release authority is external and cannot be self-issued by this module.

## 12. Remaining gates

Still required before production/release claims:

- terminal-success exact-SHA reproducible worker build and reviewed committed `Cargo.lock`;
- target-host Linux execution evidence;
- cross-profile cookie/cache/storage isolation evidence;
- macOS/Windows equivalent isolation if those platforms are in the product target set;
- functional credential-reference broker if credential use is enabled;
- exact-source Agentd caller qualification, persistent product-session composition and a trusted live authority/revocation owner for long-running activation;
- complete Agentd all-target native checks and real product composition; the 27 default isolated source tests and separately invoked Rust-to-Node fixture do not replace that gate;
- atomic renderer-pipeline document admission and execution-time deadline enforcement;
- reviewed trusted Node/Bubblewrap/OS/runtime installation and an external journal-history anchor when rollback across first admission must be detected;
- separately authorized network delivery, including redirects, subresources, script-initiated requests and DNS policy, when web access is enabled;
- real navigation/download/business terminal observation and reconciliation;
- target resource measurements;
- independent operator acceptance, promotion and release.

Source implementation, CI configuration and draft PRs are not substitutes for those receipts.

The module audit in [AUDIT.md](AUDIT.md) distinguishes source findings, local verification and external evidence still required. `SERVO_CURRENT_PIN_TOPOLOGY.json` describes source decisions; historical PR/branch references in it are provenance rather than live status.

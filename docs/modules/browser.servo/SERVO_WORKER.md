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
- `src/agentd-service-main.js` — Linux private service executable.

There is still no Browser UDS/TCP discovery endpoint. Parent death closes the Browser service/worker ownership chain.

## 2. Implemented source surfaces

| Surface | Source | State |
| --- | --- | --- |
| bounded typed actions | `src/action.js` | implemented |
| proposal -> effect bridge | `src/bridge.js` | implemented |
| serialized profile/effect host | `src/runtime-host.js` | implemented |
| stable owner facade | `src/runtime.js` | implemented |
| durable operation journal | `src/journal.js` | implemented |
| Browser -> Servo private protocol | `src/worker-protocol.js` | implemented |
| artifact-bound subprocess driver | `src/worker-driver.js` | implemented |
| Agentd -> Browser private protocol | `src/agentd-protocol.js` | implemented |
| Agentd parent service boundary | `src/agentd-service.js` | implemented |
| Linux Bubblewrap isolation | `src/worker-driver.js` | implemented in source; exact-host evidence required |
| current-pin Hepta Servo worker | `servo-worker/` | implemented in source; reproducible artifact receipt required |
| build/repro/SBOM evidence gate | `.github/workflows/hepta-browser-servo-worker-dev.yml` | implemented gate |
| trusted Linux deployment evidence gate | `.github/workflows/hepta-browser-servo-deployment-qualification.yml` | implemented main-only gate |
| macOS / Windows equivalent launchers | none | not implemented |
| functional credential secret broker | none | not connected; action fails closed |

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

`test/agentd-service.test.js` proves challenge-before-dispatch ordering and fail-closed witness drift. The cross-owner Rust caller and real `FinalUseAuthority` mutex proof are developed separately in stacked PR #611.

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

General `/usr/bin`, `/usr/local`, `/var/lib`, service roots, user homes and arbitrary host mounts are absent. The environment is cleared, `--unshare-all` is used without `--share-net`, a new session is created and parent-death cleanup is required.

`scripts/linux-sandbox-probe.js` compiles a tiny host-side C ELF and runs that exact probe through the production launcher. Inside the sandbox it requires:

- a host-only `/var/tmp` secret is invisible;
- `/usr/bin/sh` and `/usr/bin/python3` are invisible;
- direct external IPv4 connect cannot succeed;
- the private profile is writable and fsynced.

A successful probe is evidence only for the exact host/kernel/Bubblewrap tuple that executed it.

## 7. Current-pin Servo worker

`servo-worker/` is an out-of-tree Hepta-owned worker bound to the repository's exact Servo pin with `default-features = false` plus the selected `background_hang_monitor` and `bundled` features. It owns one Servo, one software rendering context and one WebView, denies unregistered origins and permission requests, and accepts only the private framed protocol over stdin/stdout.

Caller-provided arbitrary JavaScript is not a Browser action. Worker-owned fixed templates may use Servo's embedding API for bounded click/type/focus/scroll operations. Navigation uses `WebView::load`.

## 8. Reproducible worker artifact gate

`.github/workflows/hepta-browser-servo-worker-dev.yml` requires an exact source SHA and:

- Rust 1.88.0 plus explicit Servo prerequisites;
- exact current Servo pin in the dependency lock;
- Cargo feature graph capture and rejection of `webdriver_server`;
- `cargo check --locked` and all Browser Node tests;
- the real Bubblewrap secret/egress probe;
- two independent release builds with the same source date and remapped source path;
- byte-for-byte equality of the two worker binaries;
- dynamic-library closure inspection;
- real worker start/stop through Bubblewrap and the private protocol;
- worker SHA-256, deterministic SPDX-2.3 dependency SBOM and build receipt.

A generated `Cargo.lock` is only a candidate until its exact bytes are reviewed and committed. Until a terminal-success exact-head run exists, the worker artifact is **not qualified**.

## 9. Credential isolation versus credential use

Ambient host credential-store visibility is denied by the Linux filesystem allowlist. That closes the browser process's default host-filesystem credential exposure path.

Functional credential use is a separate capability and remains disconnected. The intended implementation reuses the existing trusted `secrets.heptabao` / `FinalUseAuthority` model: resolve `credentialRef` only inside live final-use authority, transfer only the minimum secret bytes over a dedicated private inherited side channel, never place raw secret bytes in Browser JSON, journals, logs or receipts, and zeroize after use. Until that broker exists, credential actions remain fail-closed.

## 10. Production caller composition

The Browser-side half of the production module port is implemented by the parent-only service above. The Agentd-owned concrete caller is intentionally separated into stacked PR #611 because it changes another owner root.

That caller must keep the real kernel revocation mutex only through `authority_enter -> Browser durable intent -> local worker pipe write -> dispatch_boundary`. It must not wait for remote page execution while holding the mutex, and it must not substitute a serialized prior verification receipt for the live authority.

## 11. Deployment qualification

`.github/workflows/hepta-browser-servo-deployment-qualification.yml` is a manual **main-only** trusted Linux target gate. It requires exact source SHA, exact worker build run and reviewed worker SHA-256; revalidates artifact identity; records kernel/Bubblewrap identities; reruns real secret/egress isolation and worker start/stop; and emits a target execution receipt.

That receipt deliberately leaves `operatorAcceptance=false`, `promotion=false` and `releaseQualified=false`. Independent operator/release authority is external and cannot be self-issued by this module.

## 12. Remaining gates

Still required before production/release claims:

- terminal-success exact-SHA reproducible worker build and reviewed committed `Cargo.lock`;
- target-host Linux execution evidence;
- cross-profile cookie/cache/storage isolation evidence;
- macOS/Windows equivalent isolation if those platforms are in the product target set;
- functional credential-reference broker if credential use is enabled;
- stacked Agentd caller qualification and a trusted live authority/revocation owner for long-running activation;
- real navigation/download/business terminal observation and reconciliation;
- target resource measurements;
- independent operator acceptance, promotion and release.

Source implementation, CI configuration and draft PRs are not substitutes for those receipts.

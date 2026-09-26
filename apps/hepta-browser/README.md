# Hepta browser

This root contains the repository-owned `browser.servo` boundary. The current candidate contains the authority-free proposal layer, the durable effect owner, a current-pin Servo worker source, the private Browser/Servo protocol and the private Agentd/Browser final-use handoff. None of those source facts are by themselves deployment, operator-acceptance or release evidence.

## Source surfaces

- `src/browser.js` — authority-free navigation and page-projection helpers.
- `src/action.js` — closed bounded typed browser effects.
- `src/bridge.js` — provenance-preserving proposal -> effect bridge.
- `src/runtime.js` / `src/runtime-host.js` — serialized profile owner, live final-use fence, durable no-redispatch recovery and semantic page observations.
- `src/runtime-boundary.js` — bounded per-profile serialization queue plus safe abort settlement; an effect-capable driver timeout is not reported until the abort/containment path itself has settled.
- `src/journal.js` — strict private durable operation journal with compaction and clean-generation retirement. Production effect ownership requires persistent durability; the in-memory journal is an explicit test-only opt-in. Durable operation history fences profile-generation resurrection after a crash.
- `src/worker-protocol.js` — canonical bounded private Browser/Servo frames.
- `src/worker-driver.js` — exact-artifact subprocess driver, principal-bound fresh profile roots, worker-originated admission boundary, response-request binding, stderr drain and Linux Bubblewrap source contract. The selected Bubblewrap and `prlimit` executables are both SHA-256-bound; the verified worker copy lives outside the writable profile bind; TLS exposure is limited to public CA/configuration data rather than the whole `/etc/ssl` tree; and the worker inherits explicit address-space, CPU-time, open-file and process ceilings before entering the sandbox. A pipe write is not treated as effect admission; timeout/abort before a worker boundary contains the worker unless the worker has explicitly proven a no-dispatch rejection.
- `src/agentd-protocol.js`, `src/agentd-service.js`, `src/agentd-service-main.js` — private Agentd parent handoff.
- `servo-worker/` — Hepta-owned current-pin Servo worker source with one Servo / one WebView and fixed worker-owned semantic/action scripts.

The canonical upstream pin remains `third_party/servo-patches/MANIFEST.json`. A source tree is not a qualified worker binary; the exact-SHA reproducible build/SBOM and target-host gates remain separate.

## Proposal, provenance and final-use authority

`buildNavigationIntent()` is authority-free. `src/bridge.js` preserves the proposal `navigationId` as the effect operation identity and includes the proposal `policyDigest` and `expectedRevision` in the typed `navigate` payload. The final payload digest and request digest therefore bind the exact proposal provenance rather than only the URL.

The Browser service does not accept a reusable serialized `VerifiedUseToken`. The persistent Agentd owner keeps an owner-private `hepta.browser.revocation-feed.v1` file under continuous monotonic refresh and performs a synchronous feed refresh before every effect-capable Browser call. Agentd then receives an exact Browser `authority_challenge` containing only the request digest and authority epoch (never a duplicate typed action or `type.text`), enters real `FinalUseAuthority::with_verified_use`, sends `authority_enter`, and keeps the same live revocation fence used by feed updates through Browser journal fsync, private-pipe queue wait and Servo-worker admission. The worker revalidates page/document/navigation/action-surface state, reserves the operation and emits `dispatch_boundary` immediately before effect execution. A worker-confirmed stale-state rejection is returned as `dispatch_rejected { localDispatchCrossed:false }`; timeout/transport uncertainty without either proof remains indeterminate. Remote page/business completion after admission is reconciled separately.

## Secret and durability boundary

Current effect actions are closed-world: `navigate`, `click`, `type`, `focus`, `scroll`, and `wait`. Credential, upload and download are explicitly **out of scope for this release** and fail at ingress; they are not completion blockers for the current release because no product contract advertises them as admitted capabilities. A future release must add dedicated secret/file brokers, final-use bindings and terminal observers before adding any of them back to the admitted action vocabulary. `type.text` exists only in the live action payload; the durable operation journal does **not** store `typedAction` or raw text. It stores the final payload digest plus immutable effect semantics.

The file operation journal is `hepta.browser.operation-journal.v2`; v2 adds nullable `terminalEvidenceDigest` instead of silently changing the old v1 record shape. It validates every hydrated field, rejects unknown fields, checks canonical checksum envelopes, fsyncs dispatch intent before the effect boundary, compacts atomically before the file ceiling and retires a fully terminal profile generation after clean close. A crash-torn unterminated final append recovers the fully validated prefix while newline-terminated malformed/tampered data remains fail-closed; qualification tests inject crashes around compaction/retirement fsync and rename boundaries. A generation with durable operation history cannot be reopened into a fresh worker; unresolved durable effects from another generation block profile advancement.

Live-worker reconciliation and post-Browser-process-loss reconciliation are separate driver paths: a replacement Servo worker is never treated as evidence of a prior remote business outcome. Product persisted terminalization is enabled only with one closed reconciliation tuple: root + observer identity + Ed25519 verification key + minimum observer generation + minimum observation timestamp + current frontier digest + bounded future-clock skew. A signed `hepta.browser.persisted-effect-observation.v2` receipt must bind the exact operation/request/semantic/outcome identity **and** satisfy that currentness policy. Generation rollback, stale observation time, frontier mismatch and excessive future timestamp all remain indeterminate and never authorize redispatch. The signed evidence hash is persisted as `terminalEvidenceDigest`.

Each worker generation receives a fresh random private profile directory. Its mode-0600 `hepta.browser.profile-owner.v1` ownership manifest lives in the host-private profile root outside the worker's read/write profile bind and binds profile ID, principal ID, generation, Browser manifest digest and profile grant digest; only the digest crosses the session boundary. Stale profile bytes are not silently reopened for another principal.

## Semantic observe -> reason -> act loop

The current-pin worker's `observe` path emits bounded `hepta.browser.semantic-observation.v1` data rather than only URL/digests. It includes title, bounded visible text, HTTP(S) links, forms, unique page-local selectors for visible actionable controls and viewport metadata. Password/hidden controls and control values are excluded. The semantic value is canonical-digest-bound by the worker and rechecked by `BrowserProfileHost` against the caller's observation budget. Click/type/focus must target a selector from that exact revalidated control surface; disabled controls fail closed, generic type cannot target password/non-text-entry controls, and the fixed execution script repeats visibility/disabled/password checks immediately before mutation.

Every admitted semantic observation advances page generation and records an actionable-surface digest over links, controls and forms. Immediately before admission the worker reruns the fixed projection and requires page generation, document digest, navigation epoch and actionable-surface digest to still match. Every crossed effect invalidates both worker and Browser-host copies of the prior observation, so the next new effect requires a fresh observe. The current one-WebView subprocess driver additionally permits only one outstanding effect until the prior identity becomes terminal, preventing later page mutation from corrupting reconciliation of an older unknown effect. Linux worker launch defaults to an 8 GiB address-space ceiling, 300 CPU seconds, 4096 open files and 256 processes; the real sandbox probe reads those RLIMIT values inside the sandbox rather than treating launcher arguments as enforcement evidence.

## Worker and sandbox boundary

The private worker protocol uses a four-byte length prefix plus <=1 MiB canonical JSON. Frames bind protocol version, session, generation, monotonic sequence, request identity and payload digest. A dispatch receives a dedicated worker-originated `dispatch_boundary` only after worker-side stale-state validation and operation reservation; ordinary responses additionally echo the original request kind, request payload digest and original request sequence, with exact-key success/error payloads. Binding drift or unknown response fields terminate/fail the private channel.

Worker stderr is always drained but is not copied into receipts or journals, avoiding both pipe deadlock and accidental persistence of page/worker secrets.

`LinuxBubblewrapLauncher` describes a source launch contract: empty tmpfs root, selected read-only runtime libraries/data, cleared environment, hidden ambient homes/service roots, no network sharing, one private writable profile and one exact worker. `scripts/linux-sandbox-probe.js` executes that same launcher to test host-secret invisibility, denied external IPv4 egress, absence of general shell/Python binaries and private-profile durability. Only execution on an exact host proves enforcement.

## Profile grant lifecycle

`expiresAtMs` is a physical **process/network lease**, not merely a check performed on the next Browser RPC. The Browser host passes the absolute expiry into the subprocess driver; the driver arms an independent timer and, at expiry, kills the Servo worker and closes the profile egress broker even when page JavaScript is still running. New Browser admissions also continue to reject the expired profile.

The current early-revocation ceremony for the profile lease is the owner `close_profile` operation. It stops the worker/broker and retires the durable generation after all crossed effects are terminal. There is deliberately no second hidden profile-revocation API. Final-use effect-grant revocation remains the independent Agentd/kernel authority path and is linearized before `dispatch_boundary`.

The real-Servo E2E includes hostile pages that run periodic background `fetch` and schedule delayed top-level navigation. It requires both profile expiry and explicit owner close to stop background network growth and prevent the delayed navigation from crossing the lease boundary.

## Capacity and backpressure

Browser service process/profile admission is bounded globally by a profile-affine worker pool (default 16 active profiles/workers, hard configurable ceiling 64). This is resident capacity rather than parent-RPC parallelism: the current Agentd private Browser port admits one in-flight call at a time. Each current one-WebView subprocess worker permits one outstanding effect. Profile mutations use a bounded serialization queue (64 queued operations per key by default) and fail with `BrowserBackpressureError` on overload. Separate ceilings cover origins, grants, active operations, terminal in-memory replay cache, action fields, semantic observations, frames, journal size and call deadlines.

## Verification

From the repository root:

```sh
node --test apps/hepta-browser/test/*.test.js
node --check apps/hepta-browser/src/*.js
```

Cross-owner Agentd qualification additionally runs the real `FinalUseAuthority` Browser handoff tests, including a real protected-file revocation-feed race, and compiles/lints the named `hepta-agentd-browser` caller. The current-pin worker gate runs `cargo check --locked` plus worker unit tests, the full Browser tests, the real Bubblewrap probe, two release builds, byte equality, dynamic-library closure, real worker smoke, a real worker revocation-boundary race, two-profile cookie/localStorage/HTTP-cache isolation, no-nonloopback-listener inspection, bounded RSS/FD soak, deterministic SPDX SBOM and a checksum-bound build receipt. The trusted main-only target gate accepts only a successful exact-main worker-build run with a reviewed committed `Cargo.lock`, rehashes the lock/worker/SBOM/source tree and reruns the target isolation/capacity oracles before qualification. It also runs `scripts/public-egress-probe.js`, which requires real public DNS resolution, an end-to-end certificate-validating HTTPS tunnel to the granted public origin, and denial of an ungranted public CONNECT target.

For the exact completion boundary see `docs/modules/browser.servo/TECHNICAL.md`, `docs/modules/browser.servo/SERVO_WORKER.md`, `docs/modules/browser.servo/IMPLEMENTATION_MAP.json` and `qualification/module-execution-dossiers/detail/browser.servo.md`.


## Persistent product composition and egress

The product topology is the long-running Agentd process retaining one private
Browser service and a bounded profile-affine Servo worker pool. The existing
Agentd owner-only UDS carries Browser calls, so profile state survives across
separate open/observe/effect/reconcile/close requests; no Browser discovery
listener is added.

Servo has no direct external namespace. Its proxy preferences point at a
loopback relay inside the sandbox, which can reach only a profile-private Unix
socket. The host-side `GrantScopedEgressBroker` resolves every admitted origin
once while establishing the profile network-grant generation, rejects
private/special destinations, and freezes the exact DNS/IP answer set under the
profile grant digest. Every later HTTP request/CONNECT uses only those pinned
addresses, so DNS rebinding cannot retarget the profile. For HTTPS CONNECT to a
DNS host it also requires bounded ClientHello SNI to match the granted host
before any upstream TCP connection. Independently, the Servo delegate pins
top-level navigation to the current effect's exact `destinationOrigin`, so a
second origin may remain profile-allowed for read/subresource policy without
becoming the redirect target of the current effect. Production denies
private/special address ranges. The real worker gate verifies both a granted
local fixture path (test-only private-range override) and denial of an
ungranted subresource origin.

After worker admission the response remains attached as a terminal-settlement
future and Browser records any terminal result durably. A process restart may
terminalize a prior effect only from the configured independent observer's
valid Ed25519 `hepta.browser.persisted-effect-observation.v2` receipt; absence,
wrong observer, signature failure or binding drift remains indeterminate.

The selected upstream Servo qualification candidate is
`servo/servo@b5a1f5e6ec6f8685d40cd389802ced7abe4980f6`, replacing `5cc5bd32d02619acdec5736055515e38c5840ce1` because upstream's
WebView double-borrow hardening changes the `WebView::load()` path used by this
worker. The dependency graph changed with that upstream window, so the existing
committed lock is predecessor evidence only: exact-head worker qualification must
generate the b5a1 candidate lock, that exact lock must be reviewed and committed,
and only then may locked build/E2E/reproducibility evidence qualify the pin.
Promotion requirements are in `docs/modules/browser.servo/SERVO_PIN_AUDIT.md`.


The real qualification path also proves that one profile actually retains its
own cookie and localStorage state and reuses its own HTTP cache entry before
asserting that a second simultaneous profile receives none of A's cookie/storage/cache
state. The same E2E checks forbidden subresources and redirects plus absence of
non-loopback worker listeners, while the broker unit suite binds HTTPS CONNECT
to the exact granted authority and port. A 32-cycle real-worker soak hard-fails
above +512 MiB peak RSS, +256 MiB terminal RSS or +32 FDs. Target-host execution
receipts remain distinct from these source oracles.


## Current product platform scope

The current Browser product service is Linux-only and explicitly rejects non-Linux startup. This is deliberate: Bubblewrap + prlimit is the only implemented product isolation launcher in this candidate. macOS/Windows must not be counted as supported or qualified until equivalent process/filesystem/network/resource isolation adapters and exact-host evidence exist. The 16-profile pool is resident worker capacity; the current parent channel remains one-in-flight and therefore does not claim 16-way RPC concurrency.

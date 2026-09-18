# Hepta browser

This root contains the repository-owned `browser.servo` boundary. The current candidate contains the authority-free proposal layer, the durable effect owner, a current-pin Servo worker source, the private Browser/Servo protocol and the private Agentd/Browser final-use handoff. None of those source facts are by themselves deployment, operator-acceptance or release evidence.

## Source surfaces

- `src/browser.js` — authority-free navigation and page-projection helpers.
- `src/action.js` — closed bounded typed browser effects.
- `src/bridge.js` — provenance-preserving proposal -> effect bridge.
- `src/runtime.js` / `src/runtime-host.js` — serialized profile owner, live final-use fence, durable no-redispatch recovery and semantic page observations.
- `src/runtime-boundary.js` — bounded per-profile serialization queue plus safe abort settlement; an effect-capable driver timeout is not reported until the abort/containment path itself has settled.
- `src/journal.js` — strict private durable operation journal with compaction and clean-generation retirement.
- `src/worker-protocol.js` — canonical bounded private Browser/Servo frames.
- `src/worker-driver.js` — exact-artifact subprocess driver plus a bounded profile→worker pool, principal-bound fresh profile roots, response-request binding, stderr drain and Linux Bubblewrap source contract. Linux launch is wrapped by `prlimit` with explicit address-space, CPU-time, file-descriptor and process ceilings. If an abort races a private pipe write, the affected worker is contained and the request is not reported timed out while the write can still complete in background.
- `src/agentd-protocol.js`, `src/agentd-service.js`, `src/agentd-service-main.js` — private Agentd parent handoff.
- `servo-worker/` — Hepta-owned current-pin Servo worker source with one Servo / one WebView and fixed worker-owned semantic/action scripts.

The canonical upstream pin remains `third_party/servo-patches/MANIFEST.json`. A source tree is not a qualified worker binary; the exact-SHA reproducible build/SBOM and target-host gates remain separate.

## Proposal, provenance and final-use authority

`buildNavigationIntent()` is authority-free. `src/bridge.js` preserves the proposal `navigationId` as the effect operation identity and includes the proposal `policyDigest` and `expectedRevision` in the typed `navigate` payload. The final payload digest and request digest therefore bind the exact proposal provenance rather than only the URL.

The Browser service does not accept a reusable serialized `VerifiedUseToken`. Agentd receives an exact Browser `authority_challenge`, enters real `FinalUseAuthority::with_verified_use`, sends `authority_enter`, and keeps the live revocation fence through Browser journal fsync and the successful local worker-pipe write. Browser then emits `dispatch_boundary`; remote page/business completion is reconciled separately. Browser no longer wraps this non-cancelable fence in an outer Promise timeout that could return failure while a late dispatch continues in background.

## Secret and durability boundary

Typed actions are closed-world: `navigate`, `click`, `type`, `credential`, `upload`, `focus`, `scroll`, `wait`, `download`. Credential/upload actions carry references rather than raw secret bytes or ambient host paths. `type.text` exists only in the live action payload; the durable operation journal does **not** store `typedAction` or raw text. It stores the final payload digest plus immutable effect semantics.

The file journal validates every hydrated field, rejects unknown fields, checks canonical checksum envelopes, fsyncs dispatch intent before the effect boundary, compacts atomically before the file ceiling and retires a fully terminal profile generation after clean close.

The Agentd service uses `PooledSubprocessBrowserDriver`: one worker process per live profile generation, with `HEPTA_BROWSER_MAX_PROFILES` (default 16) bounding the global process pool. Linux process ceilings are configurable with `HEPTA_BROWSER_MAX_ADDRESS_SPACE_BYTES`, `HEPTA_BROWSER_MAX_CPU_SECONDS`, `HEPTA_BROWSER_MAX_OPEN_FILES`, and `HEPTA_BROWSER_MAX_PROCESSES`; defaults are 8 GiB virtual address space, 300 CPU seconds, 4096 FDs and 256 processes/threads per worker launch.

Each worker generation receives a fresh random private profile directory and a mode-0600 `hepta.browser.profile-owner.v1` manifest binding profile ID, principal ID, generation, Browser manifest digest and profile grant digest. Stale profile bytes are not silently reopened for another principal.

## Semantic observe -> reason -> act loop

The current-pin worker's `observe` path emits bounded `hepta.browser.semantic-observation.v1` data rather than only URL/digests. It includes title, bounded visible text, HTTP(S) links, forms, page-local selectors for actionable controls and viewport metadata. Password controls and control values are excluded. The semantic value is canonical-digest-bound by the worker and rechecked by `BrowserProfileHost` against the caller's observation budget.

Every admitted semantic observation advances page generation. An action prepared from an earlier observation therefore fails the host's stale-generation check even when page script changed the DOM without a navigation.

## Worker and sandbox boundary

The private worker protocol uses a four-byte length prefix plus <=1 MiB canonical JSON. Frames bind protocol version, session, generation, monotonic sequence, request identity and payload digest. Responses must additionally echo the original request kind and request payload digest; mismatches terminate/fail the private channel.

Worker stderr is always drained but is not copied into receipts or journals, avoiding both pipe deadlock and accidental persistence of page/worker secrets.

`LinuxBubblewrapLauncher` describes a source launch contract: empty tmpfs root, selected read-only runtime libraries/data, cleared environment, hidden ambient homes/service roots, no network sharing, one private writable profile and one exact worker. `scripts/linux-sandbox-probe.js` executes that same launcher to test host-secret invisibility, denied external IPv4 egress, absence of general shell/Python binaries and private-profile durability. Only execution on an exact host proves enforcement.

## Capacity and backpressure

Profile mutations use a bounded serialization queue (64 queued operations per key by default) and fail with `BrowserBackpressureError` on overload. Separate ceilings cover origins, grants, active operations, terminal in-memory replay cache, action fields, semantic observations, frames, journal size and call deadlines.

## Verification

From the repository root:

```sh
node --test apps/hepta-browser/test/*.test.js
node --check apps/hepta-browser/src/*.js
```

Cross-owner Agentd qualification additionally runs the real `FinalUseAuthority` Browser handoff tests and compiles/lints the named `hepta-agentd-browser` caller. The current-pin worker gate runs `cargo check --locked`, the full Browser tests, the real Bubblewrap probe, two release builds, byte equality, dynamic-library closure, real worker smoke, deterministic SPDX SBOM and a checksum-bound build receipt.

For the exact completion boundary see `docs/modules/browser.servo/TECHNICAL.md`, `docs/modules/browser.servo/SERVO_WORKER.md`, `docs/modules/browser.servo/IMPLEMENTATION_MAP.json` and `qualification/module-execution-dossiers/detail/browser.servo.md`.

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

The Browser service does not accept a reusable serialized `VerifiedUseToken`. Agentd receives an exact Browser `authority_challenge`, enters real `FinalUseAuthority::with_verified_use`, sends `authority_enter`, and keeps the live revocation fence through Browser journal fsync, private-pipe queue wait and Servo-worker admission. The worker revalidates page/document/navigation/action-surface state, reserves the operation and emits `dispatch_boundary` immediately before effect execution. A worker-confirmed stale-state rejection is returned as `dispatch_rejected { localDispatchCrossed:false }`; timeout/transport uncertainty without either proof remains indeterminate. Remote page/business completion after admission is reconciled separately.

## Secret and durability boundary

Typed actions are closed-world: `navigate`, `click`, `type`, `credential`, `upload`, `focus`, `scroll`, `wait`, `download`. Credential/upload actions carry references rather than raw secret bytes or ambient host paths. `type.text` exists only in the live action payload; the durable operation journal does **not** store `typedAction` or raw text. It stores the final payload digest plus immutable effect semantics.

The file journal validates every hydrated field, rejects unknown fields, checks canonical checksum envelopes, fsyncs dispatch intent before the effect boundary, compacts atomically before the file ceiling and retires a fully terminal profile generation after clean close. A generation with durable operation history cannot be reopened into a fresh worker; unresolved durable effects from another generation block profile advancement. Persisted recovery automatically retires the generation once all recovered operations become terminal.

Each worker generation receives a fresh random private profile directory and a mode-0600 `hepta.browser.profile-owner.v1` manifest binding profile ID, principal ID, generation, Browser manifest digest and profile grant digest. Stale profile bytes are not silently reopened for another principal.

## Semantic observe -> reason -> act loop

The current-pin worker's `observe` path emits bounded `hepta.browser.semantic-observation.v1` data rather than only URL/digests. It includes title, bounded visible text, HTTP(S) links, forms, unique page-local selectors for visible actionable controls and viewport metadata. Password/hidden controls and control values are excluded. The semantic value is canonical-digest-bound by the worker and rechecked by `BrowserProfileHost` against the caller's observation budget. Click/type/focus must target a selector from that exact revalidated control surface; disabled controls fail closed, generic type cannot target password/non-text-entry controls, and the fixed execution script repeats visibility/disabled/password checks immediately before mutation.

Every admitted semantic observation advances page generation and records an actionable-surface digest over links, controls and forms. Immediately before admission the worker reruns the fixed projection and requires page generation, document digest, navigation epoch and actionable-surface digest to still match. Every crossed effect invalidates both worker and Browser-host copies of the prior observation, so the next new effect requires a fresh observe. The current one-WebView subprocess driver additionally permits only one outstanding effect until the prior identity becomes terminal, preventing later page mutation from corrupting reconciliation of an older unknown effect. Linux worker launch defaults to an 8 GiB address-space ceiling, 300 CPU seconds, 4096 open files and 256 processes; the real sandbox probe reads those RLIMIT values inside the sandbox rather than treating launcher arguments as enforcement evidence.

## Worker and sandbox boundary

The private worker protocol uses a four-byte length prefix plus <=1 MiB canonical JSON. Frames bind protocol version, session, generation, monotonic sequence, request identity and payload digest. A dispatch receives a dedicated worker-originated `dispatch_boundary` only after worker-side stale-state validation and operation reservation; ordinary responses additionally echo the original request kind and request payload digest. Binding drift terminates/fails the private channel.

Worker stderr is always drained but is not copied into receipts or journals, avoiding both pipe deadlock and accidental persistence of page/worker secrets.

`LinuxBubblewrapLauncher` describes a source launch contract: empty tmpfs root, selected read-only runtime libraries/data, cleared environment, hidden ambient homes/service roots, no network sharing, one private writable profile and one exact worker. `scripts/linux-sandbox-probe.js` executes that same launcher to test host-secret invisibility, denied external IPv4 egress, absence of general shell/Python binaries and private-profile durability. Only execution on an exact host proves enforcement.

## Capacity and backpressure

Browser service process/profile admission is also bounded globally (default 1 active profile/worker, configurable only up to 64 for compatible injected drivers). Profile mutations use a bounded serialization queue (64 queued operations per key by default) and fail with `BrowserBackpressureError` on overload. Separate ceilings cover origins, grants, active operations, terminal in-memory replay cache, action fields, semantic observations, frames, journal size and call deadlines.

## Verification

From the repository root:

```sh
node --test apps/hepta-browser/test/*.test.js
node --check apps/hepta-browser/src/*.js
```

Cross-owner Agentd qualification additionally runs the real `FinalUseAuthority` Browser handoff tests and compiles/lints the named `hepta-agentd-browser` caller. The current-pin worker gate runs `cargo check --locked` plus worker unit tests, the full Browser tests, the real Bubblewrap probe, two release builds, byte equality, dynamic-library closure, real worker smoke, deterministic SPDX SBOM and a checksum-bound build receipt. The trusted main-only target gate accepts only a successful exact-main worker-build run with a reviewed committed `Cargo.lock`, and rehashes the lock, worker, SBOM and source tree before target qualification.

For the exact completion boundary see `docs/modules/browser.servo/TECHNICAL.md`, `docs/modules/browser.servo/SERVO_WORKER.md`, `docs/modules/browser.servo/IMPLEMENTATION_MAP.json` and `qualification/module-execution-dossiers/detail/browser.servo.md`.

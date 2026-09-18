# browser.servo: implementation design

Parent: `docs/modules/browser.servo/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable Browser effect owner, current-pin Servo worker source, bounded semantic observation, private Browser/Servo protocol, Linux sandbox/probe source and real Agentd final-use handoff are implemented in this candidate; exact artifact/target qualification and independent acceptance remain open. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `apps/hepta-browser`, `third_party/servo-patches`.
Package: `BROWSER-WEB-C1`.
Current Servo pin: `84bcc9ac701874fa9819e5cdee06356b961d736c`.

Cross-owner Agentd composition is source-present in `codex-rs/hepta-agentd` and remains owned/reviewed by `runtime.agentd`. Browser ownership is not widened by the private caller.

## 2. Public operations and contract details

The canonical Browser design operations remain:

`open_profile(profile_id, grant, browser_manifest) -> BrowserSession`; `observe_page(session, page_generation, observation_budget) -> PageObservation`; `navigate_or_act(session, typed_action, final_payload, grant) -> BrowserEffectObservation`.

Stable owner entrypoints remain `openProfile`, `observePage` and `navigateOrAct` in `apps/hepta-browser/src/runtime.js`. Additional owner/recovery methods are `admitEffectGrant`, `reconcileOperation`, `reconcilePersistedOperation` and `closeProfile`.

Navigation proposal provenance is part of the final effect semantics: `navigationId` becomes operation identity; `policyDigest` and `expectedRevision` are fields of the typed navigate action and therefore participate in the payload/request digest. The bridge never mints authority.

## 3. State, profile ownership and transaction design

`browser_profile_state` owns profile/principal/process/page generations, allowed origins, admitted grants and browser-effect operation identities.

Each worker generation receives a fresh random private profile directory. Browser stores the mode-0600 `hepta.browser.profile-owner.v1` manifest in the host-private profile root outside the worker's read/write profile bind; it binds profile ID, principal ID, generation, Browser manifest digest and profile grant digest, while only its digest crosses the session boundary. A stale profile directory is never silently reused under another principal.

A new browser effect linearizes as:

1. validate current profile/page/document generation, typed action, provenance, destination, payload digest, grant, epoch and deadline;
2. challenge Agentd with the exact request digest;
3. Agentd enters real `FinalUseAuthority::with_verified_use` and holds the live revocation mutex;
4. Browser binds the current witness and fsyncs an indeterminate dispatch record;
5. Browser performs exactly one local private-worker pipe write;
6. the Servo worker dequeues the request, revalidates page generation, document digest, navigation epoch and actionable-surface digest, reserves the operation and emits `dispatch_boundary` immediately before execution;
7. Browser forwards that worker admission ACK; Agentd may then release final-use authority. A worker-confirmed pre-effect rejection emits `dispatch_rejected` with `localDispatchCrossed=false` and becomes a terminal failed/no-dispatch receipt;
8. remote/page/business terminality is observed/reconciled separately.

A pipe write alone is not a crossed effect. Only a worker admission ACK proves the local boundary; a worker-confirmed pre-dispatch rejection proves no effect crossed. Timeout/transport uncertainty without either proof remains indeterminate and never makes the operation identity fresh or authorizes redispatch.

## 4. Durable recovery and secret boundary

`FileBrowserOperationJournal` now validates exact fields on every hydrated record, rejects unknown fields, validates checksum envelopes, fsyncs before dispatch, uses private non-symlink paths, rejects semantic identity conflicts, atomically compacts the live snapshot before capacity exhaustion and retires a clean terminal profile generation after close. The effect owner rejects volatile journals unless an explicit test-only opt-in is supplied. A generation with durable operation history cannot be reopened into a fresh worker, unresolved effects from another generation block profile advancement, and persisted recovery automatically retires the generation once all its operations become terminal.

The durable record intentionally omits the complete `typedAction`. `type.text`, credential bytes, upload content/host paths, page HTML and worker stderr do not enter the journal. Durable identity stores the final payload digest and immutable effect semantics required for replay/reconciliation.

Terminal identities may leave the bounded in-memory cache while remaining durable until profile-generation retirement. Persisted indeterminate identities never rerun final-use authority or dispatch. They use a separate trusted persisted-reconciliation driver port; the current subprocess driver intentionally returns indeterminate unless a real terminal observer is injected, because a replacement Servo process cannot infer a crashed worker's remote business outcome.

## 5. Semantic observe -> reason -> act loop

The current-pin Servo worker implements a bounded semantic observation through a fixed worker-owned script. `hepta.browser.semantic-observation.v1` includes bounded title, visible text, HTTP(S) links, forms, unique page-local CSS selectors for visible actionable controls and viewport metadata. Password inputs, hidden controls and control values are excluded.

The worker canonicalizes the observation, emits `semanticDigest`, and includes that digest in `documentDigest`. `BrowserProfileHost` rechecks the semantic digest and caller observation budget before publication.

Each admitted semantic observation advances page generation and stores an actionable-surface digest over links, controls and forms. Worker admission rechecks page generation, document digest, navigation epoch and a fresh actionable-surface digest. Click/type/focus selectors must belong to that exact visible admitted control surface; disabled controls are denied and generic type cannot target password/non-text-entry controls, with execution-time visibility/disabled/password checks repeated by the fixed script. Every crossed effect also invalidates the Browser host's page observation, so later new effects require a fresh observation.

## 6. Private worker protocol and Linux isolation

`apps/hepta-browser/src/worker-protocol.js` implements `hepta.browser.worker-frame.v1`: four-byte big-endian framing, <=1 MiB canonical JSON, protocol/session/generation/monotonic sequence/request ID/payload digest binding.

`dispatch_boundary` is a worker-originated admission frame, not a pipe-write callback; it is emitted only after stale-state revalidation and operation reservation. Ordinary responses additionally echo the original request kind and request payload digest. The host fails/kills the channel on cross-session/generation frames, sequence drift, unregistered frame kind, unknown request identity or request/response binding mismatch. Worker stderr is continuously drained without entering durable receipts.

`LinuxBubblewrapLauncher` is a source launch contract, not self-issued target enforcement evidence. It starts from an empty root; exposes selected runtime libraries/fonts/TLS data rather than host `/` or whole `/usr`; clears environment; uses `--unshare-all` without network sharing; hides general host binaries, user homes and service roots; mounts one private profile and exact worker; and uses parent-death containment. Both Bubblewrap and `prlimit` are exact SHA-256-bound host executables. `prlimit` installs explicit address-space, CPU-time, open-file and process ceilings before the sandbox starts.

`scripts/linux-sandbox-probe.js` executes the same launcher and tests host-secret invisibility, denied external IPv4 connection, absence of general shell/Python binaries, private-profile write/fsync, exact in-sandbox RLIMIT_AS/RLIMIT_CPU/RLIMIT_NOFILE/RLIMIT_NPROC values and cleanup of Bubblewrap plus every reported sandbox descendant. The receipt qualifies only the exact host/kernel/Bubblewrap/prlimit tuple that ran it.

## 7. Resource/capacity model

Current source ceilings include <=1 active profile/worker process per Browser service by default (configurable only up to 64 for a compatible injected driver), <=128 origins/profile, <=1024 admitted effect grants/profile, a generic owner ceiling of <=1024 nonterminal effects/profile with the current one-WebView subprocess driver restricted to 1 outstanding effect, <=256 terminal operations retained in host memory, <=64 queued mutations per serialization key by default, <=1 MiB host observation request, <=256 KiB real worker semantic observation, <=1 MiB private worker frame, <=64 MiB file journal with compaction starting at 48 MiB, bounded typed-action fields and driver/authority deadlines. Linux launch additionally defaults to 8 GiB RLIMIT_AS, 300 seconds RLIMIT_CPU, 4096 RLIMIT_NOFILE and 256 RLIMIT_NPROC, all carried from Agentd configuration and verified by the real sandbox probe.

The current worker is one Servo / one WebView per profile generation. The pilot <=16-tabs target is not claimed by this candidate and requires a later measured scheduler/profile.

## 8. Current native implementation

- **Owner facade:** [apps/hepta-browser/src/runtime.js](../../../apps/hepta-browser/src/runtime.js) — `openProfile`, `observePage`, `navigateOrAct`.
- **Owner state machine:** [apps/hepta-browser/src/runtime-host.js](../../../apps/hepta-browser/src/runtime-host.js).
- **Typed actions/provenance:** [apps/hepta-browser/src/action.js](../../../apps/hepta-browser/src/action.js), [apps/hepta-browser/src/bridge.js](../../../apps/hepta-browser/src/bridge.js).
- **Durability:** [apps/hepta-browser/src/journal.js](../../../apps/hepta-browser/src/journal.js).
- **Bounded concurrency:** [apps/hepta-browser/src/runtime-boundary.js](../../../apps/hepta-browser/src/runtime-boundary.js).
- **Private worker transport:** [apps/hepta-browser/src/worker-protocol.js](../../../apps/hepta-browser/src/worker-protocol.js), [apps/hepta-browser/src/worker-driver.js](../../../apps/hepta-browser/src/worker-driver.js).
- **Current-pin Servo worker:** `apps/hepta-browser/servo-worker/`.
- **Private Agentd parent service:** `apps/hepta-browser/src/agentd-protocol.js`, `agentd-service.js`, `agentd-service-main.js`.
- **Real Agentd final-use handoff / named caller:** `codex-rs/hepta-agentd/src/browser_servo.rs`, `codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs`.
- **Focused Browser tests:** `browser.test.js`, `action.test.js`, `bridge.test.js`, `runtime.test.js`, `runtime-boundary.test.js`, `journal.test.js`, `worker-protocol.test.js`, `worker-driver.test.js`, `agentd-service.test.js`.

## 9. Concrete verification cases

- **BROWSER-01:** stale page/document/navigation/action-surface state cannot cross worker admission; every effect invalidates the prior observation and the next new effect requires a fresh observation.
- **BROWSER-02:** page content cannot widen authority; typed action/worker protocol are closed-world; target Linux isolation probe denies direct external egress.
- **BROWSER-03:** source allocates a fresh principal-bound private profile directory; real cross-principal cookie/cache/storage isolation remains a target-host Servo evidence gate.
- **BROWSER-04:** durable intent precedes worker admission; a pipe write alone is not the final-use boundary; worker-confirmed pre-dispatch rejection is terminal failed/no-dispatch; post-boundary timeout/error remains indeterminate; process-loss recovery reconciles without redispatch.
- **BROWSER-05:** proposal navigation ID/policy digest/expected revision are bound into the final effect identity.
- **BROWSER-06:** `type.text`/credential bytes are absent from the durable journal.
- **BROWSER-07:** worker response must echo exact request kind and payload digest; protocol drift fails the channel.
- **BROWSER-08:** bounded mutation queue rejects overload instead of accumulating unbounded waiters.
- **BROWSER-09:** journal hydration rejects malformed/unknown records; compaction preserves latest immutable identities and profile retirement removes closed generations.

## 10. Qualification gates and remaining evidence

Repository/source gates include complete Browser Node tests and JS syntax checks; exact current-pin worker `cargo check --locked` plus worker unit tests; real Bubblewrap sandbox probe; two deterministic release builds with byte equality; dynamic-library closure, worker smoke, worker SHA-256 and deterministic SPDX SBOM; real Agentd `FinalUseAuthority` handoff test, named caller compile and Clippy; and Lane-B exact-source and deterministic synthetic-merge checks.

Still separately open until exact receipts exist: reviewed committed worker `Cargo.lock` and terminal-success exact-SHA reproducible worker artifact/SBOM; independent Linux target-host no-listener/no-egress/descendant/profile isolation evidence; macOS/Windows isolation equivalents if targeted; functional credential broker and upload/download terminal observers if enabled; real remote business terminal observations/reconciliation; target resource/soak measurements; trusted long-running authority/revocation feed for default daemon activation; independent operator acceptance, promotion and release.

These are evidence/activation gates, not permission to weaken source semantics. The repository candidate must remain truthful while they are open.

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

Each worker generation receives a fresh random private profile directory plus a mode-0600 `hepta.browser.profile-owner.v1` manifest binding profile ID, principal ID, generation, Browser manifest digest and profile grant digest. A stale `${profileId}.${generation}` directory is never silently reused under another principal.

A new browser effect linearizes as:

1. validate current profile/page/document generation, typed action, provenance, destination, payload digest, grant, epoch and deadline;
2. challenge Agentd with the exact request digest;
3. Agentd enters real `FinalUseAuthority::with_verified_use` and holds the live revocation mutex;
4. Browser binds the current witness and fsyncs an indeterminate dispatch record;
5. Browser performs exactly one local private-worker pipe write;
6. Browser reports `dispatch_boundary`; Agentd may then release final-use authority;
7. remote/page/business terminality is observed/reconciled separately.

A timeout/error after durable dispatch never makes the operation identity fresh and never authorizes redispatch.

## 4. Durable recovery and secret boundary

`FileBrowserOperationJournal` now validates exact fields on every hydrated record, rejects unknown fields, validates checksum envelopes, fsyncs before dispatch, uses private non-symlink paths, rejects semantic identity conflicts, atomically compacts the live snapshot before capacity exhaustion and retires a clean terminal profile generation after close.

The durable record intentionally omits the complete `typedAction`. `type.text`, credential bytes, upload content/host paths, page HTML and worker stderr do not enter the journal. Durable identity stores the final payload digest and immutable effect semantics required for replay/reconciliation.

Terminal identities may leave the bounded in-memory cache while remaining durable until profile-generation retirement. Persisted indeterminate identities reconcile without rerunning final-use authority or dispatch.

## 5. Semantic observe -> reason -> act loop

The current-pin Servo worker implements a bounded semantic observation through a fixed worker-owned script. `hepta.browser.semantic-observation.v1` includes bounded title, visible text, HTTP(S) links, forms, page-local CSS selectors for actionable controls and viewport metadata. Password inputs and control values are excluded.

The worker canonicalizes the observation, emits `semanticDigest`, and includes that digest in `documentDigest`. `BrowserProfileHost` rechecks the semantic digest and caller observation budget before publication.

Each admitted semantic observation advances page generation. An action derived from an earlier observation therefore fails the stale page-generation fence even if page script changed DOM without navigation.

## 6. Private worker protocol and Linux isolation

`apps/hepta-browser/src/worker-protocol.js` implements `hepta.browser.worker-frame.v1`: four-byte big-endian framing, <=1 MiB canonical JSON, protocol/session/generation/monotonic sequence/request ID/payload digest binding.

Responses additionally echo the original request kind and request payload digest. The host fails/kills the channel on cross-session/generation frames, sequence drift, unexpected frame kind, unknown request identity or request/response binding mismatch. Worker stderr is continuously drained without entering durable receipts.

`LinuxBubblewrapLauncher` is a source launch contract, not self-issued target enforcement evidence. It starts from an empty root; exposes selected runtime libraries/fonts/TLS data rather than host `/` or whole `/usr`; clears environment; uses `--unshare-all` without network sharing; hides general host binaries, user homes and service roots; mounts one private profile and exact worker; and uses parent-death containment.

`scripts/linux-sandbox-probe.js` executes the same launcher and tests host-secret invisibility, denied external IPv4 connection, absence of general shell/Python binaries and private-profile write/fsync. The receipt qualifies only the exact host/kernel/Bubblewrap tuple that ran it.

## 7. Resource/capacity model

Current source ceilings include <=128 origins/profile, <=1024 admitted effect grants/profile, <=1024 nonterminal effects/profile, <=256 terminal operations retained in host memory, <=64 queued mutations per serialization key by default, <=16 live worker profiles by default, <=1 MiB host observation request, <=256 KiB real worker semantic observation, <=1 MiB private worker frame, <=64 MiB file journal with compaction starting at 48 MiB, bounded typed-action fields and driver/authority deadlines.

`PooledSubprocessBrowserDriver` provides the process-pool ceiling while preserving one Servo / one WebView per profile generation. Linux launches run under `prlimit` with default 8 GiB address-space, 300 CPU-second, 4096-FD and 256-process/thread ceilings. Contained workers retain their pool slot until profile cleanup. These are source ceilings, not target capacity measurements. The pilot <=16-tabs target remains unclaimed and requires a later measured scheduler/profile.

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

- **BROWSER-01:** stale page/observation generation cannot authorize an action; every semantic observation advances generation.
- **BROWSER-02:** page content cannot widen authority; typed action/worker protocol are closed-world; target Linux isolation probe denies direct external egress.
- **BROWSER-03:** source allocates a fresh principal-bound private profile directory; real cross-principal cookie/cache/storage isolation remains a target-host Servo evidence gate.
- **BROWSER-04:** durable intent precedes local dispatch; concurrent duplicates dispatch once; post-boundary timeout/error remains indeterminate; process-loss recovery reconciles without redispatch.
- **BROWSER-05:** proposal navigation ID/policy digest/expected revision are bound into the final effect identity.
- **BROWSER-06:** `type.text`/credential bytes are absent from the durable journal.
- **BROWSER-07:** worker response must echo exact request kind and payload digest; protocol drift fails the channel.
- **BROWSER-08:** bounded mutation queue rejects overload instead of accumulating unbounded waiters.
- **BROWSER-09:** journal hydration rejects malformed/unknown records; compaction preserves latest immutable identities and profile retirement removes closed generations.

## 10. Qualification gates and remaining evidence

Repository/source gates include complete Browser Node tests and JS syntax checks; exact current-pin worker `cargo check --locked`; real Bubblewrap sandbox probe; two deterministic release builds with byte equality; dynamic-library closure, worker smoke, worker SHA-256 and deterministic SPDX SBOM; real Agentd `FinalUseAuthority` handoff test, named caller compile and Clippy; and Lane-B exact-source and deterministic synthetic-merge checks.

Still separately open until exact receipts exist: reviewed committed worker `Cargo.lock` and terminal-success exact-SHA reproducible worker artifact/SBOM; independent Linux target-host no-listener/no-egress/descendant/profile isolation evidence; macOS/Windows isolation equivalents if targeted; functional credential broker and upload/download terminal observers if enabled; real remote business terminal observations/reconciliation; target resource/soak measurements; trusted long-running authority/revocation feed for default daemon activation; independent operator acceptance, promotion and release.

These are evidence/activation gates, not permission to weaken source semantics. The repository candidate must remain truthful while they are open.

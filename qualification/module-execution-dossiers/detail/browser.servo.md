# browser.servo: implementation design

Parent: `docs/modules/browser.servo/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: hardened native browser driver/effect boundary and UI projections implemented; real Servo worker, target-host isolation and independent acceptance remain open. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-browser`, `third_party/servo-patches`.
Packages: `BROWSER-WEB-C1`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`open_profile(profile_id, grant, browser_manifest) -> BrowserSession`; `observe_page(session, page_generation, observation_budget) -> PageObservation`; `navigate_or_act(session, typed_action, final_payload, grant) -> BrowserEffectObservation`. Freeze the existing Servo source/patch pin and browser manifest before execution. Read observation, navigation, input entry, download and credential use are separately typed capabilities.

The current JavaScript boundary additionally exposes recovery/maintenance operations around those design operations: durable profile recovery, reconciliation of an already-crossed effect identity, and terminal-operation compaction. These maintenance operations do not authorize a new browser effect.

## 3. State records and transaction design

`browser_profile_state` owns isolated profile identity, cookie/credential references, allowed origins, process/session/page generations and outstanding operation IDs. DOM/GUI observations are rebuildable generation-bound evidence with origin and uncertainty. Raw credentials never appear in page observations, context receipts or learning records. Profile files cannot be shared across principals by an unscoped cache.

Before an effect driver call, the current host persists the immutable operation identity with an indeterminate receipt. Typed action bytes are bounded and digest-bound but are not written to the recovery record; persisted semantics retain the payload digest instead. Once the effect boundary may have been entered, timeout/transport/driver failure remains indeterminate and cannot authorize automatic redispatch.

## 4. Deterministic algorithm and scheduling

Start the isolated browser with declared network/filesystem boundaries; authenticate the session; admit page observations as untrusted data; revalidate element/page generation before interaction; final-check destination and payload; obtain a current final-use authority claim; persist the operation intent; dispatch one typed action under final-use revalidation; obtain the trusted terminal observation. Page load is not proof that a transaction or download succeeded.

Per-profile owner operations are serialized. An existing operation identity is resolved before live dispatch admission so an idempotent replay can return the retained receipt even after the original deadline has expired. Reconciliation validates the stored immutable operation identity and does not require the expired grant to become live again.

## 5. Capacity and performance profile

Pilot <= 16 concurrent tabs per granted profile, bounded DOM/GUI node and encoded-byte observation budgets, explicit navigation/action deadlines and download byte ceilings. Measure browser RSS, open descriptors, observation cost and effect-reconciliation latency.

The JavaScript boundary caps active indeterminate operations separately from terminal replay records. Terminal records may be compacted to bounded digest/receipt tombstones without reopening an operation identity.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- BROWSER-01: a stale element/page generation cannot trigger a click in a new document.
- BROWSER-02: page instructions cannot expand network/filesystem/credential scope.
- BROWSER-03: profile isolation prevents cross-principal cookie/cache access.
- BROWSER-04: crash after form submission leaves the business effect indeterminate until reconciled, never blindly resubmitted.
- BROWSER-05: concurrent identical operation calls cross the driver effect boundary at most once.
- BROWSER-06: a driver exception/timeout after possible dispatch remains indeterminate and replay does not redispatch.
- BROWSER-07: reconciliation remains available after the original profile/effect grant and operation deadline expire.
- BROWSER-08: revocation between authority claim and final-use delivery prevents the driver effect call.
- BROWSER-09: an observed ungranted origin quarantines the profile.

The repository tests implement the JavaScript boundary cases above. BROWSER-02/BROWSER-03 still require real target-host Servo/OS evidence; fixture capability claims do not establish sandbox behavior.

## 7. Integration, rollback and capability ceiling

Wrap the existing browser boundary as a digital organ before any physical embodiment. Rollback preserves or quarantines outstanding remote effects and never exports credentials. Source pin and patch identity are part of each qualified deployment.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

The current worker decisions are rebased to the canonical Servo pin in `docs/modules/browser.servo/HARDENING.md` and the three current ADRs in the same directory. Historical `docs/hepta-vnext/browser/*` source identities are non-normative.

## 8. Current native implementation

- **Implemented entrypoints:** `openProfile`, `observePage`, `navigateOrAct`, `reconcileOperation`, `recoverProfile`, `acknowledgeTerminalOperation` in [apps/hepta-browser/src/runtime.js](../../../apps/hepta-browser/src/runtime.js). `buildNavigationEffectInput` in [apps/hepta-browser/src/bridge.js](../../../apps/hepta-browser/src/bridge.js) closes a registered navigation intent into an exact typed effect request.
- **Typed effect boundary:** bounded `navigate`, `click`, `type`, `scroll`, `focus`, `wait` and `download` actions are canonical-digest bound to the effect grant. Raw typed text is not persisted in recovery records.
- **Final-use authority:** runtime composition requires an authority adapter implementing `claim` plus `withVerifiedUse`; there is no permissive default. Local profile/effect-grant/deadline liveness is also rechecked immediately before driver entry.
- **Serialization and terminality:** one profile-scoped single-writer lane prevents open/act/observe/close races. Operation state is recorded before `driver.act`; post-boundary throw/timeout is indeterminate and replay-safe. Reconciliation is separated from live dispatch authorization.
- **State and recovery:** [apps/hepta-browser/src/state-store.js](../../../apps/hepta-browser/src/state-store.js) supplies an atomic file-backed store and an explicit volatile test store. The default runtime requires a durable store; persisted profile/operation state can be recovered without redispatch. This does not itself recover or sandbox a Servo process.
- **Driver contract:** composition fails closed unless the injected driver declares abort-signal, isolated-process, private-control-channel, network-policy, profile-isolation and credential-boundary support. These declarations still require independent target-host evidence.
- **Source tests:** [apps/hepta-browser/test/runtime.test.js](../../../apps/hepta-browser/test/runtime.test.js), [apps/hepta-browser/test/bridge.test.js](../../../apps/hepta-browser/test/bridge.test.js), [apps/hepta-browser/test/browser.test.js](../../../apps/hepta-browser/test/browser.test.js). These are test identities, not deployment/independent-acceptance receipts.
- **Implementation and operating references:** [apps/hepta-browser/README.md](../../../apps/hepta-browser/README.md), [docs/modules/browser.servo/HARDENING.md](../../../docs/modules/browser.servo/HARDENING.md), [docs/modules/browser.servo/IMPLEMENTATION_MAP.json](../../../docs/modules/browser.servo/IMPLEMENTATION_MAP.json), [third_party/servo-patches/WORKER_CONTRACT.json](../../../third_party/servo-patches/WORKER_CONTRACT.json).
- **Remaining work:** build and bind the real Hepta-owned Servo worker for the canonical pin; enforce and independently verify OS sandbox/profile/credential/network isolation; prove no public control listener; supply real navigation/download/business terminal evidence; qualify worker crash/parent death/descendant cleanup and Linux/macOS/Windows behavior; compose a named production caller.

# browser.servo: implementation design

Parent: `docs/modules/browser.servo/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-browser`, `third_party/servo-patches`.
Packages: `BROWSER-WEB-C1`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`open_profile(profile_id, grant, browser_manifest) -> BrowserSession`; `observe_page(session, page_generation, observation_budget) -> PageObservation`; `navigate_or_act(session, typed_action, final_payload, grant) -> BrowserEffectObservation`. Freeze the existing Servo source/patch pin and browser manifest before execution. Read observation, navigation, input entry, download and credential use are separately typed capabilities.

## 3. State records and transaction design

`browser_profile_state` owns isolated profile identity, cookie/credential references, allowed origins, process/session/page generations and outstanding operation IDs. DOM/GUI observations are rebuildable generation-bound evidence with origin and uncertainty. Raw credentials never appear in page observations, context receipts or learning records. Profile files cannot be shared across principals by an unscoped cache.

## 4. Deterministic algorithm and scheduling

Start the isolated browser with declared network/filesystem boundaries; authenticate the session; admit page observations as untrusted data; revalidate element/page generation before interaction; final-check destination and payload; dispatch one typed action; obtain the trusted terminal observation. Page load is not proof that a transaction or download succeeded.

## 5. Capacity and performance profile

Pilot <= 16 concurrent tabs per granted profile, bounded DOM/GUI node and encoded-byte observation budgets, explicit navigation/action deadlines and download byte ceilings. Measure browser RSS, open descriptors, observation cost and effect-reconciliation latency.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- BROWSER-01: a stale element/page generation cannot trigger a click in a new document.
- BROWSER-02: page instructions cannot expand network/filesystem/credential scope.
- BROWSER-03: profile isolation prevents cross-principal cookie/cache access.
- BROWSER-04: crash after form submission leaves the business effect indeterminate until reconciled, never blindly resubmitted.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Wrap the existing browser boundary as a digital organ before any physical embodiment. Rollback preserves or quarantines outstanding remote effects and never exports credentials. Source pin and patch identity are part of each qualified deployment.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

# browser.servo: implementation design

Parent: `docs/modules/browser.servo/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: hardened durable browser effect owner and isolated-worker host boundary implemented; the current-pin Servo worker artifact and independent target qualification remain open. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-browser`, `third_party/servo-patches`.
Package: `BROWSER-WEB-C1`.

Current Servo source identity is declared by `third_party/servo-patches/MANIFEST.json`. The deeper historical WEB-C1 design used older Servo trees; current source/API and feature assertions must be revalidated against the present pin before build admission. See `docs/modules/browser.servo/SERVO_WORKER.md`.

## 2. Public operations and contract details

The design operations remain:

`open_profile(profile_id, grant, browser_manifest) -> BrowserSession`; `observe_page(session, page_generation, observation_budget) -> PageObservation`; `navigate_or_act(session, typed_action, final_payload, grant) -> BrowserEffectObservation`.

The stable JavaScript owner entrypoints remain `openProfile`, `observePage` and `navigateOrAct` in `apps/hepta-browser/src/runtime.js`; additional recovery/grant operations are `admitEffectGrant`, `reconcileOperation`, `reconcilePersistedOperation` and `closeProfile`.

Typed action payloads are closed-world. Navigation binds normalized URL, policy digest and expected revision. Credential/upload actions carry references rather than raw secret bytes or ambient host paths. `src/bridge.js` maps authority-free navigation intents into the exact runtime payload but does not mint an effect grant.

## 3. State records and transaction design

`browser_profile_state` owns profile/principal/process/page generations, allowed origins, admitted effect grants and operation identities. A profile is a single-writer serialization domain.

Before a browser effect can cross the worker boundary:

1. current page/document generation, destination, typed payload digest, grant, epoch and deadline are checked;
2. the final-use authority gate is entered;
3. inside that gate the VerifiedUse witness is bound, the operation dispatch identity is fsynced to the browser journal and one local worker dispatch is issued;
4. any later exception/timeout is represented as `indeterminate`, never as permission to redispatch.

`FileBrowserOperationJournal` is append-only, checksum-bound, bounded and fsynced. Terminal operations may be evicted from the in-memory cache after a bounded retention window because their durable tombstones remain authoritative for replay. A reused operation ID with changed immutable semantics is rejected.

## 4. Deterministic algorithm and scheduling

Profile `open/observe/grant/act/reconcile/close` transitions serialize by profile identity. Concurrent calls for one operation cannot both enter worker dispatch.

New effects require live profile/effect authority. Reconciliation is observational and deliberately remains available after the original grant or action deadline expires; expiry/revocation denies a new effect but does not erase the owner obligation to settle an already-dispatched one.

A page observed outside the allowed-origin set is quarantined and its document digest is removed from the actionable state, so a later action cannot treat it as the current admitted document.

All driver calls have bounded host deadlines. Dispatch receives an AbortSignal; a timeout after durable dispatch becomes an indeterminate operation retained for reconciliation.

## 5. Private worker boundary and isolation

`apps/hepta-browser/src/worker-protocol.js` implements the current Hepta-owned private worker protocol: four-byte big-endian length prefix, <=1 MiB canonical JSON, protocol/session/generation/sequence/request/payload-digest binding and fail-closed decoding.

`apps/hepta-browser/src/worker-driver.js` implements an exact-artifact-digest-bound subprocess driver. It has no TCP/WebDriver control API. The supplied Linux launcher uses Bubblewrap with `--unshare-all`, no `--share-net`, a cleared environment, hidden ambient home/run/tmp state, a private writable profile mount and parent-death cleanup.

This is a concrete host path, not a claim that the pinned Servo artifact exists. The repository still lacks the current-pin Hepta-owned Servo worker executable and its independent runtime evidence.

## 6. Capacity and performance profile

Current hard source bounds include bounded origins/effect grants, maximum outstanding nonterminal operations, bounded terminal in-memory retention, bounded action fields, <=1 MiB worker frames, <=64 MiB operation journal and per-call deadlines.

The dossier's pilot `<=16` concurrent-tab target remains a target, not a measured/fully implemented tab scheduler. Real worker RSS, descriptors, renderer descendants, frame cost, reconciliation latency and download limits require target-host qualification.

## 7. Concrete verification cases

- **BROWSER-01:** stale page generation rejects before dispatch; off-origin observations are quarantined. Real element-generation identity in a Servo DOM observation remains a worker-level acceptance gate.
- **BROWSER-02:** typed action schemas reject ambient secret/path fields; Linux host path denies external network by namespace construction. Real worker/no-egress and credential-broker evidence remain required.
- **BROWSER-03:** the host allocates a private per-session profile root and isolates the process namespace. Real Servo cookie/cache cross-principal qualification remains required.
- **BROWSER-04:** durable intent is recorded before dispatch; post-dispatch driver error/timeout becomes indeterminate; process-loss recovery uses `reconcilePersistedOperation` without redispatch.

Focused source tests additionally cover concurrent duplicate dispatch, final-use fencing, grant expiry recovery, journal tamper rejection, 300-terminal-operation retention/replay, proposal-to-effect bridging, private frame canonicalization, worker artifact digest drift and sandbox argv posture.

These source tests establish repository semantics only. The real Servo artifact, actual target namespace behavior and remote terminal outcomes remain separate evidence.

## 8. Current native implementation

- **Owner entrypoints:** `openProfile`, `observePage`, `navigateOrAct` remain explicit methods in [apps/hepta-browser/src/runtime.js](../../../apps/hepta-browser/src/runtime.js), preserving the implementation-map source anchors.
- **State machine:** [apps/hepta-browser/src/runtime-host.js](../../../apps/hepta-browser/src/runtime-host.js) owns profile serialization, final-use linearization, dynamic grant admission, no-redispatch semantics and recovery.
- **Typed payloads:** [apps/hepta-browser/src/action.js](../../../apps/hepta-browser/src/action.js) and [apps/hepta-browser/src/bridge.js](../../../apps/hepta-browser/src/bridge.js).
- **Durability:** [apps/hepta-browser/src/journal.js](../../../apps/hepta-browser/src/journal.js) provides memory and private file journals; persisted indeterminate effects can be reconciled after host loss.
- **Worker boundary:** [apps/hepta-browser/src/worker-protocol.js](../../../apps/hepta-browser/src/worker-protocol.js) and [apps/hepta-browser/src/worker-driver.js](../../../apps/hepta-browser/src/worker-driver.js) provide private framed transport, artifact binding and the Linux Bubblewrap host path.
- **Focused tests:** `apps/hepta-browser/test/browser.test.js`, `action.test.js`, `bridge.test.js`, `runtime.test.js`, `journal.test.js`, `worker-protocol.test.js`, `worker-driver.test.js`.
- **Operating references:** [apps/hepta-browser/README.md](../../../apps/hepta-browser/README.md), [docs/modules/browser.servo/SERVO_WORKER.md](../../../docs/modules/browser.servo/SERVO_WORKER.md), [docs/modules/browser.servo/IMPLEMENTATION_MAP.json](../../../docs/modules/browser.servo/IMPLEMENTATION_MAP.json).

### Remaining implementation and external evidence

The following are still open and must not be represented as completed by this source change:

1. build the Hepta-owned Servo worker against the exact current pin and independently verify its source/topology/features;
2. produce reproducible build/toolchain receipts, worker digest, symbols and SBOM;
3. connect the real Servo WebView/event/render loop to the private protocol;
4. implement final credential-reference resolution without logging/exporting raw credential bytes;
5. qualify real Linux namespace/no-egress/listener/descendant cleanup behavior, then provide equivalent macOS and Windows isolation;
6. prove real cross-profile cookie/cache/storage isolation;
7. prove real stale-element behavior and terminal navigation/download/business reconciliation;
8. compose a named non-test `runtime.agentd`/product caller and obtain the separate activation/deployment/independent-acceptance evidence.

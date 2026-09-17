# browser.servo: implementation design

Parent: `docs/modules/browser.servo/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable typed browser effect owner boundary implemented; host-side private
worker process/sandbox contract implemented for Linux C1; actual pinned Servo
worker artifact, cross-platform isolation, product composition and independent
acceptance remain open. Common requirements: `../EXECUTION_SEMANTICS.md` and
`../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `apps/hepta-browser`, `third_party/servo-patches`.
Package: `BROWSER-WEB-C1`.
Current Servo pin: `84bcc9ac701874fa9819e5cdee06356b961d736c`.

## 2. Public operations and contract details

`open_profile(profile_id, grant, browser_manifest) -> BrowserSession`;
`observe_page(session, page_generation, observation_budget) -> PageObservation`;
`navigate_or_act(session, typed_action, final_payload, grant, verified_use) -> BrowserEffectObservation`.

The runtime requires a closed typed action payload, exact payload digest,
destination origin, registered effect grant, VerifiedUse witness and a current
final-use authority observation. Read observation, navigation, input entry,
upload, download and credential-reference use are separately typed capabilities.

## 3. State records and transaction design

`browser_profile_state` owns isolated profile identity, allowed origins, process
and page generations, isolation digests and outstanding operation IDs. Raw
credentials remain external references.

Every effect writes a durable operation intent with an indeterminate receipt
before entering `driver.act`. The durable record contains immutable effect
semantics and the typed payload. Reusing one operation ID with changed semantics
is a hard failure. A driver throw, timeout or host crash after durable intent can
never make the operation fresh again.

The current durable implementation is
`apps/hepta-browser/src/journal.js`. It atomically replaces a mode-0600 bounded
journal after fsync. Process restart reloads outstanding operations. Terminal
operations do not consume the 1024 outstanding-effect capacity; the in-memory
terminal cache is separately bounded while durable identity remains queryable.

## 4. Deterministic algorithm and scheduling

One profile generation is a serialized mutation owner:

1. validate profile/principal/generation and current page/document generation;
2. normalize the typed action and verify its canonical payload digest;
3. verify destination/origin and effect-grant binding;
4. verify the VerifiedUse witness binding;
5. call the current final-use authority/revocation port;
6. recheck the action deadline;
7. persist the indeterminate effect intent;
8. dispatch one driver action under AbortSignal/deadline;
9. record the observed terminal result, or keep the durable result
   indeterminate;
10. reconcile an indeterminate identity without redispatch.

Reconciliation is a recovery operation, not a new effect. It uses stored
semantics and remains legal after the original grant, witness, profile lease or
action deadline expires. It has a new bounded reconciliation deadline.

## 5. Capacity and performance profile

Current source ceilings include 128 origins, 1024 effect grants, 1024
simultaneously nonterminal operations, 1,000,000 observation budget units, a
30-second maximum host-side driver call window, bounded typed payload fields and
a 16 MiB / 16,384-record durable operation journal. These are source limits, not
target-host performance measurements.

## 6. Concrete verification cases

- BROWSER-01: stale element/page generation cannot trigger a new-document
  effect.
- BROWSER-02: page instructions cannot expand network/filesystem/credential
  scope; out-of-scope observed origins quarantine the profile.
- BROWSER-03: real worker profile/cookie/cache isolation must prevent
  cross-principal access.
- BROWSER-04: crash/throw/timeout after possible form submission remains
  indeterminate and can only reconcile, never redispatch.
- BROWSER-05: concurrent duplicate operation IDs cause exactly one dispatch.
- BROWSER-06: expiry after dispatch cannot disable reconciliation or cleanup.
- BROWSER-07: typed payload, destination, grant, epoch and VerifiedUse drift fail
  before dispatch.
- BROWSER-08: process restart reloads outstanding durable identities.

BROWSER-03 and real OS/network enforcement still require actual Servo/host
evidence. Source tests are not independent acceptance receipts.

## 7. Integration, rollback and capability ceiling

`apps/hepta-browser/src/adapter.js` now bridges the authority-free local
navigation proposal to a typed digest-bound effect request without minting
permissions. `apps/hepta-browser/src/servo-process-driver.js` implements the
host-side private length-prefixed protocol and a Linux bubblewrap launch contract
using inherited control fd 3, verified worker/launcher digests, clear child
environment, a private profile bind and denied external network for C1.

The current repository still has no qualified `hepta-servo-worker` artifact.
The process driver and sandbox launch contract therefore do not establish real
Servo execution or deployment qualification. See
`docs/modules/browser.servo/SERVO_WORKER.md`.

## 8. Current native implementation

- **Implemented owner entrypoints:** `openProfile`, `observePage`,
  `navigateOrAct`, `reconcileOperation`, and `closeProfile` in
  `apps/hepta-browser/src/runtime.js`.
- **Typed effect contract:** `apps/hepta-browser/src/actions.js`.
- **Durable recovery:** `apps/hepta-browser/src/journal.js`.
- **Proposal/effect bridge:** `apps/hepta-browser/src/adapter.js`.
- **Private worker host/sandbox boundary:**
  `apps/hepta-browser/src/servo-process-driver.js`.
- **Source tests:** `apps/hepta-browser/test/browser.test.js`,
  `runtime.test.js`, `actions.test.js`, `journal.test.js`, `adapter.test.js`,
  `servo-process-driver.test.js`.
- **Remaining product work:** reproducibly build the actual worker from the
  current Servo pin; implement child-side Servo WebView integration; prove real
  OS/network/profile/credential isolation; provide real navigation/download and
  business terminal observations; compose a named non-test caller; independently
  qualify target hosts.

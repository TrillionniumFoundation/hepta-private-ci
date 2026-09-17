# Hepta browser

This root contains the `browser.servo` owner boundary. It keeps authority-free
navigation proposals separate from final-use browser effects, binds every effect
to a typed payload digest, and never treats a driver acknowledgement as authority.
The current Servo source identity remains pinned separately under
`third_party/servo-patches`.

## Current source surfaces

- `src/browser.js` — authority-free navigation proposals and page projections.
- `src/actions.js` — closed typed browser-action vocabulary and canonical payload
  digesting for navigation, click, type, scroll, focus, wait, upload, download,
  and credential-reference fill.
- `src/runtime.js` — serialized profile owner, page-generation fencing,
  final-use authority verification, durable pre-dispatch intent, indeterminate
  effect reconciliation, timeout/AbortSignal handling, quarantine, and bounded
  in-memory terminal receipt retention.
- `src/journal.js` — mode-0600 atomic durable operation journal. Once an effect
  intent is durable, the same operation identity is never eligible for a fresh
  dispatch after a throw, timeout, replay, or process restart.
- `src/adapter.js` — bridge from the local authority-free navigation proposal to
  a typed digest-bound effect request. It does not mint a grant or VerifiedUse
  witness.
- `src/servo-process-driver.js` — host-side private worker protocol plus the
  Linux bubblewrap launch contract. It verifies launcher/worker SHA-256 digests,
  uses inherited control fd 3 instead of a network listener, clears the child
  environment, binds a private profile directory, and uses a network namespace
  with external egress denied for the C1/local-fixture posture.

The legacy object entrypoints in `src/browser.js` remain compatibility surfaces.
The additive `Local` JSON entrypoints are versioned, private-workspace internal
exports for shadow qualification, not registered module ingress or egress and
not production callers. The export is a repository convention, not JavaScript
enforcement. These entrypoints bound the encoded envelope before parsing,
require the repository's lexicographic object-key order, and reject duplicate,
missing, unknown or otherwise non-canonical fields.

## Authority and recovery boundary

`BrowserProfileHost` requires an injected final-use authority port and a durable
operation journal. The authority port must verify the current lease/revocation
frontier and consume/verify the supplied VerifiedUse witness immediately before
dispatch. A successful final-use check is still not external-effect evidence.

Effects are journaled as `indeterminate` before `driver.act` is entered. If the
driver throws, times out, or the host crashes after the effect may have crossed
the boundary, replay returns the same durable receipt and reconciliation is the
only admissible path. Reconciliation and cleanup remain available after the old
effect grant, VerifiedUse witness, profile lease, or action deadline expires;
expiry blocks new effects, not observation of an already-dispatched identity.

## Servo execution status

The repository still does **not** contain a qualified `hepta-servo-worker`
artifact or a reproducibly built Servo binary. `src/servo-process-driver.js`
implements the host-side launch/protocol boundary; it is not evidence that the
pinned Servo source has been built, that the worker implements the protocol, or
that Linux/macOS/Windows sandbox behavior has passed independent qualification.
See `docs/modules/browser.servo/SERVO_WORKER.md` for the current implementation
contract and remaining gates.

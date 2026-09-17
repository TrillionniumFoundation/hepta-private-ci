# browser.servo effect-boundary hardening

Status: current implementation addendum for `browser.servo` on the canonical main-line Servo pin.

This document narrows the gap between the module contract and the JavaScript browser-driver boundary. It does not claim that the repository contains a qualified Servo worker, an OS sandbox, a credential broker, external-network enforcement, deployment qualification, or a production caller.

## Current source identity

The canonical upstream Servo identity remains the source pin recorded by `third_party/servo-patches/MANIFEST.json`:

- repository: `servo/servo`
- branch: `main`
- commit: `84bcc9ac701874fa9819e5cdee06356b961d736c`
- integration mode: `pinned_upstream_with_hepta_adapter_boundary`

Historical `docs/hepta-vnext/browser/*` designs were written against older candidate pins. Their security decisions are rebased here and in the current ADRs below; their old source identities are not normative for this module revision.

## Implemented JavaScript boundary

`apps/hepta-browser/src/runtime.js` now enforces the following boundary rules before a browser effect can cross into a driver:

1. one profile-scoped single-writer lane serializes open, observe, effect, reconcile, compaction and close transitions;
2. a typed browser action is normalized and bounded, and its canonical digest must equal `finalPayloadDigest`;
3. the effect grant must bind action kind, destination origin, payload digest and authority epoch;
4. a final-use authority adapter must successfully `claim` the exact binding and `withVerifiedUse` must revalidate it immediately around dispatch;
5. the operation is durably recorded as `dispatching` with an `indeterminate` receipt before `driver.act` is entered;
6. once the driver effect boundary may have been entered, driver exceptions, transport loss and deadline expiry remain `indeterminate`; the same operation identity is never automatically dispatched again;
7. reconciliation uses the stored immutable operation semantics and remains permitted after the original profile/effect grant or operation deadline has expired;
8. terminal operations can be compacted to bounded replay tombstones without reopening the operation identity;
9. an observed origin outside the granted set quarantines the profile instead of returning an interactive observation;
10. driver calls receive an `AbortSignal`, and the driver capability contract requires abort support plus process, control-channel, network, profile and credential isolation claims.

The capability contract is fail-closed at composition time, but a JavaScript boolean is not independent OS evidence. A real driver must still prove those claims on the target host.

## Typed action contract

The current driver boundary accepts these bounded action kinds:

- `navigate { url }`
- `click { selector, button }`
- `type { selector, text, replace }`
- `scroll { deltaX, deltaY }`
- `focus { selector }`
- `wait { condition, timeoutMs }`
- `download { url, maxBytes }`

Raw typed-action bytes are supplied only to the effect call. Persisted operation semantics retain the payload digest and routing identity rather than raw typed text, so input text does not become a crash-recovery record.

## Final-use authority seam

The host requires an injected authority adapter with two operations:

- `claim(binding)` — obtains one final-use claim for the exact subject, destination, request digest, scope digest, payload digest and authority epoch;
- `withVerifiedUse(token, binding, consumer)` — revalidates current authority/revocation state and executes the effect consumer under that final-use fence.

This seam is intentionally shaped around the existing `kernel.authority` final-use model. There is no permissive default authority implementation in the browser host.

## Durable state and crash recovery

`apps/hepta-browser/src/state-store.js` provides:

- an explicit volatile test store; and
- an atomic file-backed store with mode-0600 state files and fsync-before-rename publication.

A durable store is required by default. Volatile operation state must be opted into explicitly for tests.

Before process or transport recovery, `listRecoverableProfiles()` and `recoverProfile()` expose the retained profile/operation state. Recovery does not redispatch an uncertain effect. Only `reconcileOperation()` can refine an indeterminate effect to a trusted terminal observation.

This durable record is not a replacement for the missing Servo-process recovery contract. A real worker must still bind process identity, private channel identity, source/build receipt and OS sandbox generation.

## Remaining non-repository/host integration gates

The following remain open and must not be inferred from JavaScript tests:

- build a real Hepta-owned Servo worker from the canonical source pin;
- bind the worker artifact digest, Servo source/tree and patch inventory to launch;
- enforce one-process/one-session/one-WebView behavior in the worker;
- use an inherited private control channel with no WebDriver/TCP control listener;
- install target-OS process, filesystem, profile, credential and network sandboxing;
- prove external egress policy and redirect containment at the browser/OS layer;
- prove cross-principal cookie/cache/profile isolation with the real worker;
- supply real navigation/download/business-effect terminal observations;
- qualify parent death, child crash, timeout, cancellation and descendant cleanup on Linux, macOS and Windows;
- compose a named non-test product caller and retain independent acceptance evidence.

## Current ADRs

- `ADR-0001-private-worker-transport.md`
- `ADR-0002-inherited-private-channel.md`
- `ADR-0003-hepta-owned-servo-embedder.md`

These files carry forward the useful decisions from the historical vNext browser work while rebasing the normative source identity to the current Servo pin and keeping runtime/deployment authority false.

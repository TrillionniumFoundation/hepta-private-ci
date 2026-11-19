# Hepta browser

This root contains the repository-owned `browser.servo` boundary. It now has two deliberately separated layers:

1. authority-free browser presentation/proposal helpers in `src/browser.js`;
2. a stateful effect owner in `src/runtime.js` / `src/runtime-host.js`, with typed actions, final-use authority fencing, a durable operation journal, replay of recorded terminal outcomes and an optional isolated subprocess driver.

The code in this package does **not** by itself prove that a Servo artifact exists or has passed deployment qualification. `third_party/servo-patches/MANIFEST.json` remains the canonical upstream source pin; a worker executable must additionally be artifact-digest bound before `SubprocessBrowserDriver` will launch it.

## Proposal to effect path

`buildNavigationIntent()` remains authority-free. `src/bridge.js` converts an admitted `BrowserNavigationIntentV1` plus a matching `BrowserSessionV1` / `PageObservationV1` into the exact typed `navigate` payload used at the effect boundary. The payload digest binds the normalized URL, policy digest and expected revision. The bridge never mints authority; an effect grant and final-use authority check remain mandatory.

Typed runtime actions are closed-world and bounded. Current action kinds are `navigate`, `click`, `type`, `credential`, `upload`, `focus`, `scroll`, `wait` and `download`. Credential and upload actions carry only `credentialRef` / `fileRef` plus bounded metadata; raw secret bytes and ambient filesystem paths are rejected as unknown fields.

## Effect correctness

`BrowserProfileHost` serializes profile mutations and reserves an operation identity before dispatch. Final-use authority is expressed as `authority.withVerifiedUse(request, callback)`: durable intent fsync and local worker dispatch execute inside that fence. A concurrent retry therefore cannot race a revocation or dispatch the same operation twice.

After a dispatch may have crossed the worker boundary, exceptions and timeouts become `indeterminate`. They never delete the operation identity and never authorize redispatch. Host policy permits reconciliation of the original identity after the profile/effect deadline; this permission alone does not provide a surviving worker readback channel. Expiry fences new effects and requests that execution stop.

`FileBrowserOperationJournal` is append-only, checksum-bound, size-bounded, fsynced and mode-0600 on Unix. `reconcilePersistedOperation()` can replay an already-recorded terminal outcome after a host restart without issuing another effect. An unresolved record requires readback from its original worker identity; the journal does not by itself establish that outcome. Terminal operations are bounded in memory while durable tombstones remain available for replay.

### Stopped-worker recovery: SOURCE_ONLY_HOLD

The current `SubprocessBrowserDriver.stop()` closes its client, clears the child/client handles and removes the private profile directory. The Servo worker's operation table is in memory, and the worker exits on stop. There is no current attach/reopen endpoint or durable worker outcome store that reconstructs unresolved observations after that session is lost.

Consequently, closing or expiring a real subprocess profile can leave unresolved operations fenced and `indeterminate`; a later reconciliation attempt cannot use the discarded client and can report `reconcile_error`. A new host/worker session does not prove the old operation's outcome. Already-durable terminal records remain replayable, but recovery of unresolved operations after stop/restart is **SOURCE_ONLY_HOLD**. The host retains the original identity and never redispatches it. Implementing that missing recovery capability requires a reviewed durable readback/attachment contract and an owning process fixture; keeping an expired effect-capable worker alive is not a substitute.

## Worker boundary

`src/worker-protocol.js` implements the private protocol: four-byte big-endian length prefix, at most 1 MiB canonical JSON, payload digest, session ID, generation, monotonic sequence and request identity. Unknown/non-canonical frames fail closed.

`SubprocessBrowserDriver` launches only an exact SHA-256-bound worker artifact through a launcher that declares and enforces the required isolation posture. The supplied Linux launcher uses Bubblewrap with `--unshare-all`, no `--share-net`, a cleared environment, hidden ambient home/run/tmp state, a private profile bind, an inherited pipe control channel and parent-death cleanup. This is a concrete Linux isolation path, but it is not evidence that the pinned Servo worker artifact has been built or independently qualified.

## Verification

Run from the repository root:

```sh
node --test apps/hepta-browser/test/*.test.js
```

The focused suite covers canonical URL/proposal parsing, typed actions, proposal-to-effect bridging, duplicate-dispatch exclusion, post-dispatch failures, host-policy reconciliation after deadline expiry using test drivers, final-use fencing, durable journal replay, journal tamper rejection, bounded retention, private framing, artifact binding and the Linux sandbox command posture. A fake driver that retains reconciliation after stop does not establish recovery through the real subprocess driver after its session is destroyed.

For the module completion boundary and remaining Servo artifact gates, see `docs/modules/browser.servo/TECHNICAL.md`, `docs/modules/browser.servo/SERVO_WORKER.md` and `qualification/module-execution-dossiers/detail/browser.servo.md`.

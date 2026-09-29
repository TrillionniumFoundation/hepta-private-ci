# Hepta browser

This root contains the repository-owned `browser.servo` boundary. It now has two deliberately separated layers:

1. authority-free browser presentation/proposal helpers in `src/browser.js`;
2. a stateful effect owner in `src/runtime.js` / `src/runtime-host.js`, with typed actions, final-use authority fencing, durable operation recovery and an optional isolated subprocess driver.

The code in this package does **not** by itself prove that a Servo artifact exists or has passed deployment qualification. `third_party/servo-patches/MANIFEST.json` remains the canonical upstream source pin; a worker executable must additionally be artifact-digest bound before `SubprocessBrowserDriver` will launch it.

## Proposal to effect path

`buildNavigationIntent()` remains authority-free. `src/bridge.js` converts an admitted `BrowserNavigationIntentV1` plus a matching `BrowserSessionV1` / `PageObservationV1` into the exact typed `navigate` payload used at the effect boundary. The payload digest binds the normalized URL, policy digest and expected revision. The bridge never mints authority; an effect grant and final-use authority check remain mandatory.

Typed runtime actions are closed-world and bounded. Current action kinds are `navigate`, `click`, `type`, `credential`, `upload`, `focus`, `scroll`, `wait` and `download`. Credential and upload actions carry only `credentialRef` / `fileRef` plus bounded metadata; raw secret bytes and ambient filesystem paths are rejected as unknown fields.

## Effect correctness

`BrowserProfileHost` serializes profile mutations and reserves an operation identity before dispatch. Final-use authority is expressed as `authority.withVerifiedUse(request, callback)`: durable intent fsync and local worker dispatch execute inside that fence. A concurrent retry therefore cannot race a revocation or dispatch the same operation twice.

Authority entry is one-shot and explicitly closed when verification fails, times out,
or returns without invoking its consumer. A rejected Promise is not cancellation:
a retained late callback cannot dispatch after the profile lock is released or
another operation has started. The callback checks both the wall deadline and
its original monotonic entry budget, including a stalled event loop. The shorter
profile, effect-grant and operation expiry bounds dispatch without rewriting the
original request digest. Driver calls reject expired work at actual invocation;
there is no one-millisecond grace period after a slow durable intent write.
Completion rechecks the same wall deadline and original monotonic budget before
publishing an eligible result, including synchronous stalls and microtask chains
that delay timer callbacks. The clock cannot regress from actual driver entry.
An over-deadline return does not prove that an entered effect failed or stopped:
the host retains its operation as indeterminate for fresh reconciliation, with
no redispatch. AbortSignal requests remain cancellation requests, not process
termination or task-success evidence.

After a dispatch may have crossed the worker boundary, exceptions and timeouts become `indeterminate`. They never delete the operation identity and never authorize redispatch. Reconciliation observes the original identity and is intentionally allowed after the original profile/effect deadline has expired; expiry prevents a new effect, not recovery of an old one.

`FileBrowserOperationJournal` is append-only, checksum-bound, size-bounded, fsynced and mode-0600 on Unix. A process restart can use `reconcilePersistedOperation()` without issuing another effect. Terminal operations are bounded in memory while durable tombstones remain available for replay.

The V1 journal now uses the same monotonic reducer for memory, writes and replay.
Every non-outcome field is immutable; equal request/semantic hashes do not permit
changing the principal, target, epoch or deadline. Dispatch retries retain the
latest outcome without adding bytes. A terminal result cannot return to unknown
or become a different terminal result. Input scalars are copied before queuing.
Incomplete final records reject without repair-by-append. Valid legacy V1
observations that accidentally included public receipt fields remain readable:
the original checksum is checked first, and only fixed non-authorizing presentation
fields are projected away. A positive authority flag is never accepted.

Durable acknowledgment follows file sync and parent-directory sync, including
newly created ancestors. A possible write, sync or close failure poisons that
live handle: queued writes, ordinary reads and deduplication cannot turn uncertain
persistence into success. Pure semantic rejection before I/O does not poison
unrelated work. This is not a cross-process lock or rollback-independent recovery
frontier. The V1 reader still scans bounded history; indexed recovery, compaction,
owner fencing, directory race isolation and generation retirement remain the
separately implemented Browser convergence profile's integration work.


### Live journal identity and observed-history fence

A live journal handle retains the device/inode, length and SHA-256 of its last
validated prefix. A file it has observed cannot disappear and be recreated as
an empty operation history. Truncation, prefix rewriting, a replacement inode,
invalid UTF-8 and read/close failures poison the same handle, including queued
requests. Restoring the file does not silently unpoison it. First creation is
exclusive; an append must still see the exact predecessor used by the reducer.
After file and parent sync, the same descriptor and current path must expose
that predecessor plus the exact appended bytes before acknowledgment.

Reads use bounded positional chunks with one extra growth-detection byte, not
an unbounded readFile following a stat. This is a conservative observation fence,
not a cross-process owner lock or an atomic filesystem namespace guarantee.
The high-water observation is process-local: reopening requires the existing
owner's independent recovery policy, and cannot detect an old valid backup by
itself. No new journal schema, replay namespace, global store or retry permission
is introduced. Full-history validation and extra append checks still have growing
cost; no compaction, indexed recovery or long-term throughput claim is made.

`test/journal-frontier.test.js` exercises actual filesystem deletion, truncation,
replacement, same-length checksummed rewriting, restoration after corruption,
queued operations and replacement during fsync. These are bounded owner tests,
not power-loss, hostile multiwriter or real Servo acceptance evidence.

## Worker boundary

`src/worker-protocol.js` implements the private protocol: four-byte big-endian length prefix, at most 1 MiB canonical JSON, payload digest, session ID, generation, monotonic sequence and request identity. Unknown/non-canonical frames fail closed.

`SubprocessBrowserDriver` launches only an exact SHA-256-bound worker artifact through a launcher that declares and enforces the required isolation posture. The supplied Linux launcher uses Bubblewrap with `--unshare-all`, no `--share-net`, a cleared environment, hidden ambient home/run/tmp state, a private profile bind, an inherited pipe control channel and parent-death cleanup. This is a concrete Linux isolation path, but it is not evidence that the pinned Servo worker artifact has been built or independently qualified.

## Agentd channel lifecycle and capacity

The selected `BrowserProfileHost` is an implementation object with prototype
methods, not a JSON record. `BrowserAgentdService` validates its required methods
without rejecting that actual class. Incoming frames, payloads and final-use
requests still require plain, canonical records; the owner contract does not
relax the wire contract.

Each request has one final-use exchange and an identity-bound lifetime. Closing
the request removes an outstanding receive waiter. If its exchange or consumer
still runs, the channel becomes unusable: a late `authority_enter`, even with a
reused request ID, cannot enter a new scope or publish a dispatch boundary.
Stream errors discard queued input and reject outstanding reads/writes. A whole
decoded batch passes sequence and capacity validation before any waiter receives
it; a valid authority prefix followed by a replay cannot release the consumer.
No invalidated channel is automatically reset, and no uncertain effect is retried.

Transport bounds are explicit: at most 64 queued frames and 4 MiB of encoded
queued input; 8 receive waiters; 8 pending writes and 4 MiB of encoded pending
output. Output-capacity rejection happens before a write or sequence advance.
Draining returns capacity without resetting sequence identity. The decoder keeps
one bounded frame body, copies fragmented input once, and rejects malformed UTF-8
instead of replacing bytes. It admits at most 64 frames per call and an input
chunk of at most `4 * (1 MiB + 4 bytes)`. Invalid or incomplete final input
permanently closes that decoder; it is not repaired by appending another frame.

These are channel-level bounds, not process containment or total system memory
limits. Channel invalidation does not attest physical stop, device-memory release
or remote task success. The existing durable operation owner must reconcile any
possibly entered effect before resources or replay rights can be settled.

`test/agentd-real-host.test.js` composes the actual service, selected host,
private-channel authority and file journal. A fresh host reopens the fsynced
operation and reconciles without redispatch; driver outcomes are controlled test
observations, not real Servo effects. A separate real Node child executes the
shipped service entry point and rejects an unopened profile without launching a
worker. It catches startup composition defects that a plain-object host double
cannot. Channel/decoder regressions cover late scope completion, malformed
batches, bounded queues, write errors and fragmented input. These tests do not
supply native Agentd admission, cryptographic authority or actual GUI acceptance.

## Verification

Run from the repository root:

```sh
node --test apps/hepta-browser/test/*.test.js
```

The focused suite covers canonical URL/proposal parsing, typed actions,
proposal-to-effect bridging, duplicate-dispatch exclusion, post-dispatch failures,
deadline-expired reconciliation, final-use fencing, late authority callbacks,
monotonic terminal replay, file/directory/close fault injection, caller mutation,
legacy presentation compatibility, durable recovery, journal tamper rejection,
bounded retention, private framing, artifact binding and the Linux sandbox command
posture. Run the complete suite rather than only newly added cases.

For the module completion boundary and remaining Servo artifact gates, see `docs/modules/browser.servo/TECHNICAL.md`, `docs/modules/browser.servo/SERVO_WORKER.md` and `qualification/module-execution-dossiers/detail/browser.servo.md`.

### Unified-candidate verification scope

The existing Browser Agentd composition workflow runs the **complete** Browser
JavaScript suite plus Agentd formatting, native FinalUse tests, compile and strict
lint on source-head and fixed-base merge candidates. It retains exact identity and
logs; a passing subset is not a successful workflow. It uses the normal `just test`
entry point, does not change source in CI and does not grant execution authority.

`test/authority-deadline.test.js` exercises the actual host with controlled
verifier/driver callbacks. Those tests prove local rejection/ordering behavior,
not actual Servo effects, OS isolation, arbitrary computer control or independent
user-task completion. Journal durability/monotonicity and real-worker tests remain
separate obligations, never skipped to certify these timing changes. The Browser
convergence line owns its richer durable journal, replay and worker-atomic target
profile; it must be integrated as a compatible implementation, not partially
copied or inferred from these callback fixes. Laya output remains a proposal and
cannot mint the final-use authority consumed by this host.

# Hepta browser

This root contains the repository-owned `browser.servo` boundary:

1. authority-free browser presentation/proposal helpers in `src/browser.js`;
2. a stateful effect owner in `src/runtime.js` / `src/runtime-host.js`, with typed actions, final-use authority fencing, durable operation recovery and an optional isolated subprocess driver.
3. private worker and Agentd parent protocols, plus current-pin Rust Servo embedder source in `servo-worker/`.

The worker source is present; a successful current-pin native build and qualified binary remain distinct obligations. `third_party/servo-patches/MANIFEST.json` is the canonical upstream source pin, and a worker executable must be artifact-digest bound before `SubprocessBrowserDriver` will launch it. Source presence and CI configuration do not prove successful Servo execution or deployment qualification.

## Proposal to effect path

`buildNavigationIntent()` remains authority-free. `src/bridge.js` converts an admitted `BrowserNavigationIntentV1` plus a matching `BrowserSessionV1` / `PageObservationV1` into the exact typed `navigate` payload used at the effect boundary. The payload digest binds the normalized URL, policy digest and expected revision. The bridge never mints authority; an effect grant and final-use authority check remain mandatory.

Typed runtime actions are closed-world and bounded. Current action kinds are `navigate`, `click`, `type`, `credential`, `upload`, `focus`, `scroll`, `wait` and `download`. Credential and upload actions carry only `credentialRef` / `fileRef` plus bounded metadata; raw secret bytes and ambient filesystem paths are rejected as unknown fields.

## Effect correctness

`BrowserProfileHost` serializes profile mutations and reserves an operation identity before dispatch. Final-use authority is expressed as `authority.withVerifiedUse(request, callback)`: durable intent fsync and local worker dispatch execute inside that fence. A concurrent retry therefore cannot race a revocation or dispatch the same operation twice.

After a dispatch may have crossed the worker boundary, exceptions and timeouts become `indeterminate`. They never delete the operation identity and never authorize redispatch. Reconciliation observes the original identity and is intentionally allowed after the original profile/effect deadline has expired; expiry prevents a new effect, not recovery of an old one.

`FileBrowserOperationJournal` is append-only, checksum-bound, size-bounded, fsynced and mode-0600 on Unix. A process restart can use `reconcilePersistedOperation()` without issuing another effect. Terminal operations are bounded in memory while durable tombstones remain available for replay.

Journal replay validates strict UTF-8, complete lines, immutable scalar records and monotonic terminal results. Same-path instances serialize together, and atomic `<journal>.writer-lock` directories exclude another process. A crash or uncertain write/fsync preserves the lock; owner recovery must confirm the old writer stopped, inspect/reconcile and sync the journal before explicitly clearing it. Recovery never authorizes redispatch. Reliable local-file metadata guards the validated replay cache and external changes force full replay; identical retries append zero bytes.

## Worker boundary

`src/worker-protocol.js` implements the private protocol: four-byte big-endian length prefix, at most 1 MiB canonical JSON, payload digest, session ID, generation, monotonic sequence and request identity. Unknown/non-canonical frames fail closed.

`SubprocessBrowserDriver` launches only an exact SHA-256-bound worker artifact through a launcher that declares and enforces the required isolation posture. The supplied Linux launcher uses Bubblewrap with `--unshare-all`, no `--share-net`, a cleared environment, an empty tmpfs root plus runtime-library/font/TLS allowlist, private home/run/tmp state, a private profile bind, an inherited pipe control channel and parent-death cleanup. Direct external networking remains denied even for admitted origins; actual web access needs a separately authorized network broker. This source path still requires exact-host execution evidence.

`src/agentd-service-main.js` exposes a parent-only inherited stdio service with a final-use challenge and a separate local-dispatch acknowledgement. The named Agentd source caller is `codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs`, backed by `BrowserServoPort` and the real `FinalUseAuthority`. It executes one call per fresh service process; a persistent product-session/daemon lifecycle and live revocation owner remain activation work.

Worker pending calls are bounded; malformed responses, EOF and pipe errors fail closed. Direct driver callers must supply a bounded `AbortSignal`. The parent service caps queued input at 64 frames/4 MiB and cancels expired authority reads. Native Agentd transport deadlines and permanent port fencing prevent an incomplete exchange from being reused. The configured `service_sha256` binds the Node entrypoint only; imported modules and the Node/Bubblewrap runtime closure still require separate immutable packaging and identity binding.

The Servo worker source uses one software-rendered WebView and fixed worker-owned scripts for DOM actions. Credential, upload and download actions are admitted typed forms but fail closed as `capability_not_connected` until their brokers and terminal observers are connected and qualified. Navigation/DOM behavior requires real current-pin execution tests.

## Verification

Run from the repository root:

```sh
node --test apps/hepta-browser/test/*.test.js
```

The focused suite covers canonical URL/proposal parsing, typed actions, proposal-to-effect bridging, duplicate-dispatch exclusion, post-dispatch failures, deadline-expired reconciliation, final-use fencing, durable recovery, journal tamper rejection, bounded retention, private framing, artifact binding, parent challenge ordering and the Linux sandbox command posture. Fixture-worker tests exercise Node transport semantics and do not compile or execute Servo. The separate worker workflow defines locked native compilation, reproducibility, SBOM and real-sandbox start/stop gates; actual successful run receipts are required.

Affected Browser source changes now select the Browser Node job in the aggregate blocking CI's required fan-in, with the private-process dependency mapped to the Agentd caller and reverse consumers. Structured worker evidence validation binds canonical repository/pin, resolved features, source/tree, worker/lock/SBOM and smoke identities; target admission also requires the reviewed committed source lock. Deep worker/target qualification remains opt-in and main/manual admission remains unchanged.

For the module completion boundary, current audit and remaining artifact/activation gates, see `docs/modules/browser.servo/TECHNICAL.md`, `docs/modules/browser.servo/SERVO_WORKER.md`, `docs/modules/browser.servo/AUDIT.md` and `qualification/module-execution-dossiers/detail/browser.servo.md`.

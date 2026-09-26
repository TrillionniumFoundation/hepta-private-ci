# Experimental local-model worker

`codex_hepta_infer_worker_host::local_model` is available only with the `experimental-local-model` feature. It is deliberately excluded from the default product surface and cannot be cited as production execution, deployment qualification or independent acceptance.

## Sealed authority boundary

A local worker accepts only a `VerifiedResourceGrant`. Callers can construct signed wire claims, but cannot construct the verified handle directly. `ResourceGrantVerifier` checks the configured Ed25519 issuer key, exact issuer identity, authority epoch, current revocation revision and head digest, grant ID and nonce, worker identity and generation, validity interval, the complete model/runtime/device tuple, all resource ceilings and the recomputed semantic digest.

The verified grant retains a shared monotonic revocation state. Load, run and unload recheck expiry and current revocation before entering their boundary. An advanced revocation set immediately denies a previously verified grant when its grant ID is revoked. This does not replace a deployed revocation-distribution service or trusted target-host clock.

## Model, input and driver boundary

`VerifiedModelManifest` binds model, weights, tokenizer, preprocessor, quantization, runtime, device and device-lease identities to the verified grant. `VerifiedInput` owns actual bounded input bytes and proves their digest before dispatch. `AttestedModelHandle` is constructed only after an injected driver result agrees with a separate `TrustedResourceObserver` for the exact generation, handle, device lease and resident-memory observation.

The async `LocalModelDriver` contract is:

- `load`: consume a verified manifest and grant;
- `run`: consume an attested handle, actual verified input bytes, cancellation token and trusted absolute deadline;
- `inspect`: reconcile an existing durable operation without starting another run;
- `unload`: report an observed terminal release.

A fake driver remains useful only inside tests. It cannot mint any of the sealed types and its results are not product evidence.

## Aggregate resource manager

`ResourceManager` performs checked, aggregate accounting across resident model memory, outstanding load reservations and per-request transient memory. Load and run reservations use RAII guards. Arithmetic underflow or overflow fences the generation instead of being hidden with saturating operations.

Model lifecycle states are `Loading`, `Ready`, `Draining`, `Zombie` and `RepairRequired`. The worker does not remove a model handle until driver unload is terminal, a trusted observer reports zero resident bytes and the exact device lease still matches. A driver unload error retains the handle and resident accounting as `Zombie`; identity drift, over-capacity observation or device reset moves the model to `RepairRequired` and fences the generation.

The observer is a trust port. A driver-reported memory number alone is insufficient. Target deployment must provide an observer backed by an independently qualified device/OS boundary.

## Durable execution and recovery

Local operations reuse `DurableInferenceControl`; they do not introduce a second journal. Before physical execution the worker durably records:

1. exact request and semantic identity;
2. payload digest over the actual input, model attestation and ceilings;
3. reservation and authority epoch;
4. worker generation and assignment digest bound to the grant witness and model handle.

An exact duplicate consumes the journal. A conflicting reuse of the request ID fails. Once assignment is durable, a driver error, timeout-like loss or process restart is not safe-to-retry evidence. Reopen calls `inspect(operation_id)` only; it never calls `run` again for the same durable operation.

Terminal observations are settled only when token and usage observations are both known and bounded. A terminal provider result with missing usage remains `UsagePending`; unknown usage is never encoded as zero. A missing or in-flight reconciliation remains quarantined and retains its durable assignment.

## Explicit non-completion gates

The repository implementation does not establish:

- a production local driver consuming named real weights and tokenizer bytes;
- a production device/OS resource observer;
- trusted-clock and revocation distribution on the target host;
- OOM, device-reset, process-kill and load-stage fault qualification on real hardware;
- an authenticated production caller;
- independent acceptance, promotion or release.

Those gates must remain false in `CURRENT_STATUS.json` and the implementation map until source-bound external receipts exist.

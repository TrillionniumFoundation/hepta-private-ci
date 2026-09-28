# Experimental local-model worker

`LocalModelWorker` is an opt-in, non-production surface enabled by `local-model-experimental`. Default builds and the production `hepta-infer-worker --profile native-app-server` binary do not expose it.

## Non-constructible verification boundary

Local execution accepts only:

- `VerifiedResourceGrant`, created by `GrantVerifier` after canonical semantic-digest validation, expiry/revocation checks and an independently replay-protected authority claim;
- `VerifiedModelManifest`, created after exact model/weights/tokenizer/preprocessor/quantization/runtime/device binding and physical artifact attestation;
- `AttestedModelHandle`, created only after a trusted device authority observes the exact loaded tuple and memory footprint;
- `VerifiedInput`, which owns the exact input bytes, verifies their digest and carries a trusted monotonic deadline.

Public raw claims cannot be converted into verified types without the configured authority ports.

## Driver contract

`LocalModelDriver` is asynchronous and provides `load`, `run`, `inspect`, `unload` and cleanup for an unattested raw load. `run` receives the exact verified input, live cancellation token and trusted deadline. `inspect` is mandatory for restart recovery; a driver error or process reopen never authorizes a blind second execution.

An injected driver remains a test/integration component until independent evidence identifies real weights, tokenizer, runtime, device, memory and fault behavior.

## Resource manager

`ResourceManager` atomically accounts for:

- model loading/loaded/unloading/zombie memory;
- request KV and transient memory;
- model count and in-flight concurrency;
- worker generation and device identity.

Reservations are RAII guards. Arithmetic is checked. A model handle is removed only after an exact terminal unload observation. Failed or abandoned unloads become `Zombie` and retain their accounted bytes. A trusted device observation above the selected limit fences the generation.

## Durable execution

`LocalInferenceRuntime` reuses `DurableInferenceControl`; it does not create a second journal. The transition is:

1. submit exact operation identity;
2. reserve quota/tokens;
3. reserve local aggregate resources;
4. persist assignment with grant, artifact, input and device witnesses;
5. call the physical driver once;
6. inspect rather than replay after unknown failure or reopen;
7. settle only exact terminal observations with trusted usage.

Exact terminal duplicates return the existing record without invoking the driver. A conflicting identity fails. Terminality with unknown usage becomes `UsagePending` and remains assigned; unknown usage is not encoded as zero.

## Remaining production gates

The feature flag does not prove:

- a production grant issuer or revocation distributor;
- real weight/device loading;
- OS/accelerator memory attestation;
- process isolation or authenticated control channel;
- OOM, device-reset, load-kill and crash-at-every-transition qualification;
- product composition, target-host deployment or independent acceptance.

These gates remain explicit in the generated `CURRENT_STATUS.json` artifact. Product callers must not enable this feature as a substitute for those receipts.

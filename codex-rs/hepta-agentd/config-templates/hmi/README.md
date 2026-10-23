# HMI integration materials

These files are passive, incomplete templates for the existing owner. They are
not installed configuration or a launcher. Zero generations, expired/revoked
policies, empty thread allowlists and invalid public-key placeholders deliberately
prevent admission. No credential, device enrollment, OS grant or deployment
change is included. The JSON argv array documents the existing `main.rs` flags;
it is not a configuration file accepted by Agentd.

Use the existing Supervisor's owner/process configuration when an authorized
operator later integrates this path. Do not start a second conversation owner or
invent `HEPTA_AGENT_GENERATION`. The existing Supervisor supplies
`HEPTA_FLEET_ROOT`, `HEPTA_AGENT_ID`, `HEPTA_AGENT_GENERATION`, `HEPTA_AGENT_HOME`
and `HEPTA_AGENT_RUN_ROOT`. The thread already exists in that Agent's App Server.

## Required materials

| Material | Source and contract |
| --- | --- |
| Owner binaries and paths | Matching reviewed Agentd/App Server and media-producer builds, build features, versions and digests; existing Supervisor configuration and persistent owner home/run root. |
| Public issuer registry | Existing registered issuer, Ed25519 public key and nonzero key epoch, current revocation state and exact existing thread allowlist. `authbus-trust.template.json` follows `src/authbus_trust.rs`. Keep the original producer's private key in its existing signing boundary; never copy it into this directory or chat. |
| Replay witness | The independent, retained checkpoint for this exact existing owner/evidence history, plus its established storage/backup procedure. There is deliberately no checkpoint template or guessed digest. Do not synthesize a witness from an untrusted or rolled-back database. |
| Audio source policy | Existing device/organ identities and generations, independently retained monotonic capture generation, bounded validity and revocation source. `audio-authority.template.json` follows `src/audio_policy.rs`. It does not grant microphone access. |
| Controlled media root | Existing canonical private direct child of the Agent home, same owner, bounded retention/quota and release after the original observation is acknowledged. Current Unix checks reject symlinks, hardlinks, foreign ownership and access by others. Preparing these materials makes no filesystem permission change. |
| Media artifacts | Trusted multilingual Whisper model, selected Piper voice/model/config, ONNX runtime, Silero model and required phonemizer library/data. Supply independently verified provenance, versions, digests, licenses and existing paths. SHA-256 identifies bytes; it does not establish trust. The Pipecat `rust/crates/pipecat-hepta/config-templates/local-speech.template.json` describes the actual `LocalSpeechConfig` shape. |
| Actual platform and devices | Adopted OS/audio backend, exact native input/output device IDs, existing OS permissions, sample rates and device authority. This source profile currently requires Unix owner checks; Windows needs its own reviewed ownership/ACL implementation. Do not bypass the checks. |
| Acceptance inputs | Chinese and target-language speech, reproducible noise/echo conditions, interruption cases, hotplug/revocation/model-crash/restart scenarios, target workload/duration and end-to-end latency/resource limits. |

## Runtime sequence and evidence

The existing producer connects to `<run_root>/hmi-text.sock`. `attach` authenticates
without admitting a request. Signed final text uses the existing AuthBus text
ingress. Signed audio uses `SignedAudioObservationV1` and
`audio_observation_claims()` with the exact current policy-file byte digest,
existing thread, current Agentd generation and controlled PCM reference. Bind
the same principal/device/organ/capture generations and
`logical_session_id = "thread:<existing-thread-id>"` in the media configuration.
The existing independent signer, not an HMI text/qualification endpoint, supplies
the signature. Current issuer, thread and device policy are checked again before
dispatch and publication. A live session cannot switch between text and audio
authorization profiles or epochs, even if its identity labels happen to match.

For audio, retain the original signed envelope and observation receipt.
`committedAudioObservation` on `inputError` means the canonical observation is
known committed while `admissionReady:false` reports failed later readiness. It
does not establish Core admission, model completion, playback or any tool effect.
Without such a receipt, a timeout/failure can still be uncertain; reconcile the
original request rather than inventing a replacement ID. `reconcileAudio` reads
the original observation under current permissions; it never inserts a delivery.
`reconcile` performs Core lookup only. `cancelRecovered` retires local output
first and requests cancellation of the exact existing queue entry/turn; its
acknowledgement keeps `terminalObserved:false`. Cancellation cannot undo already
committed tool effects. Keep original operation IDs for their reconciliation.

Record generated, queued, submitted, device-observable playback, interrupted and
unknown separately. A sound-card-buffer submission is not proof of listening.
The software cloud fixtures use real owner processes, signatures, SQLite and
temporary PCM, with synthetic model SSE. They do not validate physical capture,
STT/TTS quality, speaker playback, echo/noise, device permissions or hardware
latency. Real speech/model/device acceptance and any production credential or
policy integration remain dependent on the above external materials.

Current cloud regression commands, run from `codex-rs` with its pinned toolchain:

```sh
cargo clippy --locked -p codex-hepta-agentd --lib --bin codex-hepta-agentd --test hmi_owner_v3_product --profile dev-small --no-deps -- -D clippy::all
just test --locked -p codex-hepta-agentd --lib --features qualification-legacy-learning-write --cargo-profile dev-small
just test --locked -p codex-hepta-agentd --test hmi_owner_v3_product --test hmi_text_product --test authbus_text_product --cargo-profile dev-small --success-output immediate
```

The legacy learning feature in the unit command qualifies its existing Rust
error/ledger code; it is not a deployment requirement or evidence that adaptive
neuron control is enabled. Production HMI uses deterministic interruption and
does not put privacy, permissions or emergency stop under learned control.

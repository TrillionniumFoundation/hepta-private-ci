# Signed captured-audio observations

Agentd's optional HMI port accepts `submitAudio` only when its existing AuthBus
trust/checkpoint configuration and an explicit `--hmi-audio-authority-file` are
present. `AgentdConfig::with_hmi_audio_authority_file()` supplies the same path.
The default remains text only. This profile does not open audio hardware,
request OS permissions, enroll a device/key, create credentials or enable TTS.
It accepts a registered producer's signed observation about controlled PCM.

`AudioObservationBodyV1` and `SignedAudioObservationV1` are distinct contracts in
`src/audio_observation.rs`. Neither `AuthBusTextBody` nor qualification evidence
is reinterpreted. `audio_observation_claims()` defines the canonical signing
bytes for an independently authorized producer using its existing key.

The signed body contains the current Agentd spawn generation, existing thread,
final text, SHA-256 of the exact owner policy bytes, and `HmiCapturedAudioRefV1`.
The reference includes principal, device and organ IDs/generations, logical
session, capture generation, utterance sequence, asset ID, byte SHA-256/length,
sample rate/channels and half-open sample interval. This initial product profile
accepts PCM16LE, 16 kHz mono, at most 1 MiB per segment. Length must be twice the
interval length; the asset is exactly `capture-GENERATION-SEQUENCE.pcm16`.
The registered producer attests the capture identity and interval. Signature and
file checks bind those claims to bytes; they do not prove that physical hardware
captured them or that the transcription is semantically correct.

The independently managed private policy file has these fields:

| Field | Meaning |
| --- | --- |
| `schema_version`, `agent_id` | Version 1 and this actual owner |
| `issuer_id`, `key_epoch` | Existing AuthBus principal/key registration; no new public key is accepted here |
| `device_id`, `device_generation` | Explicit source identity and incarnation |
| `organ_id`, `organ_generation` | Explicit capture organ identity/incarnation, independent of Agentd process restarts |
| `capture_generation` | Current retained capture incarnation |
| `media_root` | Existing canonical private direct child of the owner home |
| `max_segment_bytes` | Positive limit, at most 1 MiB |
| `expires_at_ms`, `revoked` | Current owner policy expiry/revocation |

The file is read with the original owner-controlled-file checks. Media reads
reject links, extra hard links, foreign ownership, public permissions, wrong
length/digest and inode/metadata changes. The existing media owner must retain
exclusive control of this root and its ancestors; Agentd neither writes nor
deletes assets. The media producer's existing store owns quota, retention,
release and monotone capture generations. No PCM frames enter the event ledger,
neuron or model input. Only final text is submitted to Core; its original
`hepta.authbus:<delivery_id>` binds it to the persisted signed source metadata.

Audio uses its own AuthBus domain, including principal/device/organ/capture
incarnations. The domain deliberately excludes the target thread. The signed
sequence equals the source sequence and advances the original persistent replay
fence; the external replay checkpoint covers it. An exact retained duplicate is
idempotent. A new message ID reusing a captured sequence is rejected, including
after a complete Agentd process restart. This initial profile has one current
capture policy. Policy rotation immediately fences old sessions; old queued
routes cannot dispatch under a new capture incarnation and expire within the
original five-minute message bound. Existing bounded outbox capacity can apply
backpressure while those records expire.

The HMI `admission` frame contains an `audioObservation` receipt with the exact
source, observation/policy digests, delivery ID and actual queued/leased/
queueAccepted/expired/quarantined state. Queue acceptance is neither model
completion nor playback. Current issuer/thread/device policy is refreshed after
the asynchronous media read, before and after admission, at Core dispatch and at
publication. Revocation after a commit preserves that committed record and its
failure context; it never fabricates rollback. A failed or unknown admission
must be reconciled using the original delivery.

For process recovery, a first `attach` command carries a currently signed
`AuthBusTextIngress` for the existing thread. This authenticates the new UI
connection without inserting an input or starting a model. `reconcile` uses
the original delivery ID and exact text with Core `ReconcileOnly`.
`cancelRecovered` retires local presentation, reconciles the original input,
then deletes that exact durable queue row or requests interruption of its exact
persisted turn. A queue/turn race permits another read-only lookup; it never
recreates an absent/cancelled input. The resulting request acknowledgement keeps
`terminalObserved:false`. It does not assert tool rollback or an observed model
terminal. A cold interrupted turn remains interrupted unless separately and
explicitly recovered by the original product owner.

`reconcileAudio` carries the exact original signed audio envelope. It reads the
retained observation under current issuer/thread/device policy and the original
signature/expiry. The old Agentd spawn is historical on this read-only path; it
cannot authorize new admission. No lease, replay advancement, insertion, file
availability assertion or model dispatch occurs. Original metadata can be
compared with the producer's retained input even after owner process replacement.
This does not create a post-expiry or post-revocation access exception.

An `inputError` can carry `committedAudioObservation` and
`admissionReady:false` when the canonical observation committed before a replay
checkpoint or authorization refresh failed. Preserve that original receipt for
reconciliation; it is not a Core queue, model, playback or tool-effect receipt.
Failure without a receipt still does not prove absence. The relay connects to
the existing Core before claiming a first delivery attempt, so a known failed
connection cannot consume first-admission eligibility. Once a request may have
crossed the seam, recovery remains lookup-only under its original identity.

After a crash the HMI listener reclaims only its own private socket, following
connection-refused and inode/ownership checks. Live sockets, links, regular
files and changed paths are rejected. Existing filesystem/device/deployment
permissions are not modified. Runtime task quarantine retains and logs its
bounded cause; writer/session futures remain owned through cleanup.

Cloud qualification is `tests/hmi_owner_v3_product.rs`: actual supervised Agentd
with its embedded App Server, original fixture signing identity, SQLite/Core,
temporary private PCM files and HTTP SSE model fixtures. It covers identity,
incarnations, intervals/digests, links, active revocation, process replacement,
same-request recovery, queue cancellation, input/frame pressure and finite
resource-growth measurements. Its latency samples measure software send-to-text
terminal only. They are not microphone-to-speaker percentiles or long-run device
acceptance. Trusted multilingual STT/TTS artifacts, actual adopted platform/device
authority and real speech/fault/performance acceptance remain separate inputs.

See [config-templates/hmi/README.md](config-templates/hmi/README.md) for passive
templates and the exact remaining integration materials. They do not install or
activate this profile.

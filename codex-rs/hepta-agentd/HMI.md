# Agentd-owned HMI text port

The optional `--hmi-text` flag / `AgentdConfig::with_hmi_text()` registers the
existing HMI coordinator in Agentd's `RuntimeTasks`. It requires the already
configured `--authbus-trust-file` and `--authbus-checkpoint-file`. No key,
registration, production identity or external-effect authority is generated.
The default process exposes no HMI port.

The port listens on `<AgentdIdentity.run_root>/hmi-text.sock`, with owner-only
Unix socket permissions. One active UI session, one pending input, a 32-entry
output channel and 64 KiB frames are hard bounds. Writer, initial-read, RPC and
cleanup deadlines are explicit; writer/session futures stay owned on failure.
An HMI session failure is isolated from Agentd's required runtime tasks.

The first newline JSON command must be `{"type":"submit","request":...}`.
`request` is an existing independently signed `AuthBusTextIngress`, including
its original message ID, sequence, expiry and `AuthBusTextBody`. Its thread must
already exist. This adapter does not start another conversation.

Agentd checks its actual current generation/readiness and reloads its actual
`TextTrust` public-key/thread registry. The signature covers the canonical
original body. A discovery connection reads the existing thread/session/home
and server version; HMI then resumes that exact thread with `excludeTurns:true`.
An existing loaded persistent thread can now be materialized for that explicit
subscription before its first user input. Default history-bearing resume still
rejects unmaterialized storage; no history or permissions are replaced.

HMI input goes through `authbus_ingress::submit`, the original evidence outbox,
replay checkpoint and `authbus_dispatch` Core relay. Presentation tracks the
original `hepta.authbus:<delivery_id>`; it never submits another `hepta.hmi:*`
queue entry. Existing canonical deliveries never rearm output after reconnect.
A locally minted admission fence prevents interrupt-during-lookup from reopening
output. Live generation and issuer/thread permission are checked during input,
control handling and publication, and refreshed while the UI is idle.

Further commands are:

```jsonl
{"type":"interrupt"}
{"type":"reconnect"}
{"type":"reconcile","delivery_id":"ORIGINAL_64_HEX_DELIVERY_ID","text":"EXACT_ORIGINAL_TEXT"}
{"type":"stop"}
```

`reconcile` uses Core `ReconcileOnly`, retains the original identity and never
opens output or resubmits the model. Another signed `submit` may follow. A
duplicate after reconnection must neither replay output nor block that next
distinct input. Receipts keep their real AuthBus state; queue admission is not
model completion or external-tool success.

`attached` and `reconnected` carry the actual binding/connection incarnation.
`output` carries the coordinator's scoped deltas, final text or terminal outcome.
`admissionPending`, `admission`, `reconciled`, `inputError`, `outputRetired`,
`interruptRequested` and `sessionTerminal` retain separate meanings. Local output
admission closes before remote interruption; this does not retract text already
copied by the client or roll back committed tools. A terminal request ack does
not claim a terminal model receipt. Disconnect/unknown admission requires
reconciliation of the original delivery, never a replacement request.

The default profile is text only. Its principal is the actual registered AuthBus issuer;
the local Agent UI identity is scoped by that key epoch and Agent spawn. These
fields are not microphone/device permissions. `capture_generation` is zero,
and audio verification, speech and audio-observation methods fail explicitly.
No placeholder audio receipt is issued. The current `AuthBusTextBody` has only
spawn generation, thread ID and text; `KernelEvidenceAppend` accepts a signed
qualification evidence envelope, not a captured-audio observation. A sourced
audio product profile must explicitly integrate the media reference and actual
device authority rather than reinterpret either contract.

Qualification uses `tests/hmi_text_product.rs` with the original test issuer/key
from `tests/support/authbus_text.rs`, a real supervised Agentd/App Server, real
private UDS, signature checks, SQLite outbox/checkpoint and persisted Core turns.
Only the model's HTTP SSE response is a fixture. It covers invalid signatures,
Chinese deltas, same-thread/client-ID persistence, duplicates, reconnection,
the next distinct input, live cancellation and current-trust revocation.
It is not production-user, physical audio or end-to-end performance acceptance.

```sh
just test --locked -p codex-hepta-agentd --test hmi_text_product --cargo-profile dev-small
```

The cloud source audit retains all failed attempts and original-candidate
identities under `/workspace/pipecat-hmi-audit-20261023/`.

The explicit opt-in signed source profile and process-recovery commands are
documented in [AUDIO_OBSERVATIONS.md](AUDIO_OBSERVATIONS.md). They add no hardware
or speech permission to the default text port.

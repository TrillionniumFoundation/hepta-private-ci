# Hepta HMI session attachment

Status: restored and checked in the saved project Codex cloud environment on
2026-10-23, not activated. The original `3741d927` candidate failed compilation
with two E0695 errors; the local audit branch corrects the event-loop labels.
The cloud branch now also contains whole-turn speech aggregation, the owner
coordinator and the correlated Pipecat JSONL media link. All 41 adapter tests
pass, including actual byte-stream and loopback socket regression cases. Peers,
owner authorization and model/device behavior in those tests are synthetic.
Agentd now registers an optional text caller under its real AuthBus owner;
its process qualification is described in `../hepta-agentd/HMI.md`. Actual
production-user activation, sourced-audio registration, models and physical
audio acceptance remain outstanding. No credentials/grants are invented.
Exact commands, exit codes and retained failures are in the cloud workspace at
`/workspace/pipecat-hmi-audit-20261023/`; the companion Pipecat checkout contains
`rust/docs/HMI_CLOUD_AUDIT_20261023.md` with the complete acceptance boundaries.

`hmi::HmiConnectionV1` attaches an existing authenticated channel owner to an
exact App Server thread. It never creates a thread, conversation database, model
client, tool executor or grant issuer. The owner must obtain the exact endpoint,
home, version, agent/device generation and current permissions through the
existing Agentd/channel authority before constructing the binding. Matching
strings supplied by an untrusted client are not authentication.

The connection resumes the exact thread with `excludeTurns: true`, reestablishing
connection-scoped subscriptions without overriding its configuration/history.
Input uses Core's `thread/queue/reconcile`, canonical ordered-input digest and a
stable domain-separated client message identity. Persisted admission is not
external-tool exactly-once execution. Ambiguous effects remain with the existing
operations owner and its reconciliation protocol.

Cloneable requests and a sole event receiver permit local output retirement while
the admission RPC is pending. Cancellation retires the output epoch before any
RPC. A known queue row is deleted; a matching late user-item event causes an
exact `turn/interrupt` before any output is published. An interrupt request is
not a terminal receipt. Failed/unknown cancellation keeps its original request
identity; callers must reconcile it rather than mint another request.

The presentation boundary must call `requests.permits_output(scope)` immediately
before local submission. It checks principal, device and device generation,
organ and generation, logical session, utterance identity/sequence, connection,
turn and output epoch. Generated text is retained in bounded terminal summaries;
no event claims device playback or human attention. Stream gaps, lost connection,
unsupported approval requests and admission errors close presentation authority.

Reconnection fences old request handles and resumes the same thread. It does not
promise lossless restoration of deltas or replay audio. Use the original request
ID and input with `reconcileOnly` to learn its Core state. A fresh live admission
is needed to open another presentation gate.

## Owner operated JSONL entry point

Build and run in the configured project environment:

```sh
cd codex-rs
cargo run --locked -p codex-hepta-codex-adapter --example hmi_jsonl -- /absolute/owner-hmi-config.json
```

Example configuration, whose values must come from the existing owner:

```json
{
  "binding": {
    "principalId": "user:example",
    "deviceId": "device:example",
    "deviceGeneration": 1,
    "organId": "hmi:example",
    "organGeneration": 1,
    "logicalSessionId": "hmi-session:example",
    "threadId": "EXISTING_THREAD_ID",
    "appServerSessionId": "EXISTING_SESSION_ID",
    "codexHome": "/absolute/existing/agent/home",
    "appServerVersion": "EXACT_SERVER_VERSION"
  },
  "socketPath": "/absolute/existing/agent/app-server.sock"
}
```

Alternatively supply `websocketUrl` instead of `socketPath`; an existing bearer
credential is read from `HEPTA_HMI_AUTH_TOKEN` and is never printed. The owner is
responsible for authenticated transport and scope. No discovery or LAN probing
is performed.

Commands are one bounded JSON object per line:

```jsonl
{"type":"submit","generation":1,"sequence":1,"requestId":"utterance:one","text":"你好","mode":"allowIfAbsent"}
{"type":"interrupt","generation":1}
{"type":"reconnect"}
{"type":"submit","generation":1,"sequence":1,"requestId":"utterance:one","text":"你好","mode":"reconcileOnly"}
{"type":"stop"}
```

Successful admission, RPC failure and interrupt-request acknowledgements are
separate from `{scope,kind}` output events. `kind.type` is `turnStarted`,
`textDelta`, `textFinal` or `terminal`. Scope contains complete binding identity,
`utteranceId`, `utteranceSequence`, `connectionId`, `turnId` and `outputEpoch`.
Text deltas and per-item `textFinal` events may be displayed. For the initial
single-utterance media protocol, wait for the successful turn terminal and issue
`{"type":"takeSpeech","generation":1}`. It returns
`{"type":"mediaRequest","request":{"type":"speak","scope":...,"text":...}}`
once, aggregating the retained turn text in observed item order. Before a
successful terminal, after an earlier claim, or for failed/interrupted/unknown
turns, `request` is null. This is process-local output dedupe, not a delivery
receipt. Reconnection never replays it. Null turn/utterance identities cannot
authorize media.

The request caps UTF-8 text at 4096 bytes and media identity strings at 256 bytes,
matching the companion endpoint; control characters in identity are rejected.
Oversize or incompatible media identity returns `speechUnavailable` and retains
the complete text in the terminal snapshot. It never truncates later output
items or resubmits the user input/model/tool operation. The trusted owner must
still check its current device grant and `permits_output(scope)` immediately
before media submission; receiving a request alone grants no authority.

The companion Pipecat example accepts correlated
`{type:"turn",request_id,scope}` and `{type:"speak",request_id,scope,text}`.
`HmiJsonlMediaV1` implements those commands, exact-epoch retirement, source
verification, explicit retention release and joined capture revocation. Eight
pending commands and 64 KiB wire lines are hard bounds; request/ack deadlines,
malformed/foreign acknowledgements and abandoned requests fence the link.
A queued ack remains distinct from later submitted/unknown presentation. The
native decoder cannot assert device-observed playback. Terminal diagnostics
retain input, output, storage and cleanup failures/counters.

`HmiOwnerBridgeV1` supplies the bidirectional coordinator. Install it in the
existing owner with `HmiOwnerAuthorityV1` (its current grants),
`HmiOwnerObservationsV1` (its actual sourced-observation ingress/receipts) and
the owned media link. There are deliberately no default authority or observation
implementations. Reusing config strings, or a receipt deserialized from UI/media
JSON, cannot replace these ports. The read-only gateway/organ interface stays
read-only; Core remains the conversation/model/tool owner.

The owner continuously drives the sole Hepta event receiver and JSONL reader in
its joined task set while request futures run. Feed them to `route_output` and
`route_media_event`; retain every complete outcome. The concrete protocol-loop
test demonstrates this bounded reader/request pattern. The library starts no
detached task. Link failure requires the existing supervisor to close/join its
media process; asynchronous Rust cancellation cannot kill a stuck native library.

`source_transcript` carries exact PCM16LE 16 kHz mono bytes' digest, sample span,
stream scope, capture generation and sequence. The owned reader stamps its
connection incarnation. Before Core admission the coordinator validates scope,
verifies the controlled asset through the media process, obtains the existing
observation ingress's matching digest receipt, then rechecks live authority.
It retains the receipt even if revocation prevents subsequent Core admission.
`unbound_transcript` stays display-only. Source generation/sequence form a stable
request identity; repeats reconcile the same observation and Core queue entry
without creating another message or replaying media/tools. One input slot rejects
pressure immediately. A fresh capture generation can reset capture sequence
without resetting the logical Hepta utterance sequence.

Local stop acknowledgement precedes the remote interrupt. Native barge-in and
the owner echo share an exact monotonic floor; old readers/events cannot stop a
new connection. A local-stop error never suppresses the remote interrupt.
Permission revocation also closes capture. Failed/unknown presentation retains
its original scope and initiates retirement. None of these outcomes undoes
already-committed tool effects. Current production owner registration and live
authority/observation ports still need the actual deployment's owner hook and
configuration for audio. The optional Agentd text caller now uses its actual
`AgentdState`, live `TextTrust`, canonical signed ingress and original Core
client ID. It creates no audio authority or substitute observation receipt.

The example has an eight-command input channel, at most one submission task and
a 32-item nonblocking output queue. Output queue exhaustion fences the session.
The writer has one-second write/flush deadlines and its completion is monitored
by the control loop. Tokio runtime shutdown has a one-second bound because its
underlying OS stdio worker cannot be forcibly aborted; process supervision is
the final bound for OS-stuck I/O. This example does not claim a supervised device host.

## Required source qualification

From the repository root:

```sh
just test -p codex-hepta-codex-adapter hmi::tests
just fix -p codex-hepta-codex-adapter
just fmt
just bazel-lock-update
```

The original three loopback WebSocket tests cover exact-thread resume, streamed
Chinese text with failure preservation, same-request reconciliation, cancellation
before the admission acknowledgement and old-handle fencing across reconnect.
Their peers are synthetic protocol fixtures, not a real Agentd, provider or audio
device. An additional real Core `matrix_bridge_payload_binding_suite` test passed
against the App Server request processor, persistent queue and rollout, using a
synthetic model SSE response. It proves one persisted message and one model
request under repeated admission, not an authenticated production owner/audio
session. Actual permissions, models/device faults, latency/resource measurements
and neuron shadow qualification remain outstanding.
Two added socket regressions check whole-turn multi-item speech aggregation,
one-time claiming, generation/cancel fencing and explicit text/identity bounds
without losing terminal text. Their first fixture attempt omitted the protocol's
required `completedAtMs`; the failure is retained and the fixture now serializes
the actual `ItemCompletedNotification` type. No physical playback is claimed.

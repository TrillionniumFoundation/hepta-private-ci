# Hepta HMI session attachment

Status: source prepared, not activated. Cargo compilation, authored socket tests,
Clippy, formatting and Bazel lock regeneration have not run on this source.
The configured project Codex cloud environment is not currently accessible from
this session. No substitute runtime or physical audio acceptance is claimed.

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
Only `textFinal` should become an initial bounded synthesis request; deltas may be
displayed. Null turn/utterance identities cannot authorize media.

The companion Pipecat media example accepts `{type:"turn",scope}` and
`{type:"speak",scope,text}` using this owner-issued scope. Its
`unbound_transcript` is not a trusted command: the owner must bind audio asset
digest/range, principal/device authority and utterance identity before `submit`.
The two processes are not yet joined by an accepted production owner/multiplexer.

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

The three authored loopback WebSocket tests cover exact-thread resume, streamed
Chinese text with failure preservation, same-request reconciliation, cancellation
before the admission acknowledgement and old-handle fencing across reconnect.
Their peers are synthetic protocol fixtures, not a real Agentd, provider or audio
device. Real Core persistent-queue admission, authenticated owner wiring,
bidirectional media integration, permissions, actual models/device faults,
latency/resource measurements and neuron shadow qualification remain outstanding.

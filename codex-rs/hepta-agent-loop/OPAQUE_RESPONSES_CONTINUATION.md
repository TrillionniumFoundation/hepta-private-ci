# Opt-in private Responses continuation

This path closes a specific loss point in the HTTP text/function-tool profile:
`response.output_item.done.item` is captured as raw JSON before codex-api
deserializes it into `ResponseItem`. The original continuation owner can retain
that JSON, restore its already verified receipt, and place the exact completed
item JSON into a newly admitted request. The ordinary typed API remains the
default. The qualification probe is not switched to opaque mode by this patch.

## Original owners and dispatch

`ManagedResponsesClient::stream_admitted_opaque` consumes the same
`ManagedResponsesAttempt`, original policy lease, scoped authentication and
exact encoded-body observer as the existing typed method. The original lease
supervisor starts before validation or awaits. A legacy continuation owner is
rejected before a physical send unless it explicitly implements private opaque
retention. The adapter creates no credential store, grant, provider policy,
TaskFlow run or persistent continuation store.

`ResponsesContinuationOwner::retain_opaque` must durably retain the private raw
bytes and bind them to the supplied original turn/request. Only then can the
same policy and encoded terminal owners acknowledge the observed completion.
The policy response-item digest covers the raw item JSON values in opaque mode.
The original continuation receipt additionally binds the exact private bytes.

The qualification `ContinuationEvidence` implementation writes raw evidence
through its existing append-only, mode-0600 evidence owner, then records the raw
digest inside its v2 continuation receipt. This remains qualification evidence,
not a production inference authority or recovery service.

## Exact supported scope

- Exact JSON text of completed item envelopes, their items, and the completed
  terminal envelope is retained. Encrypted strings and fields unknown to the
  typed serializer are not reconstructed from visible text.
- This is not byte-for-byte SSE framing, HTTP header, network packet, websocket,
  or transient delta retention. The existing route, request-ID and turn-state
  owners continue to handle transport identity.
- The current native loop still accepts its bounded assistant-text, ordinary
  function-call, reasoning and compaction profile. Images, programmatic tool
  calls, custom/namespace/encrypted tool argument protocols and unknown item
  variants are not made executable by retaining their bytes.
- A completed item with a field lost by the typed projection is retained by the
  original owner but cannot produce native `ModelEvent::Completed` or raw replay
  permission. Explicit response-only completed status, empty output-text
  annotations/logprobs, and known optional-null fields are reviewed exceptions.
- Duplicate object keys, contradictory terminal status/error, incomplete item
  sets, terminal/item mismatch and bounded-buffer overflow fail closed.
- Unknown terminal metadata is retained without interpretation. An unsupported
  item variant or malformed stream can stop the existing typed adapter before
  a complete terminal is available; this remains unresolved/indeterminate.
  This patch does not claim durable recovery of every partial stream.

`RawResponsesInput` appends owner-supplied typed initial input and actual tool
results, plus supported raw prior continuations in their original order. The
ordinary request's `input` must be empty when this explicit raw input is used.
`encode_request` produces the exact final bytes for a **fresh original-owner
admission**, including initial context, tools, encrypted continuation and tool
results. `stream_request_single_attempt_captured` passes those bytes through the
same exact-body observer and single-transport-attempt session. It never uses the
generic Value API with provider-default retry behavior.

Restoration is parsing, not authentication. Before calling
`ResponseCapture::restore_private_evidence`, the original owner must verify the
stored digest and its full original binding. Receipt verification, turn fences,
request identity, input token accounting, tool-call IDs and FinalUse grants
remain the caller's existing contracts.

## Resource and privacy limits

Completed capture is opt-in and bounded by item count and retained JSON bytes.
It adds parsing and bounded copies; no performance result is claimed. Its bounds
start after the existing SSE decoder has produced an event, so it does not add
a transport download/event-size limit. Known transient deltas are not stored.
Captured objects intentionally implement neither `Debug` nor `Serialize`.
Private accessors contain sensitive provider data and must not be printed in
logs, summaries or public artifacts. Managed diagnostics remain redacted.

## Hard budget remains unsupported

The ordinary path adds no `max_output_tokens` field. A separate explicit
`stream_admitted_bounded_opaque` path requests the documented cap through the
same exact-body observer and single-attempt transport. It requires the same
owner to retain incomplete raw terminal/usage and the original reservation;
policy and encoded terminals remain Indeterminate, never Completed. The
`hepta-native-provider-cap-witness` binary qualifies only a concrete fresh
original-route request; ordinary short completion is not proof of enforcement.

Local reservations and elapsed-time cancellation do not prove the original
provider stopped generating or billing. The original policy has no distinct
incomplete-with-usage terminal, so the same owner keeps private usage and the
whole reservation, and attaches its receipt digest to Indeterminate. Public
Responses API documentation alone does not establish support by a separate
ChatGPT-auth backend. Primary A/B and complete hard-budget admission remain
closed. See `../hepta-agent-qualification/CAP_WITNESS.md`.

## Validation scope

New offline tests cover raw encrypted JSON round-trip, original SSE parsing,
unknown nested-field retention and execution rejection, duplicate keys, bounds,
terminal binding, raw request encoding and conflicting typed input. Owned
loopback HTTP fixtures check one physical send, exact-body observation, private
retention before both original terminal acknowledgements, unknown-field
completion rejection, and rejection of a legacy owner before any send.

These fixtures provide no production authority and make no real-provider or
agent-intelligence claim. Remote compilation, package tests and actual-provider
qualification must be recorded separately against the exact final source.

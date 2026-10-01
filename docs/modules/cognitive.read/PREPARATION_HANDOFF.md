# Owner-issued preparation handoff contract

Status: source implementation candidate. This contract closes the identity handoff
between existing learning and native owners. It does not establish training admission,
physical provider acceptance, target-host qualification, activation or release.

## Wire extension and compatibility

Agentd control schema version remains 2. The additive `cognitive_context_prepare`
method takes the same bounded `query` and `limit` as `cognitive_context`, and returns
`cognitive_context_prepared` with `snapshot` and optional `preparation`. The capability
`cognitive.context.prepare` major 1 advertises this extension. A context-using native
worker requires that capability; it must reject an older peer rather than silently
fall back to a read that loses its durable preparation identity.

The existing `CognitiveContextSnapshot` and legacy read response remain byte-identical.
The receipt is outside the snapshot: its `read_request_id`, `sequence`, `event_digest` and `chain_digest`
identify one append under the existing witnessed learning owner. The context digest
continues to hash only the exact serialized snapshot. Putting the receipt inside that
snapshot would change the digest after append and cannot satisfy this contract.

`preparation: null` means no learning sink was configured for that read. It does not
assert no exposure, justify retry, or create learning evidence. An installed sink that
cannot commit a witnessed preparation causes the read to fail, as before. Empty or
abstained context can have a preparation receipt but cannot be joined as an exposed
candidate. A preparation may survive a later publication fence rejection.

## Existing owner lookup and native persistence

The learning owner resolves an exact sequence/event/chain receipt through its replayed
record vector, recomputes the owner-issued identity from the owner binding, predecessor
chain, sequence and separately authenticated agent/generation/read-RPC namespace
material, then reacquires the
current independent witness and active assignment index. Wrong sequence, event, chain,
namespace, missing/inactive records and witness lag fail closed. A matching content
digest alone is insufficient. The trusted host separately authenticates its principal,
generation and independently pinned native request; the receipt is not a bearer grant.

The normal worker persists the separate optional receipt as `cognitive_preparation`
in the existing native dispatch event before physical `turn/start`. It never adds that
receipt to model-visible context. Exact request, context and modern dispatch checks
remain required when inspecting the join. The native delivery digest includes the
persisted receipt, so swapping preparations changes the evidence binding even if two
reads yielded identical context bytes.

Historical native entries omit the field and remain readable. Serializing `None`
omits the field, preserving their canonical event bytes and journal digest. Entries
with a receipt require the upgraded reader; a downgrade must reject those entries,
never discard the receipt or rewrite them as historical entries. Missing receipt on
an old entry means the ordinary owner-issued preparation join is unavailable.

## Evidence and remaining admission boundary

The join reads the existing owners without dispatching, adding a second event, or
granting training access. `NotSent`, `RejectedBeforeTurn`, `AcceptanceUnknown`,
`TurnAccepted` and `TerminalObserved` retain the distinctions in
[DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md). Unknown acceptance remains unknown after
reopen or cancellation; server refusal does not prove no transmission.

Later training admission must reacquire current memory, learning, consent/withdrawal
and outcome owners under its separate contract. Automatic ingestion, tokenizer/provider
boundary tests and signed product acceptance remain pending. Fixtures of the identity
handoff cannot replace independently observed physical execution.

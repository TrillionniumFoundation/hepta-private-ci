# intelligence.control compatibility and migration contract

Parent: [TECHNICAL.md](TECHNICAL.md). This document defines source and persisted
state compatibility; it does not authorize product activation.

## Public source compatibility

The canonical product path is the authenticated `ObjectiveStart` route with a
host-owned invocation provider and, when physically composed, one
`AgentdIntelligenceExecutionHostV1`. Compatibility/shadow entrypoints may remain
for migration but cannot advertise canonical capability or bypass currentness,
permission, lease, provider-entry or learning acknowledgement checks.

New public APIs must preserve the existing operation identity and effect-boundary
semantics. Renames require a deprecation window or an atomic update of every
tracked caller. Consumer compilation is part of the exact-head qualification.

### Exact tokenizer admission

Physical prompt preparation now requires a host-owned `ExactTokenizerV2`.
Callers migrate to `prepare_prompt_delivery_with_tokenizer_v1`,
`compile_prompt_registry_with_tokenizer_v2` or
`AgentdPromptPipelineOwner::compile_and_stage_with_tokenizer` and pass the exact
tokenizer for the admitted model profile. Its digest must match that profile;
serialization counts the complete source envelope, including its overhead,
against both the compiled budget and maximum context size. A sum of source
fragment token costs cannot replace this complete-payload count.

The registry path subsequently extracts developer fragments for staging. Its
source-envelope count does not include the final provider's model framing; the
host's final serializer must enforce that complete physical request budget
separately. The direct canonical prepared-delivery path retains the payload it
validates.

The previous no-tokenizer entrypoints retain their signatures for source
migration but reject preparation with `PromptPipelineErrorV1::MissingExactTokenizer`.
The registry and Agentd owner entrypoints preserve their existing `Pipeline` and
`Compilation` error wrappers. Callers must supply the tokenizer rather than
reinterpret this error as a fallback authorization. Historical receipts and
counts are not upgraded into current serialization proof by changing their
declared token count. Exact-head consumer compilation and prompt-budget tests
must run after migration; source presence alone grants no product acceptance.

Public registry compilation fields are compatibility views of a sealed owner
result. Validation retains the original payload serialization, admitted exercise,
compatible snapshot and aggregate identity. Rehashing substituted fields or
grafting a different valid same-registry compilation cannot change that lineage;
such changes fail with `Integrity` rather than alter staged developer fragments.

An individual Agentd `RunCancel` now reaches a bound native physical observer
without requiring process-health loss or embedding-wide cancellation. The
bridge is private and leaves public bindings, wire enums and journal schemas
unchanged. A terminal observed concurrently with cancellation retains its
physical status but cannot restore a successful execution boundary. Callers
must continue to require separate Agentd and learning closure receipts.
New intelligence terminal recovery preserves the journal's stop intent and
retained authority/usage. Existing cached terminal observations are returned
unchanged, preserving their digest and separate control-closure diagnostics.

## Durable compatibility

SQLite migrations are append-only and versioned. Existing semantic digests,
operation IDs, terminal evidence, outbox fences, attempt counts and tombstones
must remain readable after upgrade. A migration may not reinterpret
`Dispatching`, `Dispatched` or `Indeterminate` as safe-to-retry. Unknown enum or
schema values fail as corruption rather than falling back to a permissive state.

`DurableOperationClock` changes clock ownership, not the persisted timestamp
format. Values remain Unix milliseconds and rollback remains fail-closed.

Completed native message text supplements the retained live trace by item
identity; a terminal summary does not duplicate the corresponding streamed
message. Recovered `ThreadRead` output requires a complete `itemsView: full`
turn, and summary or unloaded views return reconciliation errors without
authorizing replay.
Duplicate recovered turn IDs are rejected before output projection. A physical
terminal that conflicts with the Agentd terminal phase remains pending
reconciliation and cannot produce an acknowledged Outcome.

## Upgrade procedure

1. Freeze an exact candidate and retain a backup plus its digest.
2. Run migrations and quick/invariant checks on an isolated copy.
3. Reopen old pending, leased, indeterminate and terminal fixtures.
4. Verify same-identity replay, stale-owner fencing, destination-first recovery
   and tombstone non-resurrection.
5. Execute source-head and synthetic-merge qualification with the final lockfile.
6. Roll forward only after independent acceptance; otherwise restore the intact
   backup and keep admission closed.

## Versioning policy

Wire and persisted schema changes require explicit version fields, migration
tests and a compatibility note here. Evidence and status schemas may advance
independently, but a verifier must reject an unknown schema rather than treating
it as a pass. Acceptance receipts bind their verifier and workflow SHA, so a
verifier change invalidates previous candidate acceptance.

The registry compilation/staging path counts its binary source envelope.
Agentd then extracts developer fragments, and the host serializer must validate
the final provider framing and complete physical request budget separately.
The direct canonical prepared-delivery path retains the exact payload it
validates. Neither path creates a model-specific live tokenizer implementation
or independently provisions an authorized production embedding.

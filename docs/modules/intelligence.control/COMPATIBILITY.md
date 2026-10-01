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

### Canonical Prompt Optimizer owner outputs

`EnumeratedPromptCandidatesV1`, `PricedPromptCandidatesV1` and
`SelectedPromptPortfolioV1` now contain private owner-produced original
snapshots. External struct literals and struct update syntax for these types no
longer compile. Callers obtain them through `enumerate_factors_v1`,
`price_factors_v1` and `select_portfolio_v1`; public fields remain readable and
outputs remain cloneable. Mutating a public field does not authorize the next
owner to consume that altered view. Pricing, selection and exercise reject drift
or a whole-output graft with `CanonicalPromptError::OwnerOutputDrift`.
The added error enum variant also requires source updates to exhaustive matches.
This is an intentional source compatibility tightening, not an additive-only
change.

Producer function signatures, protocol serialization and signed/persisted digest
bytes are unchanged. No public seal constructor or test-support admission API is
provided. The two tracked Intelligence and Agentd fixture callers now use the
real enumeration, signed pricing and graph-bound selection producers. Their
test-only KG dependencies add two workspace dependency edges to `Cargo.lock`;
they do not add a production owner or change authority. Consumer compilation
and owner regressions are required on the new candidate's own source identity.

### Physical prompt-runtime turn resolution

The private physical prompt extension now uses `OnceCell<ResolvedAttachment>`
to serialize preparation shared by context and provider-policy contributors.
Ready, None and Failed remain cached for the turn. Concurrent callers share one
completed result; cancellation before completion permits a waiting initializer
to retry without overlapping preparation. Failure is stored as a resolved value,
not converted into an automatic retry. The separate injection flag and physical
attempt/terminal lease retain their existing behavior.

This private implementation change and terminal-mapping type alias preserve
public function signatures, contributor interfaces, dependency features and
persisted/wire bytes. Exact-head extension package regressions and consumer
compilation remain required; a private cache refactor grants no new authority.

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

Fresh Decision evidence must bind the ledger candidate universe: sorted policy
actions plus exactly one intrinsic `abstain`, with at most 128 total entries.
Providers compute completeness count and both candidate digests for that same
universe before signing. Canonical/evaluation action bindings remain unchanged.
Existing action-only completeness evidence is rejected; it is not automatically
renewed or repaired. Persisted schema-V2 payloads retain their original candidate
IDs, completeness, signature and operation identity. Recovery never inserts an
abstain into historical bytes or re-signs them.

SQLite migrations are append-only and versioned. Existing semantic digests,
operation IDs, terminal evidence, outbox fences, attempt counts and tombstones
must remain readable after upgrade. A migration may not reinterpret
`Dispatching`, `Dispatched` or `Indeterminate` as safe-to-retry. Unknown enum or
schema values fail as corruption rather than falling back to a permissive state.

`DurableOperationClock` changes clock ownership, not the persisted timestamp
format. Values remain Unix milliseconds and rollback remains fail-closed.
Exact claims and pre-dispatch deferrals now honor that same clock and sample it
after writer admission. Existing timestamps and operation identities are not
rewritten to accommodate an older injected clock. The rollback floor also
includes timestamps from outboxes associated with active operations, so an
outbox-only recovery update cannot be bypassed; settled operations stay excluded.

`AgentdIntelligenceInvocationProviderV1::build_in_canonical_worker` is an additive
provided method, so existing custom providers remain source-compatible. The
built-in provider executes its actual factory inside the caller's supervised
worker for both canonical configuration paths; its standalone `build`, `new`
and `with_policy` behavior remains separate. A custom canonical implementation
must not detach actual factory work beyond that supervised lifetime.
The additive timeout accessor defaults to the existing thirty-second ingress
cap; the built-in provider preserves its shorter configured policy timeout.
The provided exit-grace accessor defaults to no additional factory policy. A
configured factory grace can shorten the runner fence, never disable or delay it.

Unix-socket RPC fixtures and the actual registry/anchored-authority profile
fixtures are registered only on Unix. This includes the Optimizer provenance
cases, Intelligence delivery/pipeline cases, the Agentd registry pipeline case,
and signed/anchored-profile integration and factory-containment cases. Mixed
Agentd memory-state, portable file-reopen and worker/Busy assertions remain
cross-platform, as do pure canonical identity and optimizer tests. The registry
and rollback owners reject non-Unix profile construction because a qualified
anchored-handle implementation is unavailable. Platform-specific fixture
registration does not establish whole-module Windows qualification, non-Unix
no-follow or production execution parity.
Bazel's client/adapter/Agentd
unit-test variants carry `test-support` only in `testonly` dependency graphs,
with shared concrete client types. Production libraries and binaries keep the
ordinary client without test witness constructors.

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

# memory.retrieval product admission

Status: source-composed contract; production qualification, activation, and release remain false.

## Purpose

The product admission boundary prevents a partial set of retrieval owners from being interpreted as a complete observation. It sits between owner batch generation and recall dynamics and requires:

- one immutable `GeneratedCandidateInputV1`;
- one explicit expected-owner policy;
- one `ValidatedCandidateSetV1`;
- one caller-owned `RecallWorkControlV1` with the existing absolute deadline;
- one typed completeness decision before recall is permitted.

A policy row is not merely an action for a batch that happens to arrive. It is the expected owner inventory for the selected product profile. If a row has no corresponding batch, admission treats that owner as `Unavailable` and executes `on_unavailable`. Omitting an owner can therefore never convert a partial observation into `Complete`.

## Completeness outcomes

`RetrievalCompletenessDecisionV1` has four outcomes:

- `Complete`: every expected owner is present and exhausted within its declared bound;
- `Degraded`: recall is permitted, but every incomplete owner and action is retained in the decision;
- `Abstain`: no recall packet is produced;
- `FailClosed`: admission returns an error and the caller cannot downgrade it.

Severity is monotonic: `FailClosed` dominates `Abstain`, which dominates `Degrade`.

## SQLite owner profile

The current Agentd path builds seven batches from one durable SQLite snapshot:

1. `CognitiveLexical`;
2. `CognitiveEntity`;
3. `CognitiveAssociative`;
4. `CognitiveTemporal`;
5. `KnowledgeGraphCausal`;
6. `KnowledgeGraphProcedural`;
7. `KnowledgeGraphContradiction`.

The profile applies these source-level rules:

- lexical, entity, associative, temporal, causal, and procedural capacity limits produce a typed degraded decision;
- contradiction-evidence truncation is fail-closed;
- every omitted or explicitly unavailable expected owner is fail-closed.

The SQLite adapter invokes `ValidatedCandidateSetV1::new` and `recall_product_with_engram_v1`; it no longer calls the controlled recall primitive directly. Agentd still owns the work control, capacity permit, absolute deadline, cancellation state, and late-result rejection.

## Vector publication admission

A durable vector publication binds tenant, writer fence, sequence, generation, exact predecessor, encoder release, immutable snapshot, withdrawal frontier, revocation frontier, withdrawal set, and active/withdrawn state into the publication digest.

- writer fence zero is invalid;
- a successor with a lower fence is stale even when its predecessor digest is exact;
- a newer fence may take over at the same immutable object and generation;
- encoder or index changes require a strict generation advance;
- withdrawal and revocation frontiers are monotonic;
- withdrawn record digests cannot be present in the snapshot or later removed from the withdrawal set;
- a withdrawn publication cannot serve queries or reactivate.

`DurableVectorPublicationPortV1` requires a durable fence acquisition operation plus compare-and-publish. A real implementation must persist the fence with its lease/epoch and reject any publication whose fence is not current.

## Claim boundary

These contracts do not establish a production encoder, durable vector backend, target-host performance, hard worker preemption, external frontier/revocation authority, independent acceptance, canary activation, or release approval. They make partial-source and stale-writer behavior explicit so those later qualifications cannot rely on an ambiguous API.

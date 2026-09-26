# memory.retrieval API reference

Status: source candidate. This reference does not grant activation or release authority.

## Trust boundary

`memory.retrieval` is a read-only deterministic decision component. It does not own memory persistence, model release, encoder deployment, clocks, network effects, or learning-ledger durability. Every externally generated candidate batch must be tied to an exact Lane C generation and a named owner receipt before recall.

## Core entry points

### Candidate generation

- `compile_cue`: creates a generation-bound `MemoryCueV1` from objective, approved-context, request, snapshot and cue-profile digests.
- `RetrievalGeneratorReceiptV1::new`: seals generator identity, generation vector, owner generation, candidate count and completeness.
- `GeneratedCandidateInputV1::new`: canonicalizes named generator batches and proves candidate/receipt count agreement.
- `generate_vector_batch_v1`: validates a sealed vector-index snapshot and query, applies model/generation/OOD bounds, deterministically ranks records and emits the `EncoderVector` batch.

### Recall

- `build_candidate_union`: canonicalizes per-record channel evidence.
- `recall`: applies policy admission, safety checks, score ordering and result limits.
- `settle_engram`: executes bounded recurrent HNMF dynamics.
- `recall_with_engram`: combines admitted retrieval evidence with HNMF support and returns a receipt.
- `observe_retrieval_assignment`: records enumerated, legal, selected and omitted identities without claiming causal identification.

## Product context capability

`CurrentMemoryRetrievalContext` supplies the exact current `RetrievalExecutionContextV1`. The Agentd-owned implementation is constructed with `<dyn CurrentMemoryRetrievalContext>::product(...)` and supports:

- `lifecycle_epoch()`
- `lease_expires_unix_ms()`
- `context_state_digest()`
- `rotate_context(expected_epoch, ...)`
- `renew_context(expected_epoch, ...)`
- `revoke_context(expected_epoch)`
- `<dyn CurrentMemoryRetrievalContext>::recover_product(...)`

All lifecycle mutations are epoch-fenced. Every `current()` call revalidates identity, lease, state digest and the full generation vector. Revocation and expiry fail closed.

## Invariants

1. Zero activation never creates support.
2. `minimum_activation` is strictly positive.
3. A zero-weight synapse is structurally present but semantically inert.
4. Confidence is activation-weighted.
5. OOD and contradiction decisions use only the policy-admitted set.
6. Contradiction identity binds proposition and polarity; two records on the same side are corroboration, not a contradiction.
7. Input order cannot change canonical unions, recall ordering or receipts.
8. Generator receipt count equals the emitted candidate count.
9. Vector candidates bind exact model and generation identities and retain owner-supplied OOD values.
10. Final text exposure remains subject to exact revision/content/source revalidation in Agentd.

## Errors

Validation errors are fail-closed and must not be converted into empty successful recall. Capacity exhaustion is represented by `LimitReached`; owner unavailability is represented by `Unavailable`; neither may be mislabeled as exhaustive enumeration.

## Compatibility

V1 public types remain available. Semantic corrections use versioned receipt domains where the digest meaning changed. Callers must not compare V1 and V2 digest domains as interchangeable identities.

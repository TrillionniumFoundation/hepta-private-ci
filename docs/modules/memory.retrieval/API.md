# memory.retrieval API reference

Status: implementation candidate, not an activation or release authorization. Read this together with [TECHNICAL.md](TECHNICAL.md), [POLICY_REFERENCE.md](POLICY_REFERENCE.md) and [OPERATIONS.md](OPERATIONS.md).

## Ownership and caller contract

The retrieval crate is a bounded, deterministic, read-only decision component. The canonical SQLite owner retains memory/index persistence; external owners retain model, encoder and policy provenance; the learning ledger owns assignment durability. No unkeyed receipt authenticates its issuer. Requests must not mint current generations, choose arbitrary product thresholds or acquire lifecycle write authority.

`compile_cue` binds objective, approved context, request, snapshot and cue-profile digests. `RetrievalGeneratorReceiptV1::new` records generator identity, generation vector, owner generation, count and completeness. `GeneratedCandidateInputV1::new` canonicalizes batches and checks count agreement. `build_candidate_union`, `recall`, `settle_engram` and `recall_with_engram` apply deterministic admission and bounded HNMF decisions. `observe_retrieval_assignment` records enumerated/legal/selected sets; completeness alone is not causal identifiability.

`generate_vector_batch_v1` operates on supplied, bounded fixed-point vectors with exact record/model/generation identities. It is not a text encoder, deployed index service, calibrated OOD model or proof of product composition.

## Product read and control capabilities

The trusted composition root calls:

```rust,ignore
let (reader, control) = <dyn CurrentMemoryRetrievalContext>::product_with_control(
    owner, body_generation, validated_context, lease_expires_unix_ms,
)?;
// Give request code only `reader`. Retain `control` in the protected owner.
```

`product(...)` returns only the reader and deliberately drops the control capability. The read trait retains legacy lifecycle mutation method names for source compatibility, but the product reader rejects `rotate_context`, `renew_context` and `revoke_context`. Real mutations use `ProductRetrievalContextControlV1::rotate`, `renew` and `revoke` with an expected epoch. Its internal provider field is private.

`acquire_context(owner, body_generation)` returns **one atomic observation**:

| Value | Meaning |
| --- | --- |
| `RetrievalExecutionContextV1` | Validated model/tokenizer/encoder/policy/engram/generation payload |
| `Digest32` lifecycle binding | Owner, body, epoch, lease, revoked disposition and payload commitment |
| `Option<u64>` lease deadline | Product wall-clock deadline; `None` is legacy compatibility, not durable-lease evidence |

The product provider acquires all three under one read lock. Do not assemble a request binding from separate `current()`, `lifecycle_epoch()` and `lease_expires_unix_ms()` reads. Separate accessors are diagnostic, not an atomic transaction.

Agentd keeps the lifecycle binding in its read receipt, bounds execution by the provider lease, and reloads the binding before publication and final-use acceptance. Same-payload renewal or rotation invalidates previous read receipts. A compatibility provider's default `acquire_context` retains payload-only semantics; it must not be represented as a qualified product lifecycle.

## Lifecycle and recovery

The maximum in-process lease is 300,000 milliseconds. Both wall-clock expiry and a monotonic deadline are enforced. Wall-clock regression relative to acquisition fails closed. Expiry cannot be repaired by renewing the expired object. Rotation and renewal increment the epoch with checked arithmetic. Rotation rejects a regressing authority epoch. Revocation is terminal, clears the payload, sets lease to zero, and accepts an exact retry of the completed revocation.

`ProductRetrievalContextSnapshotV1::validate` checks structure, context and hash. This is **not** a freshness proof. Historical `recover_product(...)` therefore rejects recovery. `recover_product_with_witness(snapshot, witness)` requires a `RetrievalRecoveryWitnessV1` supplied by the independently protected current owner and compares the exact latest epoch and state digest. The witness implementation must not read the same rollbackable snapshot it is checking.

The in-process provider does not implement durable checkpoint publication or an external registry. Cross-process anti-rollback/recovery is incomplete until those owners and their fault-injection tests are composed.

## Decision invariants and outstanding semantic boundary

Positive activation, bounded dynamics, inert zero-weight synapses, activation-weighted confidence, admitted-set safety checks, deterministic ordering and count agreement are intended invariants and have source tests. Test execution and qualification must be recorded for the exact source.

**The current legacy contradiction wrapper still infers polarity from retrieval channels.** Its `ContradictionEvidenceV1` accessor is not owner-issued proposition/polarity evidence. In particular, merging channel sets must not be confused with merging logical assertions. Removing this inference and carrying explicit owner evidence through candidate, union, canonical digest and selection is still an activation blocker; the presence of an accessor or a same-side fixture does not close it.

## Errors, completeness and evidence

Validation errors must not become successful empty recall. `LimitReached` and unavailable generators do not prove exhaustive enumeration. Only policy-admitted evidence may influence decision safety, but malformed or over-capacity raw input still requires bounded validation before filtering.

Assignment, prepared response, published response, native-started attachment and actual model consumption are distinct events. A successful ledger append or `context_exposed` field is not independent proof of final consumption. Consumers must verify the exact receipt and actual-use evidence.

## Compatibility

No registered wire ID or authority is added here. Product lifecycle state uses the `hepta.agentd.product-retrieval-context.v2` digest domain. Old lifecycle digests are not interchangeable with new bindings. Legacy reader implementations retain a compatibility default; product deployments must explicitly qualify their override. The old self-hash recovery factory now fails closed intentionally.

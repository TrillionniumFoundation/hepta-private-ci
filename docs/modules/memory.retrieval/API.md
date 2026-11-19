# memory.retrieval API reference

The public retrieval surface is deterministic, bounded and read-only. It does not own memory content, knowledge facts, learning outcomes or release authority.

## Cue and generation identity

`MemoryCueV1` binds cue identity, objective, approved context, request, cue profile and an exact `CognitiveSnapshotKeyV1`. Every candidate, engram node and synapse must carry the same generation-vector digest. A mismatch is a hard error before ranking.

## Generator input

`RetrievalGeneratorReceiptV1` binds registered generator owner, generation, owner-generation digest, candidate count and source completeness. `candidate_count` equals the batch length. Missing positive-weight owners, unavailable owners, duplicate ranks, rank zero, over-capacity batches and cross-generation candidates fail closed.

`RetrievalChannelCandidateV1` binds exact record revision/digest, channel, normalized score, OOD value, support digest and optional typed contradiction evidence. Contradiction evidence identifies a proposition and polarity; sharing one polarity is corroboration, not a conflict.

## Recall policy

`RetrievalPolicyV1` declares channel weights/capacities, result bound, score floor, OOD ceiling, channel-coverage floor and contradiction behavior. Risk checks operate only on the policy-admitted set after channel capacity and score-floor admission. Zero-weight channels and zero-weight edges contribute no coverage, support, expansion or contradiction.

## HNMF

`EngramSnapshotV1` and `EngramDynamicsPolicyV1` are generation-bound. `minimum_activation` is strictly positive. Active nodes have positive activation and satisfy the threshold. Confidence is activation weighted. Structural and active-set ceilings are enforced before receipt publication.

## Outputs

`RecallPacketV1` records disposition, canonical selections, omissions, admitted channel count, optional engram receipt and digest. An abstention has no selections. A recalled packet contains only exact admitted records. Assignment observations distinguish enumerated, legal, selected and delivered candidates; delivery is recorded by the learning-ledger owner.

## Product provider

Agentd accepts a protected `CurrentMemoryRetrievalContext`. The product-owned provider binds owner/body generation, lease interval, monotonic revision, revocation, execution-context digest and a common model/encoder/tokenizer/policy/engram generation identity. Rotation and revocation are expected-revision operations; restart recovery validates the entire snapshot.

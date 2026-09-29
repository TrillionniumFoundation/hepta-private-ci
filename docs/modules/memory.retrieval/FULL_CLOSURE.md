# memory.retrieval full-closure contract

Status: source implementation and qualification contract. Production activation remains
fail-closed until every external evidence gate is independently accepted.

## Authority

The single product-composition authority is
`qualification/memory-retrieval/product-composition.json`. Product code, CI, operators,
and reviewers must not infer a second composition from environment defaults or prose.

The manifest binds the chunking profile, encoder state and identity, embedding dimensions
and normalization, quantization schema, index schema/version, publisher and durable-store
state, tenant/principal binding, transport, endpoint, mTLS profile, scopes, consumer, and
policy generation. Missing production identities are represented as explicit
`not-established`/`null` values. They are blockers, never wildcards.

## One execution identity

Every stage carries one `execution_identity_v1` with these exact fields: tenant,
principal, request, query digest, policy generation, encoder identity, snapshot identity,
and decision identity.

The required ordered lifecycle is:

```text
prepare
→ durable_publish
→ restart_recover
→ query
→ decision
→ native_consume
→ downstream_effect
→ acknowledgement
```

A receipt for an earlier stage does not prove a later stage. A function-call observation
does not prove durable publication, native consumption, downstream effect, or
acknowledgement. Any identity mismatch is terminal for that attempt.

## Strong lifecycle types

`codex-rs/hepta-memory-retrieval/src/lifecycle.rs` exposes separate types for
`ValidatedRequestV1`, `TenantBoundExecutionV1`, `SealedSnapshotV1`,
`QualifiedDecisionV1`, `PublishedRetrievalV1`, `ConsumedRetrievalV1`,
`AcknowledgedRetrievalV1`, and `QuarantinedUnknownOutcomeV1`.

Transitions consume the preceding value. Product adapters therefore cannot accidentally
treat a validated request as a published or acknowledged retrieval.

`DurableDecisionPortV1` is the only persistence boundary defined by the retrieval core.
A production implementation must provide writer fencing, compare-and-swap frontier
advancement, atomic append, load/replay, unknown-outcome quarantine, replay-integrity
verification, and retention. The core intentionally does not bless an in-memory store as
a production implementation.

## Quality and performance evidence

`quality-performance-policy.json` enumerates the mandatory cases and metrics. Every case
requires at least 100 samples on a named target host and must bind exact source, tree,
binary, policy, encoder, snapshot, tenant, and risk stratum. The matrix includes CJK and
multilingual input, code/path input, long and empty queries, stale and contradictory
sources, adversarial near-duplicates, cross-tenant isolation, float32/int16/int8
comparison, and ANN/full-scan comparison.

No threshold is inferred from the source tree. Approved SLO thresholds and the immutable
raw measurements are external evidence.

## Production qualification

`production-qualification.json` contains the ten conjunctive release gates. The release
flag must equal the conjunction of evidence-backed gates. Missing evidence keeps all
production, execution, acceptance, activation, and release claims false.

The validator `scripts/validate_memory_retrieval_closure.py` rejects lifecycle-stage drift,
split identities, production enablement with an unqualified encoder/index/security
boundary, missing quality cases or metrics, release claims without all ten evidence-bearing
gates, missing direct tests for `build_candidate_union` or `recall`, and malformed static
source observation.

The static implementation map records the exact parent observed before a closure commit.
The generated runtime qualification manifest must bind the resulting exact head and tree.
Neither artifact is a substitute for the other.

## Promotion order

1. Close source-head, current-main, and ordered-parent synthetic-merge qualification.
2. Qualify a real encoder, durable index publisher/store, and protected native consumer.
3. Produce restart/recovery and full lifecycle receipts under one execution identity.
4. Execute and independently accept the quality/performance matrix.
5. Satisfy every external production gate, run canary, and rehearse rollback.

Until step 5 is complete, activation stays `compatibility` and Vector remains
non-production.

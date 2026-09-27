# cognitive.types compatibility migration

This document describes type and codec migration only. It does not change repository permissions, runtime capabilities, deployment state or release status.

## Sequence

1. Register the current local type and its canonical schema.
2. Compile the consuming crate against the closed schema registry.
3. Produce legacy and canonical projections from the same immutable snapshot.
4. Compare their semantic digests as matched, mismatched, legacy-only or canonical-only.
5. Require exact equality plus the consumer-specific acceptance check.
6. Switch one consumer at a time and retain the documented fallback.
7. Observe mismatch counters through the declared observation window.
8. Retire duplicate wire types only after no current call site depends on them.

## Registered consumers

| Consumer | Maintainer | Current local surface | Canonical boundary | Acceptance check |
|---|---|---|---|---|
| `cognitive.read` | `cognitive-platform/read` | `MemoryRecord`, `CognitiveSnapshot` | memory event, cross-modal binding and forget receipt inputs | `cognitive-read-canonical-v1-zero-mismatch-exact-head` |
| `cognitive.store` | `cognitive-platform/store` | Lane C admission/write types and compatibility receipt | memory event input and strong receipt output | `cognitive-store-authenticated-canonical-v1-writer` |
| `memory.retrieval` | `memory-platform/retrieval` | generation-bound cue/packet | canonical cue input and recall output | `memory-retrieval-canonical-v1-recall-equivalence` |
| `compact.engine` | `memory-platform/compact` | record/checkpoint types | event and forget inputs | `compact-engine-canonical-v1-reconstruction-proof` |
| `intelligence.control` | `intelligence-platform/control` | cognitive snapshot | recall and outcome inputs | `intelligence-control-canonical-v1-policy-equivalence` |

The executable registry in `src/consumer.rs` is the source of truth for these strings.

## Store adapter

`CanonicalCognitiveStoreV1Ext::append_admitted_canonical` reuses the existing checked store operation, converts its compatibility receipt into the fully bound canonical receipt, verifies a closed-registry round trip and emits a semantic comparison receipt. It does not create an additional state store.

## Decoder behavior

A canonical decoder checks the closed registry before typed decode, rejects unknown schema/version/contract combinations, enforces the declared input/output direction and returns `Validated<T>` only after all current validation succeeds.

## Measurements

Each consumer has a unique mismatch counter. Supporting measurements cover decode rejection by code, legacy-only and canonical-only counts, exact matches, mismatches, fallback use, schema/version rejection and maximum observed payload bytes. Measurements contain no raw cognitive payloads.

## Fallback

Fallback disables the canonical call site while retaining existing records, canonical receipts, comparison evidence and historical compatibility. It never rewrites stored digests.

## Current state

The branch contains schema bindings for all five consumers and a real canonical adapter for `cognitive.store`. Compile-contract tests cover all five consumers. The remaining application call-site switches are not reported as complete until exact call-site evidence exists.

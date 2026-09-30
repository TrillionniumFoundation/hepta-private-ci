# cognitive.types performance and engineering closure

**Date:** 2026-09-30  
**Status:** source implemented; immutable-candidate qualification pending

This note records the source boundary for the performance and engineering work requested after the module review. It is not a production, activation, compatibility-retirement, canary, release, or independent-acceptance claim. Only exact-head and deterministic synthetic-merge receipts may change those states.

## Request-scoped canonical payload reuse

`ValidatedCanonicalPayload<T>` owns exactly one type-validated value, one canonical payload byte buffer, and the frozen and schema-bound digest identities derived from that same buffer.

The representation is deliberately request-scoped:

- it does not implement `Clone`;
- it contains no owner-currentness, source-freshness, revocation, authorization, promotion, activation, or release conclusion;
- it does not use a global or process-wide mutable cache;
- prepared consumer bindings reuse only the payload bytes and digest generated for the current value;
- final-use code must still obtain and revalidate the real current owner binding.

The bounded serialization preflight remains intentional. It protects public `CognitiveContractV1` implementations from materializing an unbounded `serde_json::Value`. The optimization removes repeated canonicalization and digest construction after that safe preparation boundary; it does not weaken the resource bound to save one defensive traversal.

Strict wire decoding still parses, validates, canonical re-encodes, and compares the accepted envelope. That work is the canonicality proof and is not replaced by cached authority. Once the proof succeeds, downstream encode and digest users share the retained exact payload slice.

## Attributable fuzz campaigns

The aggregate decoder target remains for compatibility, but qualification is split into five independently named campaigns:

1. `hnmf_base`
2. `hnmf_learning`
3. `shared_experience_v2`
4. `consumer_handoff`
5. `canonical_json_grammar`

Each campaign has an independent deterministic seed corpus and receipt. The runner records exact source commit and tree, command, toolchain, campaign class, duration, execution count, coverage and feature counters when emitted by libFuzzer, peak RSS, corpus digest, crash inventory and digest, bounded log digest, source cleanliness before and after execution, and receipt/checksum files.

The `consumer_handoff` campaign now exercises every registered consumer:

- `cognitive.read`
- `cognitive.store`
- `memory.retrieval`
- `compact.engine`
- `intelligence.control`

It covers every currently accepted consumer/payload family in the binding matrix. Accepted payloads must produce a matched typed handoff and must pass current-binding equality checks. A Python source-coverage guard prevents a future edit from silently dropping one of the five consumers or one of the three prepared binding families.

A smoke receipt is not a sustained-fuzz receipt. Sustained campaigns, target-host resource observations, and crash-free execution evidence remain qualification obligations.

## Unicode semantic identity

Wire V1 continues to preserve the caller's exact Unicode scalar sequence. It does not silently normalize NFC/NFD and therefore does not claim logical identity.

The canonical consumer identity registry makes each owner decision explicit. All five current consumers select `StableIdAsciiV1`, disallow free text as an identity key, and name the same owner as the canonical consumer registry. `validate_consumer_semantic_identity_v1` checks both registries before producing a `ContractIdV1`.

The closed-registry tests require:

- exactly one identity-policy row for every `CanonicalConsumerV1`;
- no duplicate consumer rows;
- exact consumer-name and owner agreement with the canonical migration registry;
- ASCII-bounded stable identifiers for current product consumers;
- rejection of composed/decomposed accent variants, Cyrillic confusables, and whitespace-bearing identity strings.

Owner-normalized and reject-confusable policies remain fail-closed in this generic crate. A real owner must supply its own evidence before either policy can be admitted.

## Remaining gates

The following remain false or pending until immutable remote evidence exists:

- exact-head Linux, Windows, and macOS package/all-target/strict-Clippy success;
- deterministic synthetic-merge success against the recorded base;
- sustained fuzz receipts for all five targets;
- selected-host allocation, latency, RSS, and load evidence;
- authenticated owner-epoch/currentness/revocation final-use proof for all five consumers;
- compatibility retirement and rollback rehearsal;
- Shared Experience V2 cross-host transport, longitudinal transfer, and full influence-removal evidence;
- independent acceptance, canary, activation, and release.

No local registry, prepared payload, typed digest, fuzz result, or document may be interpreted as granting those states.

# memory.retrieval API and trust boundaries

Status: source candidate; Rust execution, independent acceptance and production activation are separate gates. Read this with `TECHNICAL.md`, `IMPLEMENTATION_MAP.json`, `POLICY_REFERENCE.md`, `ROLLOUT_POLICY.md`, `ADR/0001-semantic-admission.md`, `ADR/0003-signed-lifecycle-delivery.md`, `ADR/0004-protected-rollout-and-shadow-budgets.md`, `PROCESS_BOOTSTRAP.md` and `E2E_MEASUREMENT.md`.

## Owner boundaries

`codex-hepta-memory-retrieval` is a deterministic read-only decision component. `codex-hepta-memory` owns content, SQLite indexes, revisions, citations and authoritative read cuts. `learning.ledger` owns durable assignment records. Agentd owns context delivery and revalidates the current owner state. A digest or public Rust struct is not an authority credential.

## Entry points

| API | Required input | Result and failure contract |
| --- | --- | --- |
| `compile_cue` | Nonzero objective/context/request/profile digests and a valid snapshot key | A cue bound to the complete Lane C generation vector; malformed identity is an error, not an empty recall. |
| `build_candidate_union_from_generated` | Owner-generated batches, counts, completeness and the bound policy | Deterministic union with exact generation/count validation. `LimitReached` is not exhaustive evidence. |
| `recall_generated_with_engram` | Cue, policy, generated input, immutable graph and dynamics policy | Bounded recall plus receipts. OOD/conflict/coverage decisions use the policy-admitted view; input accounting retains the observed union. |
| `observe_retrieval_assignment` | Matching cue, policy, generation-bound input and recall | Enumerated/legal/selected identities. Deterministic propensity is not evidence of counterfactual overlap. |
| `execute_owner_observation` | SQLite observation and coherent read cut plus current execution context | Owner adaptation followed by recall and assignment. A changed cut, revision or policy is rejected. |
| `LeasedMemoryRetrievalProviderV1::install` | Signed current publication for the configured Agent/body | Validates context/signature/lease and independent challenged frontier before installation. Identical reinstall does not renew the monotonic lease. |
| `LeasedMemoryRetrievalProviderV1::current` | Exact Agent ID and launched body generation | Compatibility payload accessor delegating to atomic acquisition; verifies currentness and rejects revocation/rollback/expiry. |
| `CurrentMemoryRetrievalContext::acquire_context` | Exact Agent/body from trusted host composition | Atomically returns context, lifecycle digest and optional absolute lease. The signed provider returns its publication digest and signed deadline under one mutex. The legacy default is payload-only with no product lease; it is not signed evidence. |
| `CurrentMemoryRetrievalContext` rollout methods | Host-captured canary policy version, ppm threshold, nonzero salt and shadow structural ceilings | These values are host policy, not request fields. The runtime wrapper binds them into final-use identity and rejects invalid policy. |
| `LeasedMemoryRetrievalProviderV1::from_loopback_frontier` | Protected endpoint, context/frontier public-key pins and time bounds | Constructs the real bounded client; does not create the remote owner or authority keys. |
| `LeasedMemoryRetrievalProviderV1::load_process_bootstrap` | Protected canonical descriptor path, independently approved raw-byte SHA-256 pin and launched Agent identity | Strict bounded v1/v2 descriptor, publication and context decoding followed by signature and fresh frontier checks. Returns a current-context provider that rereads signed publications; malformed, stale or unavailable input fails closed. |

`read_with_retrieval_context_and_learning` is the named Agentd caller, not a public application API. It binds lifecycle and host mode, bounds the operation deadline by the signed lease, and revalidates after ledger append and awaited final-use ranking. Same-payload publication renewal invalidates the old read. Published context and ledger preparation are not proof of native turn/start attachment or successful downstream use.

The runtime has explicit compatibility, shadow, canary and required routing. Shadow observes but does not publish HNMF selections as exposure; only the actual HNMF-delivered subset is attributed to treatment. Bootstrap v1 retains its historical fixed cohort. Bootstrap v2 requires a complete pinned rollout policy and separate non-delivery candidate/node/synapse/step ceilings. These ceilings are structural admission only, not CPU, RSS, allocation, wall-time or cancellation isolation. Mode and rollout policy are documented in `ROLLOUT_POLICY.md` and `CANARY_AND_ROLLBACK.md`; native process and host qualification remain required.

## Version and semantic migration

`ContradictionEvidenceV2` replaces opaque contradiction-group values in this candidate's generation-bound Rust structures. Its fields are `proposition_digest`, `generation_vector_digest` and `polarity`. The legacy field names ending in `_digest` are retained only for source migration; their values are no longer bare `Digest32`. Rebuild all consumers together. Do not decode old serialized values as the new structure or invent missing polarity. The proposition digest must bind the owner's canonical subject, predicate/object and applicable temporal qualifiers; the generation vector supplies scope/purpose binding.

`Affirmed` and `Denied` on the same proposition/generation conflict. `ConflictReported` is neither side. A SQLite record describing a contradiction must not be relabelled as a denied proposition. The canonical cognitive recall adapter remains a shadow migration surface, not a replacement product wire contract.

The bootstrap JSON schemas are explicit process-input formats, not changes to the canonical cognitive recall wire. Version 1 cannot carry version 2 rollout fields. Version 2 requires every rollout/budget field and has no per-field fallback. Native constructors still validate all decoded values. The SLO sample/receipt format moves to v2 to require actual source-tree binding; historical v1 measurements must not be relabelled with current source identities.

## Errors, empty results and authority

Malformed or stale input returns an error. A policy decision to abstain returns an explicit disposition and no selections. An empty result is not proof of exhaustive absence unless every required generator has authoritative `Exhausted` completeness. Callers must preserve these distinctions. Only the host's verified composition establishes batch provenance; checksum recomputation alone does not.

All collections and work limits are checked before use. Downstream rankers may reorder admitted identities but may not add records. Every delivered record requires current revision/content/source revalidation. Source declarations, test fixtures and successful local validators grant no activation or release authority.

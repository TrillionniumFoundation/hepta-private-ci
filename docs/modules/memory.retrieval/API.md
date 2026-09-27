# memory.retrieval API and trust boundaries

Status: source candidate; Rust execution, independent acceptance and production activation are separate gates. Read this with `TECHNICAL.md`, `IMPLEMENTATION_MAP.json` and `ADR/0001-semantic-admission.md`.

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
| `LeasedMemoryRetrievalProviderV1::current` | Exact Agent ID and launched body generation | Re-observes the frontier, verifies signature/currentness, rejects revocation/rollback/expiry, returns the frozen context. |
| `LeasedMemoryRetrievalProviderV1::from_loopback_frontier` | Protected endpoint, context/frontier public-key pins and time bounds | Constructs the real bounded client; does not create the remote owner or authority keys. |

`read_with_retrieval_context_and_learning` is the named Agentd caller, not a public application API. It records the delivered subset separately from the selected set. Published context is not proof of native turn/start attachment or successful downstream use.

## Version and semantic migration

`ContradictionEvidenceV2` replaces opaque contradiction-group values in this candidate's generation-bound Rust structures. Its fields are `proposition_digest`, `generation_vector_digest` and `polarity`. The legacy field names ending in `_digest` are retained only for source migration; their values are no longer bare `Digest32`. Rebuild all consumers together. Do not decode old serialized values as the new structure or invent missing polarity. The proposition digest must bind the owner's canonical subject, predicate/object and applicable temporal qualifiers; the generation vector supplies scope/purpose binding.

`Affirmed` and `Denied` on the same proposition/generation conflict. `ConflictReported` is neither side. A SQLite record describing a contradiction must not be relabelled as a denied proposition. The canonical cognitive recall adapter remains a shadow migration surface, not a replacement product wire contract.

## Errors, empty results and authority

Malformed or stale input returns an error. A policy decision to abstain returns an explicit disposition and no selections. An empty result is not proof of exhaustive absence unless every required generator has authoritative `Exhausted` completeness. Callers must preserve these distinctions. Only the host's verified composition establishes batch provenance; checksum recomputation alone does not.

All collections and work limits are checked before use. Downstream rankers may reorder admitted identities but may not add records. Every delivered record requires current revision/content/source revalidation. Source declarations, test fixtures and successful local validators grant no activation or release authority.

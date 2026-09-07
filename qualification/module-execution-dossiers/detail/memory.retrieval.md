# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-retrieval`.
Packages: `MEM-2-RETRIEVAL`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compile_cue(objective, approved_context, snapshot) -> MemoryCueV1`; `retrieve(cue, channel_budgets) -> CandidateUnion`; `recall(candidates, engram_snapshot, policy) -> RecallPacketV1 | Abstain`. Channels are explicitly lexical, vector, entity, temporal, causal, procedural and contradiction support where implemented. Each returns scoped IDs, source revisions and a score/support receipt, not unrestricted source payload.

## 3. State records and transaction design

No source-fact writer. A rebuildable query/recall cache binds the full read snapshot key, cue digest, retrieval/encoder profile, source quotas and truncation policy. Engram/synapse generations are supplied as immutable projections. Candidate-set and propensity facts are appended only through learning.ledger's owner port.

## 4. Deterministic algorithm and scheduling

Run bounded channels in parallel; stable-union by exact event revision; deduplicate; apply source/modality quotas and deterministic pre-assignment truncation; expand only a bounded local engram graph; settle at most four steps; apply per-population competition; detect contradictions; calibrate recall/abstain; revalidate exact source support before returning. Vector closeness does not prove truth; incompatible facts are not averaged into a new fact.

## 5. Capacity and performance profile

Use HNMF reference ceilings: <=512 candidate events, <=4096 nodes, <=32768 synapses, <=4 settling steps and <=16 returned events, with <=64 active units per population. Report channel omissions, graph expansion, p99 latency and source revalidation cost; no full-store scan or central synchronous RPC.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- RET-01: channel completion order/permutation yields an identical canonical candidate union.
- RET-02: high-risk contradictory support forces abstention/slow path.
- RET-03: revoked/stale source after ranking cannot be attached to a model request.
- RET-04: no-intervention, lexical-only, no-recurrence and no-inhibition baselines measure independent utility and resource cost.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 first changes a bounded read-only ranking/recall decision. Keep complete legal candidates and assignment propensities for causal evaluation. Rollback restores compatible retrieval/engram profiles and rebuilds caches under current tombstones, not old cached answers.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

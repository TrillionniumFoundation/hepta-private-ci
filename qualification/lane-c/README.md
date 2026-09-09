# Lane C cognitive, memory and context closure

This directory records the repository-controlled closure contract for `LANE-C-MEMORY`. It is a navigation and claim-boundary document; the native Rust sources and their tests remain authoritative for executable semantics.

## Canonical module set

Lane C contains exactly these modules:

1. `cognitive.types`
2. `cognitive.store`
3. `cognitive.read`
4. `memory.retrieval`
5. `memory.federation`
6. `knowledge.graph`
7. `compact.engine`
8. `prompt.registry`
9. `context.compiler`

No module may silently assume another owner's write authority. Every cross-module handoff carries a generation-bound identity, exact content or source digest, revocation posture and deny-all authority ceiling unless a separately governed runtime owner supplies a current capability.

## Shared identity contract

The Lane C implementation binds each operation to a coherent `LaneCGenerationVectorV1` and, where a cognitive snapshot is consumed, a `CognitiveSnapshotKeyV1`. Generation, snapshot, source, policy and revocation inputs are immutable for one admitted operation. Mixed generations, stale snapshots, missing predecessor evidence and zero identity digests reject before publication or downstream use.

The shared records in `codex-rs/hepta-cognitive-types/src/lane_c.rs` define bounded admission, federation, graph, compaction, prompt-registry and context-delivery values. These records prove local structural consistency only. They do not authenticate an external source, create production-writer authority or establish deployment.

## Module ownership and current closure

### `cognitive.types`

Owns stable bounded records, generation vectors, snapshot keys and typed Lane C receipts. It performs deterministic validation and digest binding without storage, network, model, selection, promotion or release authority.

### `cognitive.store`

Owns the append and read ledger boundary. V2 admission is generation-bound, predecessor-aware and fail-closed before mutation. The repository implementation proves local ledger transitions and state preservation under rejected admissions; it does not self-certify a production database deployment.

### `cognitive.read`

Owns authoritative snapshot acquisition and read projection. The authoritative provider boundary requires exact request/snapshot identity and rejects stale or inconsistent observations. A caller-supplied snapshot is not treated as authenticated merely because its internal digest is valid.

### `memory.retrieval`

Owns deterministic retrieval over an admitted snapshot generation. Query, candidate set, ordering and result receipts are bound to the same generation and snapshot identity. Retrieval cannot widen authority or silently substitute a newer or older snapshot.

### `memory.federation`

Owns bounded remote-observation admission. Federation V2 binds peer, scope, lease, snapshot and revocation observations and rejects identity drift, stale generations and unsupported authority. A remote response is evidence input, not an authorization decision.

### `knowledge.graph`

Owns generation-bound graph projection. Graph rebuilds bind input snapshot identity, ordered source edges and output generation. Partial, stale or mixed-source projections cannot be promoted to current truth.

### `compact.engine`

Owns compaction proof construction. Qualified compaction preserves required live records, tombstones, citations, predecessor relationships and deletion/revocation frontiers under an exact generation. A smaller payload alone is never proof of semantic preservation.

### `prompt.registry`

Owns admitted prompt factors and realizations. V2 snapshots bind factor lineage, admission state, revocation and registry generation. Registration does not grant model-call, context-attachment, selection or release authority.

### `context.compiler`

Owns deterministic compilation and delivery receipts over exact objective, snapshot, retrieval, prompt and policy inputs. Required groups, byte budgets and source bindings reject closed when unsatisfied. A compiled context is not proof that a provider consumed it or that an external action occurred.

## Failure and recovery invariants

- Rejected admission leaves owner state unchanged.
- A stale generation never advances a current owner.
- Missing, zero or mismatched digests reject before mutation or publication.
- Revoked or tombstoned content cannot re-enter retrieval, graph, prompt or context outputs through replay, compaction or federation.
- Recovery reuses stable operation identities only when the complete semantic request digest is equal.
- An observation after an uncertain external boundary remains indeterminate until the responsible terminal observer settles it.
- Rollback creates a new generation and revalidates current revocation and deletion frontiers; it does not restore expired authority or deleted content.

## Repository verification

The branch-level source suite covers the new generation-bound types and each owner implementation through unit and hostile-path tests. The global native-source contract additionally checks that every canonical module's pinned blob is exactly 40 lowercase hexadecimal characters, equals the Git blob calculated from the committed bytes and still contains every declared exported identifier.

Run the repository-controlled checks from a committed, clean tree:

```sh
python3 qualification/module-execution-dossiers/implementation_contracts.py verify-repository
python3 scripts/hepta-readiness.py generate-status --check
python3 scripts/hepta-readiness.py verify
```

The exact-head and deterministic synthetic-merge GitHub workflows are authoritative for CI admission. Prior-head, dirty-tree, shallow-history and manually edited receipts are not transferable.

## Claim boundary

This Lane C package closes source-level generation binding, bounded owner semantics and repository-controlled traceability. It does not self-issue production activation, production database evidence, external peer trust, model/provider execution, independent semantic acceptance, operator acceptance, hardware safety, longitudinal efficacy, promotion, signing or release authority.

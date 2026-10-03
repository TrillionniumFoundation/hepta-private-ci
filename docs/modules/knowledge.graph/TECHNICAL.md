# knowledge.graph technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `knowledge.graph`

**Owner:** `knowledge-graph`

**Deputy:** `cognitive-platform`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-4-KG`

This stable document is the implementation guide for `knowledge.graph`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Build rebuildable knowledge and prompt-factor projections without mutating source facts.

The primary owner `knowledge-graph` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `cognitive-platform` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `projection`, state model `stateful_rebuildable` and architecture role `projection` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-kg`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-kg`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-kg/src/lib.rs](../../../codex-rs/hepta-kg/src/lib.rs); observed identifiers include `KnowledgeEdge`, `KnowledgeProjection`, `rebuild`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md) for the implemented subset and remaining product work.

The cognitive knowledge-graph product integration is cross-owner evidence rather than a second module root. `codex-rs/hepta-memory/src/cognitive_kg_store.rs` is the canonical cognitive-facts adapter and SQLite publication owner integration; `codex-rs/hepta-memory/src/cognitive_retrieval.rs` is the product read adapter; migration `0013_kg_generation_semantics.sql` persists the canonical generation/publication receipts. These adapters call `hepta-kg` V2 semantics instead of duplicating a second graph policy.

The prompt-factor projection is a second rebuildable source family, not a second graph kernel. `PromptRegistry::factor_graph_source_v1` is the only constructor of the sealed current owner view; `codex-rs/hepta-kg/src/prompt_factor.rs` maps that exact registry revision/source digest into `KnowledgeGenerationV2`; and `codex-rs/hepta-prompt-optimizer/src/graph.rs` is the generation-bound read consumer. The optimizer cannot construct or mutate the registry relation source.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `cognitive.store`
- `cognitive.types`
- `prompt.registry`

Authoritative write domains:

- `knowledge_graph_projection`
- `prompt_factor_graph_projection`

Explicitly denied capabilities:

- `source_fact_mutation`
- `prompt_registry_mutation`
- `production_writer_construction`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `source consumer`
- `generation builder`
- `cognitive SQLite canonical adapter` (cross-owner integration in `hepta-memory`)
- `prompt.registry sealed factor-relation source adapter`
- `atomic publication step`
- `digest-bound product query adapter`
- `generation-bound prompt.optimizer relation consumer`
- `rebuild and equivalence verifier`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Shared-experience and isolated-Agent integration target

Maintain rebuildable multi-source relations and contradiction groups with original revision support. A shared publication/copy never creates an independent fact-history writer. Corrections or revocation invalidate dependent projections; identical wording alone does not deduplicate distinct observations.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::knowledge_graph_projectionV1`
- `DomainRead::prompt_factor_graph_projectionV1`
- `ModulePort::knowledge.graph::memory.retrieval`

Consumed contracts:

- `DomainRead::knowledge_fact_ledgerV1`
- `DomainRead::memory_ledgerV1`
- `DomainRead::prompt_factor_lifecycleV1`
- `DomainRead::prompt_factor_registryV1`
- `DomainRead::prompt_realization_registryV1`
- `ModulePort::cognitive.store::knowledge.graph`
- `ModulePort::cognitive.types::knowledge.graph`
- `ModulePort::prompt.registry::knowledge.graph`
- `PromptFactorV1`

Critical protocol schemas:

- `PromptFactorV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

### Native developer API

| Operation | Inputs and result | Required invariant |
| --- | --- | --- |
| `build_complete_generation` | `Generation`, `KnowledgeProjectionInputV2` → `KnowledgeGenerationV2` | Complete source cut; nonzero source/vector/profile digests; unique node/edge/support identities; live support for every retained record. |
| `apply_incremental_delta` | Predecessor, next generation, `KnowledgeProjectionDeltaV2` → complete generation | Exact predecessor digest and next generation; bounded, unique removals/upserts; result uses the same canonicalization as a full build. |
| `publish_generation` | Optional predecessor, candidate → `KnowledgePublicationReceiptV2` | Initial generation is one; subsequent publication names the exact next generation and predecessor digest. The caller owns atomic durable selection. |
| `query_relations` | Generation, `KnowledgeRelationQueryV2` → `KnowledgeRelationResultV2` | Exact generation digest, unique bounded seeds/filters and positive edge limit. Returns canonical bidirectional one-hop adjacency, with an exact omitted-edge count; an empty relation filter selects all kinds. |
| `ValidatedKnowledgeGenerationV2::new` / `query_relations` | Owned generation → immutable validated view; query → the same relation result | `new` consumes and semantically validates the generation once. Only a shared read getter is exposed; every query still checks its generation digest, identities and bounds and computes the same request/result receipts through the shared query core. |
| `build_prompt_factor_projection_v1` | Generation, vector digest, sealed `PromptFactorGraphSourceV1` → `PromptFactorProjectionV1` | Registry owner supplies the admitted current source; graph source identity and revision remain bound to the projection. |
| `enumerate_factors_v1` / `price_factors_v1` | Registry owner → `EnumeratedPromptCandidatesV1`; sealed enumeration plus signed `PromptPricingEvidenceV2` → `PricedPromptCandidatesV1` | Each input carries its own private complete seal; enumeration objective must equal the current verifier objective. V2 evidence binds the complete candidate-set receipt and actual realization digest. Pricing privately retains signed admission proofs and their canonical payloads; public fields and recomputed public receipts cannot replace the owner-issued enumeration or verified pricing result. |
| `select_portfolio_v1` | Validated pricing, sealed `PromptFactorProjectionV1`, signed `PromptPairUtilityEvidenceV2` → selected portfolio | Exact owner revision/snapshot/source cut and generation vector; pair model and both actual realization bindings; complete input seals; current verifier objective and reverified admission proofs; lifetime capped by bound evidence and realizations. Graph truncation fails closed. Bare `KnowledgeGenerationV2` is not accepted at this public boundary. |

`valid_at_unix_seconds = None` requests structural adjacency. `Some(t)` additionally requires both endpoint nodes and the returned edge to have live support at `t`; support windows are inclusive at the lower bound and exclusive at the upper bound. Only visible edge supports are copied into a temporal result; expired supports are not cloned and then discarded. Query truncation preserves canonical edge order. A digest over an arbitrarily reordered generation does not establish a valid canonical generation. Distinct relation kinds and distinct source revisions remain distinct evidence.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `knowledge_graph_projection`
- `prompt_factor_graph_projection`

Read-only data dependencies:

- `knowledge_fact_ledger`
- `memory_ledger`
- `prompt_factor_lifecycle`
- `prompt_factor_registry`
- `prompt_realization_registry`

Ownership is deliberately split by layer. `knowledge.graph` is the semantic owner of projection identity, generation/publication digests and relation-query rules. The existing `cognitive.store` / `hepta-memory` owner remains the physical SQLite schema and transaction writer for the cognitive projection, while `prompt.registry` remains the source-fact owner for prompt factors and factor relations. No graph adapter may create a second durable source-of-truth store. Projection mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

For the cognitive knowledge projection, the existing `cognitive_1.sqlite3` owner remains the only durable store. The adapter derives canonical `KnowledgeGenerationV2` values from immutable/current cognitive facts, invokes `build_complete_generation`, validates predecessor-bound `publish_generation`, writes physical projection rows plus `kg_projection_generation_semantics`, and only then advances the selected generation in the same SQLite transaction. Reopen recomputes the physical output digest, canonical generation digest and predecessor-bound publication digest. Compact revision-fact generations introduced by migration `0014` reconstruct the projection from retained source revisions instead of copying every historical node/edge snapshot. Startup still verifies all retained fact-set digests: a scalar preflight rejects source/memory owner IDs above 128 UTF-8 bytes before rows are materialized, then 128-record keyset pages and streamed live-shape checks bound Rust-owned KG row/identifier materialization on the checked cut. SQLite internal page/sort work and total startup cost are not constant; total verification work remains proportional to retained history. Only current publication reconstruction is restricted to the current generation and its exact predecessor. Pre-`0011` legacy generations may remain readable history but cannot drive digest-bound graph expansion without a canonical V2 semantic receipt.

Canonical cognitive entity identity is `owner + scope + entity_key`; `entity_type` and `label` are shape fields, not identity fields. All simultaneously live supports for one canonical key must agree on those shape fields or the product mutation fails closed. A correction may change shape only after the predecessor support leaves the current active cut. A rename or alias that must coexist uses a distinct entity key plus an explicit owner-governed custom relation such as `alias_of`; the KG kernel does not silently merge display labels or infer aliases.

Current source and relation coverage is deliberately narrower than the kernel enum:

| Source boundary | Produced relation identity | Current consumer and limitation |
| --- | --- | --- |
| Cognitive revision facts | Stable `Custom` identity derived from the exact stored relation label | GraphOneHop and typed cognitive channels use the same owner-label mapping; labels such as `causes` do not automatically become the kernel's closed `Causes` variant. |
| Sealed prompt.registry factor source | `PromptComplements`, `PromptSubstitutes`, `PromptConflicts` | Both public prompt selectors consume the owner-produced sealed projection. |
| Canonical private algorithm fixtures | `PromptRequires`, `PromptDominates`, `PromptRedundant`, `PromptSupersedes` | Algorithms remain testable, but the current sealed registry source does not emit these four kinds; no product source composition is claimed. |
| Generic KG build/query API | All validated closed or custom kinds | Semantic digests and immutable admission do not authenticate an external fact source or adapter. |

For prompt factors, `prompt.registry` remains the fact/lifecycle owner. The durable owner registers governed complement/substitute/conflict relations through `register_factor_relation_final_use`, binding a signed final-use grant to the current registry snapshot, actor, scope and exact relation/evidence. It persists relation metadata in the existing registry store, includes it in the registry snapshot digest and emits a sealed current `PromptFactorGraphSourceV1` containing only currently admitted governed endpoints. `revoke_factor_relation_final_use` binds withdrawal to the current owner snapshot, original relation, actor, scope and reason digest, then durably records immutable withdrawal lineage and advances the revocation frontier. The original relation identity is terminally withdrawn and cannot be reused; replacement evidence uses a fresh relation identity. Reopen verifies withdrawal lineage, and the next owner source/projection excludes the withdrawn relation even when both factors remain admitted. `knowledge.graph` rebuilds that exact source into the same V2 generation type; factor revocation changes the owner source digest and removes relations whose endpoint is no longer admitted. No prompt-factor relation becomes a new source fact inside `knowledge.graph`.

## 7. Runtime, concurrency and transaction model

For the cognitive knowledge projection, `CognitiveStore::refresh_scope_projection_tx` is the durable mutation boundary. One SQLite transaction observes the exact current source cut, derives the canonical V2 generation, reconstructs the exact predecessor, validates `publish_generation`, persists physical rows and semantic receipts, and CAS-advances `kg_projection.generation`. The selected pointer therefore cannot name a generation whose canonical receipt was not durably inserted first.

The product GraphOneHop read path loads the persisted generation through `load_generation_query_cut_tx`, building its compact support-to-memory index in the same reconstruction when storage mode is `revision_facts_v1`. Both use one core and the same SQLite read transaction; the index reuses occurrence IDs from the already loaded edge rows instead of scanning the source cut a third time. Legacy storage retains the physical `kg_edges` lookup fallback. The generation-only `load_canonical_generation_tx` path uses that core without allocating the query index. Retrieval consumes the generation into an owned `ValidatedKnowledgeGenerationV2` for reuse within the transaction. This immutable view validates canonical semantics once, exposes only `as_generation(&self) -> &KnowledgeGenerationV2`, and delegates each query to the same core as the validating free `query_relations` function. Query generation digests, seed/filter identities, bounds, temporal visibility, truncation and request/result receipts remain checked or bound on every query. The transaction-local cache also builds the relation-kind inventory once. Each processed seed still requires its persisted `generation_sha256` to match the reconstructed V2 digest before an absent typed relation can skip an empty query. The cache grants no external source or adapter authentication, and does not change ordering, ranking, truncation or admission boundaries. SQL after query selection only maps kernel-selected support identities back to their physical memory occurrences. `apply_incremental_delta` is retained as an equivalence oracle/reference path; the current durable product writer deliberately rebuilds the bounded complete generation on each logical mutation.

Canonical reconstruction also uses pure source-cut-local memoization: equal node kinds reuse their stable hashes, an already checked canonical shape reuses its payload digest, and historical edge endpoints reuse node occurrence IDs from the selected revision cut. Every occurrence retains its independent source/revision support digest. These maps do not survive the transaction or replace shape, lineage or source validation.

The prompt path is `PromptRegistry::factor_graph_source_v1 -> build_prompt_factor_projection_v1 -> optimize_with_factor_graph`. The registry view is sealed outside the owner crate. The optimizer requires every candidate factor to exist in the complete generation and queries complements/substitutes/conflicts against the exact generation digest. `PromptConflicts` are hard co-selection exclusions; `PromptSubstitutes` are hard redundancy exclusions; `PromptComplements` are observed and receipt-bound but do not manufacture a numeric bonus because the relation record carries no calibrated marginal magnitude. Any positive complement utility must come from independently supported causal interaction evidence. The complete canonical query request and result digests are both bound into the graph portfolio receipt. Request bounds are checked before graph allocation. `PromptPortfolioReceipt` construction is restricted to the optimizer by a private output seal; its public `validate` checks the observable selections, decisions and accounting against that seal. `GraphBoundPromptPortfolioReceipt` also retains its original private binding seal and validates the inner portfolio: replacing it with another valid standalone portfolio or rewriting the graph/query digests and recomputing the public digest fails validation. These seals preserve the optimizer-produced output inside the typed API; they are not external authentication credentials. The optimizer remains read-only and `DENY_ALL`.

The separate canonical `enumerate_factors_v1 -> price_factors_v1 -> select_portfolio_v1` path privately seals the complete issued enumeration and pricing result, including actual realizations, row order, utility/accounting, identities and receipts. Pricing validates the enumeration; selection validates the pricing and accepts only a sealed `PromptFactorProjectionV1` whose owner revision, registry snapshot, source cut and generation vector match enumeration. Callers cannot omit owner relations with a relabeled bare graph or repair modified public inputs by recomputing public digests. The selected portfolio retains its private complete output seal; `exercise_v1` rejects mutation before revalidating the current owner snapshot. Relation-only withdrawal invalidates an already selected portfolio. These owner-produced types and private seals protect this public prompt boundary; the generic KG APIs still require trusted source adapters and do not authenticate arbitrary fact sources by digest equality.

The canonical entrypoints require versioned evaluator evidence from [canonical_evidence.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_evidence.rs). `PromptPricingEvidenceV2` binds `candidate_set_digest` to the enumeration's complete `receipt.receipt_digest` and `binding_digest` to the actual realization digest for its factor. `PromptPairUtilityEvidenceV2` adds the exact model-tuple digest and oriented left/right realization binding digests to the existing graph-generation, state and edge-validity bindings. The V2 signing functions use separate `pricing-evidence.v2` and `pair-utility-evidence.v2` domains. V1 evidence types and signing payloads remain unchanged for historical interpretation; the formal pricing and selection paths do not fall back to V1 authentication.

Pricing translates both confidence bounds by the same deterministic cost debit used for net utility: `net_bound = raw_bound + (net_utility - raw_utility)`. Checked Q32 arithmetic and range conversion reject overflow. This keeps raw and net estimates in their corresponding numeric domains while preserving the existing confidence admission rules.

Pricing and selection require the enumeration objective to equal the supplied current verifier's objective. The priced value privately retains at most 129 signed admission proofs: one completeness proof and up to 128 factor-pricing proofs, together with their canonical payloads, admission time and trust digest. Selection rejects time before pricing admission and re-verifies every retained proof at its current time under the supplied verifier; expired evidence, rotated trust and effective scheduled revocation fail closed. The selected `valid_until_unix_ms` is capped by the requested deadline and the shortest completeness, pricing, pair-evidence or selected-realization deadline. Verification at the last included millisecond (`valid_until_unix_ms - 1`, because the upper bound is exclusive) also rejects a requested lifetime crossing a scheduled revocation already known to that same trust snapshot. This is a lifetime constraint on the supplied current trust state, not a promise to detect future trust changes.

`exercise_v1` validates the selected seal, current registry owner state and expiry before producing typed `DENY_ALL` proposals. The selected output privately binds `selected_at_unix_ms`; a nonempty selection rejects exercise time before that timestamp as `RejectStale`. It does not take a fresh learning-evidence verifier and cannot detect an unknown subsequent ledger trust rotation. A proposal does not authorize the final effect: the effect boundary still requires fresh trust validation and its own final-use grant.

The two selectors apply different interaction contracts. `optimize_with_factor_graph` treats substitutes as hard redundancy exclusions and binds complements without a numeric bonus. Canonical `select_portfolio_v1` treats both substitutes and complements as pair-utility interactions requiring independently verified V2 evaluator evidence bound to graph/state/edge, model and both realizations; missing evidence fails closed. Neither selector manufactures utility from the relation label. The additional requires/dominates/redundant/supersedes semantics remain in the private algorithm until a sealed owner can produce them.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

The cognitive projection transaction has test-only process-crash rendezvous before the canonical semantic receipt and after the semantic receipt/physical rows but before current-generation CAS. The qualification child publishes an fsynced marker, is killed by its parent, and the reopened store must expose only the exact predecessor generation with no tentative source, memory revision, generation receipt or semantic receipt. This is a process-crash/SQLite-WAL test, not a physical power-loss claim. Independent `lane_c` cut-witness tests separately detect restoration of an older internally valid SQLite backup; the stronger descriptor-safe writer `open_with_recovery` contract remains owned by `cognitive.store` and is not implied by this module.

Ordinary publication reconstruction verifies the current generation plus its exact predecessor. Full historical publication-chain replay remains a qualification/forensic operation; the cognitive KG oracle walks every persisted semantic generation and reconstructs each predecessor-bound publication digest. This bounds publication-chain reconstruction, while ordinary startup still verifies all retained fact-set digests and therefore performs O(retained history) total work. Keyset pages and streamed shape verification bound verifier memory without dropping historical integrity checks.

Historical entity and relation fact validity intervals must equal the interval of their owning memory revision exactly. A narrowed subset is corruption, just as a widened interval is; the revision-fact source contract does not independently authorize changing those windows.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md) specifies this module's algorithm and pilot ceilings. The current durable writer deliberately performs one bounded complete-generation rebuild for each logical mutation; `apply_incremental_delta` remains the independent equivalence/reference path until measurements justify selecting it as the durable runtime algorithm.

| Boundary | Current admission ceiling |
| --- | --- |
| V2 semantic kernel | 65,536 nodes; 262,144 edges; 50,000 explicit supports per node or edge; 327,680 supports in one generation. |
| Cognitive SQLite scope | 10,000 memory heads; 10,000 physical node occurrences; 50,000 physical edge occurrences. |
| Cognitive retrieval channel | 32 candidates before fusion; the caller's final reference limit remains separate. |
| `optimize_with_factor_graph` | 4,096 candidates; 128 selected; requests the full 262,144-edge kernel ceiling and rejects omitted edges. |
| Canonical `select_portfolio_v1` | 128 candidates; 16 selected; 512 interaction edges; truncation fails closed. |

The pilot fixture's 4,096 node-support/32,768 edge-support occurrences and the target 512-reference output profile are measurement/design profiles, not additional native traversal or batch APIs. The free query function validates the complete generation for each call; an owned immutable `ValidatedKnowledgeGenerationV2` admits it once and reuses those semantics across queries through the shared core. Both paths still perform the same one-hop scan and per-request checks, so reducing the output limit does not remove graph-scan cost. Returned-edge allocation follows the requested bound rather than materializing the entire matching graph before truncation. The aggregate support ceiling is checked before canonicalization or digest allocation and exceeds the cognitive owner's maximum 60,000 node-plus-edge occurrences. Target-host memory/latency budgets remain required in addition to kernel admission ceilings.

[codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) is the PERF-LIBRARY qualification probe. Its default fixture performs 256 real `remember_with_kg` transactions with 16 entities and 128 relations each, reaching 4,096 physical node-support occurrences and 32,768 physical edge-support occurrences, then samples product retrieval/GraphOneHop and ordinary reopen. Those supports project to 16 canonical nodes and 128 canonical edges: this is a support-dense fixture, not evidence of query capacity at 4,096 unique canonical nodes. The full probe emits mutation/query/reopen p50/p95/p99, integer throughput, database/WAL bytes, RSS and Linux CPU ticks when it completes. The repository defines no host-independent millisecond threshold for PERF-LIBRARY, so such a receipt is measurement evidence only; target-host/release qualification must supply the actual acceptance budget before full-generation versus durable-incremental selection changes.

The local full-capacity attempt on 2026-10-01 completed the 256 writes in 1,676,162 ms, then its 30-minute watchdog terminated it during the query phase. It did not complete the full write/query/reopen qualification. The separately ignored `qualification_knowledge_graph_existing_read_capacity_receipt` accepts an explicit `HEPTA_KG_BENCH_READ_FLEET_ROOT` containing that existing 256-write fixture. It performs ordinary owner validation, verifies the exact current generation/source/physical counts, and measures 20 product queries plus 5 ordinary reopens without new writes. That historical run passed in 193.536 s; the [read-capacity receipt](../../../qualification/module-execution-dossiers/reports/knowledge.graph-read-capacity-2026-10-01.json) records query p50 5,482,285,356 ns and p95/p99 5,744,929,233 ns, and reopen p50 14,173,021,219 ns and p95/p99 15,982,671,923 ns. The accompanying local validation record identifies code commit `992c3a90fca45c4543db670514984c8ec8c8dc21`; this is not execution proof for the current second-round HEAD. These are measurements on the shared execution host using the unoptimized test profile (`debug = 0`, `opt-level = 0`), not target-host budget acceptance. There is no complete before/after comparison, so no speedup factor is claimed. The `hepta.knowledge-graph-read-capacity.v1` receipt cannot substitute for a passing full write-capacity test or establish performance of newly changed code.

The [second-round read-capacity receipt](../../../qualification/module-execution-dossiers/reports/knowledge.graph-read-capacity-2026-10-01-round2.json) measures committed KG/memory source `8b459faeaa2c772d56404425de4deeb07c46bc3c` on the same 256-write source cut: all recorded source, generation, publication and physical digests match the historical receipt. Its 20 queries record p50 3.508694118 s and p95/p99 4.107741552 s; its 5 ordinary reopens record p50 11.088318591 s and p95/p99 11.780440358 s. These are raw observations on the shared contended host with `debug = 0` and `opt-level = 0`, alongside the earlier query/reopen p50 observations of about 5.48/14.17 s. They do not establish a controlled speedup factor, target-host budget acceptance, passing full write capacity, or complete final-HEAD/synthetic-merge qualification; other prompt/doc changes were outside that measured source.

The first full-capacity attempt in the second round failed after 841.882 s during writes with database/disk full. The later complete retry passed 256 real writes, 20 product queries and 5 ordinary reopens in 1269.858 s excluding build time, as recorded by the [full-capacity wrapper](../../../qualification/module-execution-dossiers/reports/knowledge.graph-full-capacity-2026-10-01-round2.json). Total write time was 1,147,652,705,313 ns. The failed disk-full attempt and the earlier query-phase watchdog remain historical failures.

| Complete retry phase | p50 (ns) | p95 (ns) |
| --- | ---: | ---: |
| Mutation | 4,642,611,383 | 8,196,905,699 |
| Product query | 3,377,370,820 | 3,717,962,550 |
| Ordinary reopen | 10,804,119,826 | 11,428,328,621 |

The wrapper records component-code observation `be4004a11e374f49a5b0db2fa4e1dd87d318b11d`, tree `039ed37a41cf2981e4b9b1e42b635f1ba699d323`. The existing test binary ran while final formatting proceeded in parallel; the memory algorithm was unchanged. This is scoped component execution, not complete final-HEAD/synthetic-merge qualification. The raw full receipt exports no source-cut digests, so equality with the read-only fixture's semantic cut is not established. It retains the support-dense 16-canonical-node/128-canonical-edge fixture and the shared contended host's unoptimized profile (`debug = 0`, `opt-level = 0`); passing this complete local probe does not establish a controlled speedup, target-host budgets or module-wide production/acceptance flags.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Projection builder library over owner-approved facts. Publish only complete validated generations tied to an exact source cut; do not turn generated edges into source facts. Persistence, index service and route/GC ownership must be explicitly composed before claiming a durable graph deployment.

Current operating and state-format references:

- [codex-rs/hepta-kg/src/lib.rs](../../../codex-rs/hepta-kg/src/lib.rs).
- [codex-rs/hepta-kg/src/generation.rs](../../../codex-rs/hepta-kg/src/generation.rs).
- [codex-rs/hepta-memory/src/cognitive_kg_store.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store.rs) for the cognitive source adapter and same-transaction durable publication.
- [codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql](../../../codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql) for immutable semantic receipts and current-generation fencing.
- [codex-rs/hepta-memory/src/cognitive_retrieval.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval.rs) for the digest-bound product GraphOneHop consumer.
- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) for the durable cognitive owner contract.
- [codex-rs/hepta-kg/src/prompt_factor.rs](../../../codex-rs/hepta-kg/src/prompt_factor.rs) for the prompt.registry-to-KG adapter.
- [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs) for governed prompt-factor relation ownership and the sealed graph source.
- [codex-rs/hepta-prompt-optimizer/src/graph.rs](../../../codex-rs/hepta-prompt-optimizer/src/graph.rs) for the generation-bound real consumer.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-kg/src/generation_tests.rs](../../../codex-rs/hepta-kg/src/generation_tests.rs); cases cover full/incremental equivalence, predecessor-bound publication, support/tombstone behavior, custom relation identities and temporal visibility.
- [codex-rs/hepta-kg/src/validated_generation_tests.rs](../../../codex-rs/hepta-kg/src/validated_generation_tests.rs); immutable admission rejects malformed generations, and repeated queries match the complete free-function results and receipt bindings while preserving stale/duplicate/oversize request rejection.
- [codex-rs/hepta-kg/src/lib_tests.rs](../../../codex-rs/hepta-kg/src/lib_tests.rs); named case: `rebuild_is_canonical_and_authority_free`.
- [codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs); the canonical oracle drives the same source cut through full V2 rebuild, incremental V2 rebuild, SQLite materialization, reopen, query, correction and tombstone, compares physical/canonical digests plus visible query behavior, walks the complete persisted publication chain, and verifies the canonical entity shape-evolution contract.
- [codex-rs/hepta-memory/src/cognitive_store_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_tests.rs); reopen integrity includes fail-closed generation/publication receipt tamper cases plus the ignored child-process crash-window matrix.
- [codex-rs/hepta-memory/src/cognitive_intelligence_writer_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_intelligence_writer_tests.rs); `reopen_rejects_narrowed_historical_fact_validity_after_restoring_triggers` narrows old revision fact windows beyond the current/predecessor cut, restores the original trigger and requires ordinary reopen to reject them.
- [codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs); the ignored full PERF-LIBRARY probe builds the pilot fixture with 4,096 physical node supports and 32,768 physical edge supports over 16 canonical nodes and 128 canonical edges, and measures writes/queries/reopens. The separately ignored existing-fixture probe performs 20 queries and 5 reopens and emits an independent read-capacity receipt; completing it does not establish that the full probe passed.
- [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs); the named Agentd product profile exercises real App Server remember, restart/recall, correction and forget while checking persisted KG receipts and product-visible retrieval. The additional `qualification-cognitive-write` feature only attaches the qualification turn-witness seam; it is not the mutation authority.
- [codex-rs/hepta-prompt-registry/src/lib_tests.rs](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs), [codex-rs/hepta-prompt-registry/src/durable_relations_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_relations_tests.rs), [codex-rs/hepta-kg/src/prompt_factor_tests.rs](../../../codex-rs/hepta-kg/src/prompt_factor_tests.rs), [codex-rs/hepta-prompt-optimizer/src/graph_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/graph_tests.rs), and [codex-rs/hepta-prompt-optimizer/src/canonical_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_tests.rs) cover owner-bound relation admission and durable terminal withdrawal, stale-cut/corrupt-lineage rejection, revocation/rebuild, V2 projection/query, graph-conflict enforcement, private output/binding seals, and canonical selection/exercise against the owner source cut. These test identities do not establish authentication of arbitrary bare graphs.
- [codex-rs/hepta-prompt-optimizer/src/canonical_adversarial_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_adversarial_tests.rs) covers forged bare-graph replacement, enumeration/pricing mutation, objective mismatch, proof expiry/trust rotation/scheduled revocation and generator/evaluator independence.
- [codex-rs/hepta-prompt-optimizer/src/canonical_evidence_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_evidence_tests.rs) covers superseded-realization price replay with fresh completeness, pair-evidence replay across models/realizations in one owner cut, and net confidence translation including cost totals wider than Q32 with legal final bounds. These are source references until exact-candidate test receipts are recorded.

In `codex-rs`, run `just test -p codex-hepta-kg`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md) separately labels target acceptance designs.

The latest scoped local checks passed all-target strict Clippy with `-D warnings` for knowledge.graph, prompt.registry and prompt.optimizer. `just fix` completed for five scoped crates and formatting completed. The broader memory/Agentd scope still reports existing warnings; these local results do not establish complete final-HEAD/merge or workspace-wide warning-clean qualification.

CI exposed line wrapping in the newly registered test-only `codex-rs/hepta-agentd/src/runtime_executable.rs`; the correction is at `b3b14c25821896eda3c27aaade20196d93b24aee`, tree `b22babb0050f74e4b27d4ac6ef1518f38f98aee7`, with scoped `just fmt --base a89e97a1` passing. `856dbd4f5c` is the earlier formatting observation; capacity execution remains bound to `be4004a11e`, without renewing test, capacity or final-HEAD/merge qualification.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

The 2026-10-03 qualification wiring repair adds narrowly triggered exact-source and deterministic-merge execution with retained command/log hashes and mandatory nonzero test counts. The explicitly ignored crash-window test is selected separately in both lanes; the full 256-write/20-query/5-reopen PERF-LIBRARY measurement remains source-lane-only and uses a bounded, dedicated measurement profile. Required map, formatting, test or lint failures remain aggregate failures while later diagnostic commands retain their own outcomes. This is evidence collection, not a new native pass, host-latency acceptance, production qualification or activation claim. See [the bounded change record](../../../qualification/knowledge-graph/retained-commands-20261003.md).

The first retained run at `f3effae2` now proves the exact-source and merge kernel/owner suites and crash-window test, plus the source full-capacity workload. It retains one qualification-writer E2E failure in a legacy-storage evidence query and two private Memory argument-count lint failures. The [compact fixture follow-up](../../../qualification/knowledge-graph/compact-fixture-20261003.md) records exact artifact identities and repairs only that fixture query and private parameter grouping; its own native execution remains pending. Production-host custody and all acceptance flags remain unchanged.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-4-KG`

The bootstrap package is `MEM-4-KG`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `knowledge.graph`, the cognitive knowledge read path is product-composed. The default **Agentd** feature enables the cognitive-write configuration profile and fails startup closed when the cognitive owner store is unavailable; ordinary Codex/App Server binaries remain default-off. Actual production mutation tools still require the sealed, live-verified capability supplied by an independently recovered `AgentdProductionWriterHost`. The default feature does not provision that host. The explicit `qualification-cognitive-write` feature permits qualification store writes as well as the turn-witness seam; its remember/restart/correct/forget E2E is ignored in the default profile. Passing that feature test does not establish production-writer custody through the real daemon. The independently recovered capability through that daemon path remains a separate test and host-evidence gap.

The three selected real product E2E cases produced one pass for unavailable-store startup rejection and two failures while binding the Unix control socket with `EPERM`, before readiness. The positive remember/restart/correction/forget chain and server-isolation cases therefore have no passing execution result on this host. The full-capacity component probe's success does not close this product-environment blocker.

The prompt-factor graph source/projection/consumer path is now source-composed separately from the cognitive SQLite path: prompt.registry owns relation facts, knowledge.graph rebuilds them, and prompt.optimizer consumes the exact generation-bound relation view. This does not make prompt.registry durable or activated by implication, and it does not turn the optimizer into an authority source. Module-wide `productionImplementation` and `productExecutionProved` remain false until the current exact-head and deterministic synthetic-merge qualification gates are green; independent acceptance, activation and release remain separate external gates.

For `knowledge.graph`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-4-KG`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `knowledge-graph` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-kg/**`
- Development predecessors:
- `MEM-0-TYPES`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- Activation predecessors:
- `MEM-1-STORE`
- `PIM-1-PROMPT-FACTOR-REGISTRY`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `knowledge.graph` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `knowledge.graph` is implemented by work package `MEM-4-KG` in:

- `codex-rs/hepta-kg`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. The cross-owner cognitive integration additionally depends on the `codex-hepta-memory` oracle/store tests and the Agentd product qualification suite; prompt-factor composition additionally depends on prompt.registry, the prompt-factor adapter tests and prompt.optimizer graph-consumer tests. These are source/test identities until an exact-candidate run records a passing receipt. The default Agentd crate profile now selects the scoped cognitive writer and fails closed when its store is unavailable, while ordinary Codex/App Server remains default-off. This receipt grants no model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

The [2026-10-01 adversarial audit](../../../qualification/module-execution-dossiers/reports/knowledge.graph-adversarial-audit-2026-10-01.md) and [second-round audit](../../../qualification/module-execution-dossiers/reports/knowledge.graph-adversarial-audit-2026-10-01-round2.md) record concrete findings, source identities, regression evidence and remaining qualification boundaries. They do not replace the canonical completion gates.

### Complete-input identity repair (2026-10-02)

Complete-generation admission now rejects duplicate node and edge identities
before removing empty or tombstoned support sets. A dead duplicate cannot hide
an ambiguous live/dead source cut. Unique unsupported records still disappear
normally, and all resource, authority and digest contracts remain unchanged.
Two baseline-failing regressions cover both input orders and support-pruning
forms; all 35 KG package tests pass locally. The [continuation audit](ADVERSARIAL_AUDIT_20261002.md)
records the scope and remaining qualification requirements.

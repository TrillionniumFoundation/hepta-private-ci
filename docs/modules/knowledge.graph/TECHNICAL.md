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

- `CrossModalBindingV1`
- `DomainRead::knowledge_fact_ledgerV1`
- `DomainRead::memory_ledgerV1`
- `DomainRead::prompt_factor_lifecycleV1`
- `DomainRead::prompt_factor_registryV1`
- `DomainRead::prompt_realization_registryV1`
- `EngramNodeV1`
- `ForgetPropagationReceiptV1`
- `MemoryEventV1`
- `ModulePort::cognitive.store::knowledge.graph`
- `ModulePort::cognitive.types::knowledge.graph`
- `ModulePort::prompt.registry::knowledge.graph`
- `PromptFactorV1`
- `SynapseV1`

Critical protocol schemas:

- `CrossModalBindingV1`
- `EngramNodeV1`
- `ForgetPropagationReceiptV1`
- `MemoryEventV1`
- `PromptFactorV1`
- `SynapseV1`

The HNMF event, engram, synapse, cross-modal and forget contracts above are registered target inputs. Their registration does not establish an additional native KG source adapter, associative-recall implementation or learned world model. The current executable sources remain the cognitive fact ledger and the sealed prompt-factor source described below; any HNMF composition must preserve original owner, revision, support and deletion lineage.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

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

For the cognitive knowledge projection, the existing `cognitive_1.sqlite3` owner remains the only durable store. The adapter derives canonical `KnowledgeGenerationV2` values from immutable/current cognitive facts, invokes `build_complete_generation`, validates predecessor-bound `publish_generation`, writes physical projection rows plus `kg_projection_generation_semantics`, and only then advances the selected generation in the same SQLite transaction. Reopen recomputes the physical output digest, canonical generation digest and predecessor-bound publication digest. Pre-`0011` legacy generations may remain readable history but cannot drive digest-bound graph expansion without a canonical V2 semantic receipt.

Canonical cognitive entity identity is `owner + scope + entity_key`; `entity_type` and `label` are shape fields, not identity fields. All simultaneously live supports for one canonical key must agree on those shape fields or the product mutation fails closed. A correction may change shape only after the predecessor support leaves the current active cut. A rename or alias that must coexist uses a distinct entity key plus an explicit owner-governed custom relation such as `alias_of`; the KG kernel does not silently merge display labels or infer aliases.

For prompt factors, `prompt.registry` remains the fact/lifecycle owner. It stores governed complement/substitute/conflict relation records, includes them in the registry snapshot digest and emits a sealed current `PromptFactorGraphSourceV1` containing only currently admitted governed endpoints. `knowledge.graph` rebuilds that exact source into the same V2 generation type; factor revocation changes the owner source digest and removes relations whose endpoint is no longer admitted. No prompt-factor relation becomes a new source fact inside `knowledge.graph`.

The current owner implementation adds `DurablePromptRegistry::register_factor_relation` through its existing atomic commit and uncertain-commit poisoning path. Relation metadata is digest-bound in the existing V2 semantic image and V3 nested state; a missing relations field defaults to an empty set, and empty sets remain omitted so legacy relation-free V3 metadata need not be rewritten. Restore rejects invalid IDs, unknown relation kinds, zero evidence, duplicate relation identity or endpoint-pair/kind, ungoverned endpoints, missing admitted lifecycle history and capacity overflow. Historical relations remain retained after endpoint revocation, but the sealed current source filters them out; reopen cannot make them live again. Older readers that reject unknown fields cannot read populated relation metadata, so a downgrade requires an owner-reviewed compatibility path. The five new focused restart/revocation/fault and malformed-state tests passed in the historical core-library run at source `c3056c3`; complete product and exact-head/synthetic-merge qualification remains pending.

## 7. Runtime, concurrency and transaction model

For the cognitive knowledge projection, `CognitiveStore::refresh_scope_projection_tx` is the durable mutation boundary. One SQLite transaction observes the exact current source cut, derives the canonical V2 generation, reconstructs the exact predecessor, validates `publish_generation`, persists physical rows and semantic receipts, and CAS-advances `kg_projection.generation`. The selected pointer therefore cannot name a generation whose canonical receipt was not durably inserted first.

The product GraphOneHop and typed relation read paths load the persisted generation through `load_canonical_generation_tx` and prepare an owned `VerifiedKnowledgeGenerationV2`. The verified generation, relation inventory and compact support index are reused only within that owner's SQLite read transaction, keyed by scope and generation. Every seed use still requires the persisted `generation_sha256` to match the reconstructed V2 digest. The verified view delegates canonical relation selection, temporal visibility and truncation to `knowledge.graph`; query-time visibility is recomputed for each temporal cut. SQL after that point only maps kernel-selected support identities back to their physical memory occurrences. `query_relations` remains the full-scan differential reference. `apply_incremental_delta` remains an equivalence oracle/reference path; the durable product writer rebuilds the bounded complete generation on each logical mutation.

The cognitive product channels are `GraphOneHop`, `Causal`, `Procedural` and `ContradictionSupport`. The three typed channels select `Causes`, `ProcedureStep` and `Contradicts` respectively; the generic graph channel excludes these typed relations so their distinct support cannot be counted again as generic graph evidence. Each channel admits at most 32 memory candidates and the retrieval owner returns at most 4 final results. These product limits are separate from kernel generation and pilot design limits.

The prompt library path is `PromptRegistry::factor_graph_source_v1 -> build_prompt_factor_projection_v1 -> optimize_with_factor_graph`. The registry view is sealed outside the owner crate. The optimizer requires every candidate factor to exist in the complete generation and queries complements/substitutes/conflicts against the exact generation digest. `PromptConflicts` are hard co-selection exclusions; `PromptSubstitutes` are hard redundancy exclusions; `PromptComplements` are observed and receipt-bound but do not manufacture a numeric bonus because the relation record carries no calibrated marginal magnitude. Any positive complement utility must come from independently supported causal interaction evidence. The complete canonical query request and result digests are both bound into the graph portfolio receipt. The optimizer remains read-only and `DENY_ALL`.

The separate canonical optimizer `select_portfolio_v1` also consumes V2 graph relations: `PromptRequires` forms prerequisite bundles, while `PromptDominates`, `PromptRedundant` and `PromptSupersedes` enforce co-selection exclusions. It now requires every priced candidate factor to be present in the validated complete generation before querying. Previously, an unknown positive-utility candidate could be selected from a graph containing only another factor because its query returned no edges. A represented relation-free factor remains valid; the generic KG query's unknown-seed behavior is unchanged. Numeric complement/substitute utility requires separately authenticated pair evidence. The sealed prompt-factor source adapter currently emits only complements, substitutes and conflicts; the four additional relation kinds are kernel/consumer capabilities, not proof of an owner-produced source path. The existing `AgentdPromptPipelineOwner::compile_and_stage` consumes an externally selected canonical portfolio, revalidates it through `compile_prompt_registry_v2` against the durable registry and stages the compiled bytes into the product runtime host. It does not call `select_portfolio_v1` or the sealed prompt-factor source/projection/graph optimizer chain. Completing that KG route must bind the current registry source, graph generation and candidate set before the existing final-use and delivery boundaries.

The current canonical-optimizer repair captures the registry digest from the enumerated source snapshot in the selected portfolio and binds it into the portfolio receipt. `exercise_v1` compares that digest with a new current owner snapshot before exercising a nonempty portfolio. Thus a newly registered conflict or another registry change rejects the stale selection even if every selected realization binding is unchanged. This revalidation closes selection-time source drift; it does not create a KG product route. The exercise check also rejects receipt-checksum drift or granted authority on a nonempty proposal; an empty selection remains `NoIntervention`. Every owner source mutation conservatively requires re-enumeration and selection. The checksum binds proposal content and source freshness; it does not authenticate evidence or confer dispatch authority. The canonical and expanded graph-consumer regressions passed in the historical 43-test optimizer run at source `c3056c379e5a272bb8c3037b4608f5d4341c0c01`; full Agentd and synthetic-merge qualification remain separate. That receipt does not cover subsequent source-authentication changes.

The complete proposal checksum in [canonical_portfolio.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_portfolio.rs) binds selected realizations, inner/outer factor IDs, binding digests, the receipt, owner source and objective/state/model/vector context. Exercise independently requires at most 16 sorted unique selections exactly matching receipt IDs, valid realizations and bindings, an exact checked token sum and an expiry no later than any selected realization. Recomputing a checksum cannot make an inconsistent receipt valid. Empty selection retains the `NoIntervention` contract.

[canonical_temporal.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_temporal.rs) caps validity at the next future start/end of prompt-relation supports incident to priced factors, their endpoints and priced-factor node supports. Currently invisible future constraints are included. KG visibility is `[valid_from, valid_to)` in seconds; checked conversion to milliseconds makes the old selection stale at the boundary. Past or unrepresentable boundaries cannot shorten a representable future deadline. Overlapping supports may cause conservative early reselection. This temporal cap does not authenticate the graph source or change final-use authority.

### Canonical graph-source binding — implemented and locally regression-tested

A structurally valid `KnowledgeGenerationV2`, matching generation vector and complete candidate-node membership do not prove that supplied relations are the registry owner's complete projection. The adversarial baseline reproduced this gap with a real Conflict registered before enumeration and genuine signed factors: omitting the edge admitted both candidates, and a fresh, consistently recomputed portfolio reached exercise and the compiler. At published baseline `807df52331ae76fe84bf9ecf4f16031161f70868` (the identical tree of local baseline `7af3`), the two optimizer regressions and one compiler regression actually failed because the invalid dual selection was accepted. An initial zero-match invocation exited 4 without executing a test and is not counted as a counterexample. This differs from the post-selection mutation rejected by the freshness check above.

Source `0314b2f2ac8219a28bf8cf20e85a382d068d2b6b` implements the repair in private [canonical_source.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_source.rs). Enumeration retains a boxed, sealed `EnumeratedSourceV1` containing the complete `PromptFactorGraphSourceV1` and the factory's original snapshot digest. Validation checks the original snapshot, registry revision/digest, model and generation vector; changing public frontier fields and recomputing snapshot/candidate receipts cannot replace the private seal. Pricing and selection also recompute candidate and pricing-table consistency. These are same-boundary consistency checks; they do not independently reauthenticate an Evaluator credential or establish a new dispatch exploit.

Before selection, the consumer rebuilds the registered owner projection and requires every registered relation and corresponding endpoint to match exactly, including support revision, confidence, validity and tombstone fields. A graph claiming the owner factor-source digest, registry digest or owner profile must equal the complete owner generation. Additional graph relations with a distinct source/profile may remain supplemental, including temporal prerequisites and exclusions, but cannot remove or alter the registered owner projection. This check authenticates only registry-registered Complements/Substitutes/Conflicts and their exact endpoints. It does not authenticate the source cut or producer of supplemental Requires/Dominates or other raw KG relations; those still need their own trusted read/projection owner composition.

The interaction digest's v2 domain binds the sealed owner source digest. The supplied graph is preserved rather than silently merged or rewritten, so numeric PairEvidence continues to sign its original graph-generation digest. Final exercise independently rejects a current registered Conflict between selected factors as `RejectStale`, even when the portfolio and checksum are mutually consistent. Canonical Substitutes retain authenticated numeric PairEvidence semantics and are not unconditional exclusions.

The private enumerated-source field intentionally prevents external Rust struct-literal construction and exhaustive destructuring of `EnumeratedPromptCandidatesV1`; callers must use the existing enumeration factory. Public factory/method signatures are unchanged, but this is still a source-compatibility consideration. Independent source review found no residual reproducible defect in this registered-owner binding scope. The first repaired-source core run at `0314b2f2` executed 139 tests: 137 passed and two failed during fixture setup because support labels containing spaces were invalid `StableId` values. No production assertion failed in those two cases. Source `6fe8237c493b9c2a52bf2b685da1d9b1b11333cd` changes only those labels to hyphenated IDs; assertions, workloads and production code are unchanged. At that exact source, the complete scoped native chain passed 440 tests: core 139 (KG 35, registry 55, optimizer 49), memory 277, compiler delivery six, explicit crash one, explicit history one and prompt-runtime 16. Memory retained eight ordinary ignored cases; compiler/runtime filters omitted 77/160 unrelated tests. All three genuine-owner counterexamples that failed on the baseline now pass. Each executed workload retained identical before/after critical source hashes at the same source/tree, so this is a new receipt rather than inherited coverage from the historical 433-test candidate. Final six-owner `just fix` exited zero without source changes; strict lint exited 101 on the existing `CanonicalRunOutcomeV1` large-enum-variant diagnostic. This is a real code lint failure, not a disk failure or a passing receipt. The repair does not compose KG selection into Agentd or grant mutation/dispatch authority.

The pipeline-backed runtime now persists a private registry-source fence alongside the existing staged attachment. Compilation and staging hold the shared owner lock; `prepare` and every dispatch callback, including an idempotent retry after cached preparation, compare the retained source digest with that owner before returning the attachment or recording dispatch. The attachment deadline is capped by the requested deadline, selected portfolio validity and realization expiry. A changed, unavailable or poisoned owner fails closed. After uncertain durability following rename, the runtime requires reopen; commit and prepare recheck availability after acquiring state so a waiter that passed an earlier check cannot read or overwrite the retained predecessor. Terminal recording and unresolved-dispatch reconciliation retain historical evidence without requiring a still-current source. The optional `StoredStage.registry_source` field keeps old records readable: an unfenced legacy stage cannot prepare or dispatch through the bound pipeline, while the standalone generic qualification host preserves its behavior. Older readers reject populated unknown metadata; a downgrade requires owner review. These repairs add no KG selection route, dispatch permission or new durable store. At source `6fe8237c493b9c2a52bf2b685da1d9b1b11333cd`, the prompt-runtime filter actually passed all 16 selected tests, including all seven source-fence regressions; 160 unrelated tests were filtered. The source-fence and queued-poison behaviors therefore have current local native evidence, while complete Agentd product and source-head/synthetic-merge qualification remain open.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

The cognitive projection transaction has test-only process-crash rendezvous before the canonical semantic receipt and after the semantic receipt/physical rows but before current-generation CAS. The qualification child publishes an fsynced marker, is killed by its parent, and the reopened store must expose only the exact predecessor generation with no tentative source, memory revision, generation receipt or semantic receipt. This is a process-crash/SQLite-WAL test, not a physical power-loss claim. Independent `lane_c` cut-witness tests separately detect restoration of an older internally valid SQLite backup; the stronger descriptor-safe writer `open_with_recovery` contract remains owned by `cognitive.store` and is not implied by this module.

KG publication reconstruction on ordinary reopen verifies the current generation plus the exact predecessor needed by its receipt. Full historical publication-chain replay is a separate qualification/forensic operation. This narrower property does not make the complete cognitive-owner startup independent of history: `verify_revision_fact_digests` loads and checks every retained fact-set revision, and other owner integrity queries inspect historical rows. The current owner repair compares the complete `memory_fts` view with immutable memory revisions: exactly one row for each `(memory_id, revision)`, no orphan identities and exact indexed content. It also checks every retained `kg_revision_entity_fts` row against its exact source memory/revision/entity key, canonical ID, type and label, with exactly one occurrence per source entity. Existing current-generation checks remain. Superseded/tombstoned corpus history is retained because obsolete rows can affect BM25 ranking of current results. Aggregate SQL checks avoid loading those FTS histories into Rust memory or issuing a query per revision, but their historical scans/grouping add startup work. Current scope limits bound each selected projection, not total retained history. History probes measure finite growth only; a deployment still needs an owner-approved retention policy, startup memory/time budget and target-host evidence. Integrity checks must not be removed merely to claim bounded startup.

Retained lexical identities also require canonical SQLite storage types: memory identity/content and entity identity/type/label fields are TEXT, while revision fields are INTEGER. SQLite numeric affinity can make TEXT `01` or REAL `1.0` join an integer source revision even though the actual SQLx integer decoder rejects that row. Structural `quick_check` and numeric join equality therefore do not replace typed source validation. Seeded corruption tests use fresh read-only pools for structural checks, then require the actual owner reopen to reject source drift.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

### Query preparation and admission bounds — 2026-10-01

`VerifiedKnowledgeGenerationV2` owns a fully validated generation and derives
node and incident-edge indexes without exposing mutable access. Indexed selection
preserves the full-scan reference's canonical edge order, temporal supports,
request/result digests and exact omitted count. Only returned supports are copied;
exact omission counting still visits all incident matches. The full-scan reference
now allocates result slots only when an edge is selected, so no-match queries
do not reserve output storage for unrelated generation edges. Preparation is real
product work and remains included in retrieval timings. The cognitive adapter
reuses preparation only inside one read transaction; a new request or source cut
requires a new view.

Admission rejects more than 65,536 nodes, 262,144 edges, 50,000 supports on one
node/edge, 1,048,576 total supports or 256 MiB of canonical generation encoding.
Input counts include tombstoned records before normalization. Complete builders,
public validators and delta admission share these limits before sorting, lineage
copying or digest encoding. Delta removal/upsert collections and the resulting
source cut are bounded; node removal filters incident edges in one pass. The
encoding budget bounds the digest buffer, not process RSS, output bytes or a
target-host latency guarantee. The cognitive owner's stricter physical scope
limits continue to apply.

Public validation rejects noncanonical node/edge order and duplicate support
identity `(source_id, source_revision)` even when other support fields differ.
Joint endpoint and last-edge-support revocation produces an empty supported cut;
live dangling relations still fail closed. Differential tests exercise indexed
and full-scan selection and zero retained output capacity for no-match results, while transaction
tests exercise temporal cuts, digest
drift, correction, forgetting and reopen.

The prompt-factor registry/projection/optimizer path is library composition.
`optimize_with_factor_graph` has test callers but no named Agentd product caller
at this candidate. Durable relation registration now uses the existing prompt owner;
focused restart/fault tests passed, while full product qualification remains pending.
This module cannot activate that route. Product activation, target-host budgets and independent
acceptance remain explicit upstream/integration gates.

See [the 2026-10-01 audit](../../../qualification/knowledge-graph/AUDIT_20261001.md)
for corrected staged-code claims, verification and remaining evidence gates. [The follow-up audit](../../../qualification/knowledge-graph/FOLLOWUP_AUDIT_20261001.md) records the current source-boundary corrections, passing core-library checks and remaining cognitive/product qualification.

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md) specifies this module's algorithm and pilot ceilings. The current durable writer deliberately performs one bounded complete-generation rebuild for each logical mutation; `apply_incremental_delta` remains the independent equivalence/reference path until measurements justify selecting it as the durable runtime algorithm.

[codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) defines the PERF-LIBRARY probe. When executed, its default fixture performs 256 real `remember_with_kg` transactions using the same 16 entity keys and 128 relation identities, yielding 4,096 entity revision occurrences and 32,768 relation revision occurrences. The canonical projection has 16 nodes, 128 edges and 36,864 combined node/edge supports. This measures support/history growth rather than a 4,096-node/32,768-edge canonical graph. After those writes it samples product retrieval/GraphOneHop and ordinary reopen and emits mutation/query/reopen p50/p95/p99, throughput, database/WAL bytes, RSS and Linux CPU ticks. Historical remote runs skipped this step after compile failures; the local third-pass attempt timed out as recorded in Section 12. Neither supplies a successful PERF receipt. Any future receipt is measurement evidence; the repository defines no host-independent millisecond threshold. Target-host/release qualification must supply the actual acceptance budget before changing the durable writer algorithm.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Projection builder library over owner-approved facts. Publish only complete validated generations tied to an exact source cut; do not turn generated edges into source facts. Persistence, index service and route/GC ownership must be explicitly composed before claiming a durable graph deployment.

Current operating and state-format references:

- [codex-rs/hepta-kg/src/lib.rs](../../../codex-rs/hepta-kg/src/lib.rs).
- [codex-rs/hepta-kg/src/generation.rs](../../../codex-rs/hepta-kg/src/generation.rs).
- [codex-rs/hepta-memory/src/cognitive_kg_store.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store.rs) for the cognitive source adapter and same-transaction durable publication.
- [codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql](../../../codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql) for immutable semantic receipts and current-generation fencing.
- [codex-rs/hepta-memory/src/cognitive_retrieval.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval.rs) for the digest-bound GraphOneHop and typed causal/procedural/contradiction product consumers.
- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) for the durable cognitive owner contract.
- [codex-rs/hepta-kg/src/prompt_factor.rs](../../../codex-rs/hepta-kg/src/prompt_factor.rs) for the prompt.registry-to-KG adapter.
- [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs) for governed prompt-factor relation ownership and the sealed graph source.
- [codex-rs/hepta-prompt-optimizer/src/graph.rs](../../../codex-rs/hepta-prompt-optimizer/src/graph.rs) for the generation-bound library consumer.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

### Observed remote qualification and current candidate coverage

Run `36783032514` tested source `1a75d5f14fe7e66ee108086351917217289d43ac` in source-head and deterministic base-merge lanes. Both lanes passed the compiled core suite: KG 31, prompt.registry 55 and prompt.optimizer 32, totaling 118 tests with zero skipped. Scoped source mapping, measurement/budget harness checks and Rust formatting also passed. The cognitive-owner test build failed with Rust `E0659` because `assert_eq!` was ambiguous in the history test module; no memory tests executed. Subsequent crash, capacity, history, Agentd and combined strict-lint steps were skipped. The earlier local core Clippy pass does not replace that skipped cross-owner lint.

The adapter and graph-consumer files were not compiled in the 118-test baseline. Run `36794255979` subsequently tested source `163441e047f44a1cffa3df968d4358c88821cdbf` in both lanes: KG 35 and registry 55 passed with zero skipped, while optimizer compilation failed with duplicate imports and downstream native/lint workloads were skipped. Actual Bazel lock regeneration passed with zero drift. These results cover that source only.

The third pass removes the import blocker, declares the Agentd assertion dependency and regenerates the Cargo lock. It also requires canonical SQLite types in both retained lexical corpora, binds actual selected realizations and context into portfolio checksums, rejects inconsistent receipt/selection shapes even with recomputed checksums, and expires temporal interaction views at their next relevant support boundary. Local third-pass execution passed KG 35, registry 55 and optimizer 43 tests (133 total, zero skipped), plus five filtered compiler delivery tests; the compiler filter omits 77 unrelated tests and is not a full intelligence test receipt.

At historical source `c3056c379e5a272bb8c3037b4608f5d4341c0c01`, all 133 core and 277 ordinary memory library tests passed, with zero core skips and eight ordinary ignored memory cases. Five compiler-delivery regressions and all 16 selected Agentd prompt-runtime tests also passed, including seven source-fence tests; their filters omitted 77 and 160 unrelated cases respectively. The explicit child-process crash-window and correction/deletion history workloads each passed one test at that source. These workloads total 433 passing tests and do not cover the subsequent graph-source-authentication repair. The history workload performed 128 corrections, eight reopen samples and three post-deletion reopens, with no resurrection of the deleted facts. These finite workloads do not establish physical power-loss recovery, history-independent startup or indefinite retention bounds.

The default support-growth capacity run at source `676a18740ee50e93ca50c077a2e69b9c47f6b40e` exited 100 when its 1,800-second watchdog expired. It completed 256 writes, 20 queries and ten contention rounds with four readers, but only two of five reopen samples; it emitted no PERF receipt. This is an incomplete support-growth measurement, not a passing capacity or target-host qualification. Source `2be1a1d` reuses canonical-node kind/payload digests and removes duplicate shape-string allocation while preserving per-support validation and exact shape equality. Source `c3056c3` also reuses sorted support order for duplicate rejection and borrows node/edge identities during validation; duplicate checking remains before tombstone removal. The timed-out capacity run predates these changes, so no measured speedup is claimed.

Earlier local Agentd attempts at source `2be1a1d` executed zero tests: the default cognitive-product build exited 101 after the codex-exec-server archive failed with ENOSPC; the qualification-witness build exited 101 after codex-core-plugins LLVM output failed with ENOSPC; and the prompt-runtime build exited 101 when the darling_macro linker terminated with signal 7 (Bus error), whose cause has not been conclusively attributed. The later prompt-runtime retry at source `c3056c3` passed the 16 selected tests described above. The final six-owner scoped `just fix` at that source exited zero without changing source hashes. Strict lint actually ran and exited 101 on the existing `hepta-intelligence/src/canonical.rs` `CanonicalRunOutcomeV1` large-enum-variant diagnostic; this is a code lint failure, not a disk failure or a passing lint receipt. Complete default/witness product execution remains unproved.

Four prompt-runtime build attempts at the repaired source executed zero tests after E0463/E0599 dependency-resolution failures. Metadata inspection found that the archived intelligence unit referenced a different optimizer dependency hash from the current unit. A normal rebuild of the matching intelligence library unit with `--emit=metadata,link` resolved that observed mismatch, after which the actual Agentd prompt-runtime filter passed 16 tests. A separately successful intelligence library unit with a different dependency/feature-unification unit graph was not counted as Agentd evidence. The original cause of the stale archive remains unknown; no cause is attributed to source code, disk space, deletion or a timestamp change alone.

The first graph-source-repair core run at `0314b2f2` executed 139 tests with 137 passes and two `StableId::InvalidCharacter` fixture-setup failures. After repairing only the two support labels, source `6fe8237c493b9c2a52bf2b685da1d9b1b11333cd` (tree `bbe525f939dc110e1d0fdfa10b445f0d46b30c68`) actually passed 440 scoped tests: core 139, memory 277, compiler delivery six, explicit crash one, explicit correction/deletion history one and prompt-runtime 16. Memory had eight ordinary ignored cases; compiler/runtime filtered 77/160 unrelated cases. All three genuine-owner source-authentication baseline counterexamples now pass, and all seven runtime source-fence tests executed successfully. Every workload retained identical before/after critical source hashes. The first partial run remains a recorded fixture failure, not a 139-test passing receipt. At the same source, six-owner `just fix` exited zero in 261.141 seconds with all 1,096 critical inputs unchanged. Strict lint exited 101 in 169.078 seconds on `hepta-intelligence/src/canonical.rs:463`, where `CanonicalRunOutcomeV1` has a Ready variant of at least 528 bytes and an Abstained variant of at least 272 bytes. That source blob matches integrated main exactly; no public API or lint flags were changed to suppress it. The current strict-lint gate remains failed.

The [native execution receipt](../../../qualification/knowledge-graph/evidence/native-round3.json) records actual source/tree identity, verbatim command arguments when captured, exit status, ignored/filtered counts and before/after critical input hashes. It binds the externally retained raw evidence archive by SHA and per-file manifest; unavailable historical command fields are not invented. Evidence history does not select a dynamic source or grant product acceptance, activation or release authority.

The explicit deep workflow retains six-owner source qualification, compiler delivery, runtime, dependency-lock, scoped fix/strict lint and cognitive crash/capacity/history/product workloads. Third-pass actual `just bazel-lock-update` passed with no lock drift. The local library and finite recovery results do not replace current source-head and deterministic synthetic-merge qualification, complete Agentd execution, approved target-host budgets or independent acceptance. Module-wide production, product-execution and target-host claims remain open. The [second-pass audit](../../../qualification/knowledge-graph/SECOND_PASS_AUDIT_20261001.md) records executed candidates and subsequent repairs separately.

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-kg/src/generation_tests.rs](../../../codex-rs/hepta-kg/src/generation_tests.rs) and [query_closure_tests.rs](../../../codex-rs/hepta-kg/src/query_closure_tests.rs); cases cover full/incremental equivalence, predecessor-bound publication, canonical ordering, conflicting support identity, support/tombstone behavior, custom relation identities, bounded request admission and indexed/reference temporal-query equivalence.
- [codex-rs/hepta-kg/src/query_allocation_tests.rs](../../../codex-rs/hepta-kg/src/query_allocation_tests.rs); no-match requests preserve indexed/reference result equality without graph-sized output reservation.
- [codex-rs/hepta-memory/src/cognitive_retrieval_observation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_observation_tests.rs) and [cognitive_retrieval_adapter_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs); cases preserve typed-channel ownership, limits, temporal visibility and support receipts.
- [codex-rs/hepta-memory/src/cognitive_kg_history_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_history_tests.rs); the finite correction/forget/reopen probe measures retained-history effects without asserting history-independent startup.
- [codex-rs/hepta-kg/src/lib_tests.rs](../../../codex-rs/hepta-kg/src/lib_tests.rs); named case: `rebuild_is_canonical_and_authority_free`.
- [codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs); the canonical oracle drives the same source cut through full V2 rebuild, incremental V2 rebuild, SQLite materialization, reopen, query, correction and tombstone, compares physical/canonical digests plus visible query behavior, walks the complete persisted publication chain, and verifies the canonical entity shape-evolution contract.
- [codex-rs/hepta-memory/src/cognitive_store_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_tests.rs); reopen integrity includes fail-closed generation/publication receipt tamper cases plus the ignored child-process crash-window matrix. The new memory-FTS source/history regressions cover missing/duplicate/wrong-identity/content-drift rows, canonical SQLite storage types and valid correction/forget history; `reopen_rejects_obsolete_entity_fts_source_drift` covers retained entity history after a correction removes all current entities. These regressions passed in the historical 277-test memory run at source `c3056c3`; the explicit crash-window test also passed separately.
- [codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs); ignored support-growth probe uses 4,096 entity and 32,768 relation revision occurrences, representing 16 canonical nodes, 128 edges and 36,864 supports. Measurement output exists only after successful execution.
- [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs); the named Agentd product profile exercises real App Server remember, restart/recall, correction and forget while checking persisted KG receipts and product-visible retrieval. The additional `qualification-cognitive-write` feature only attaches the qualification turn-witness seam; it is not the mutation authority.
- [codex-rs/hepta-prompt-registry/src/durable_relations_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_relations_tests.rs); focused cases cover exact graph-source restart equality, revocation non-resurrection, legacy metadata, capacity, predecessor preservation, uncertain commit and corrupted relation restoration.
- [codex-rs/hepta-prompt-registry/src/lib_tests.rs](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs), [codex-rs/hepta-kg/src/prompt_factor_tests.rs](../../../codex-rs/hepta-kg/src/prompt_factor_tests.rs), and [codex-rs/hepta-prompt-optimizer/src/graph_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/graph_tests.rs) cover owner-bound relation admission, revocation/rebuild, V2 projection/query and graph-conflict enforcement in the read-only optimizer.
- [canonical_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_tests.rs) and [prompt_delivery_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs) cover complete candidate-node membership, registry-source drift and receipt/actual-selection binding at selection/exercise/compiler boundaries. [canonical_temporal_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_temporal_tests.rs) exercises authenticated pricing and reselection across future edge/endpoint visibility boundaries. [canonical_source_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_source_tests.rs) supplies genuine-owner source-authentication counterexamples. Two optimizer and one compiler counterexample failed as intended on baseline `807df523`; the repaired source `0314b2f2` adds exact owner-edge/endpoint, complete owner-claim and signed numeric supplemental-relation coverage, whose first core run had two fixture-setup failures and whose retry at `6fe8237c` passed as part of the new 139-test core receipt, without inherited coverage from the earlier candidate. [prompt_runtime_source_tests.rs](../../../codex-rs/hepta-agentd/src/prompt_runtime_source_tests.rs) adds bound-runtime tests for deadline capping, signed revocation/reopen, cached prepare/idempotent dispatch, legacy stages/reconciliation and persisted fence corruption; all seven passed in the current 16-test runtime filter at source `6fe8237c`.

In `codex-rs`, run `just test -p codex-hepta-kg`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/knowledge.graph.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

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

For `knowledge.graph`, the cognitive knowledge read path is product-composed. This candidate also makes scoped cognitive mutation the default **Agentd** product profile and fails Agentd startup closed when the cognitive owner store is unavailable; ordinary Codex/App Server binaries remain default-off. The separate `qualification-cognitive-write` feature adds only the qualification turn-witness seam. This candidate writer is not treated as established until current exact-head and deterministic synthetic-merge evidence are green.

The prompt-factor graph source/projection/consumer path is library-composed separately from the cognitive SQLite path: prompt.registry owns relation facts, knowledge.graph rebuilds them, and prompt.optimizer consumes the exact generation-bound relation view. The existing prompt owner now includes durable relation registration and validated restoration; focused core/owner library validation passed as recorded in the follow-up audit; complete cognitive/product and exact-head/synthetic-merge qualification remains pending. The existing Agentd compiler/runtime staging consumer does not itself compose the sealed prompt-factor KG selection route; that source/projection/selection binding and its product evidence remain separate integration work. The optimizer remains a read-only consumer. All five module-wide claims remain false: `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation` and `release`. Current exact-head and deterministic synthetic-merge qualification, complete product execution, independent acceptance, activation and release remain distinct gates.

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

Ordinary aggregate CI validates development navigation and selects affected owners and reverse consumers from the base and candidate dependency graphs. It does not renew historical closed-world qualification evidence by default. The explicit `.github/workflows/hepta-knowledge-graph-qualification.yml` accepts exact `source_sha` and optional `base_sha` inputs; providing the base runs source-head and deterministic synthetic-merge lanes. It verifies six owner maps with the qualification profile and retains package tests, cross-owner recovery and Agentd product workloads, strict lint, tracked-source cleanliness and dependency-lock regeneration. These are source/test identities until an exact-candidate run records a passing receipt. The default Agentd crate profile selects the scoped cognitive writer and fails closed when its store is unavailable, while ordinary Codex/App Server remains default-off. This receipt grants no model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

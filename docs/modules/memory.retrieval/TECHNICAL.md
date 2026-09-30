# memory.retrieval technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `memory.retrieval`

**Owner:** `cognitive-platform`

**Deputy:** `performance`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-2-RETRIEVAL`

This stable document is the implementation guide for `memory.retrieval`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Produce explainable, revalidated retrieval results on the local hot path without central synchronous RPC.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `performance` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `engine`, state model `read_only` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-memory-retrieval`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-memory-retrieval`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The source root now contains four complementary native surfaces: [v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs) preserves the complete-input integrity binding; [generator.rs](../../../codex-rs/hepta-memory-retrieval/src/generator.rs) owns cue compilation, authenticated generator-batch canonicalization and policy-relative completeness; [engram.rs](../../../codex-rs/hepta-memory-retrieval/src/engram.rs) owns bounded HNMF expansion/settling/competition; and [decision.rs](../../../codex-rs/hepta-memory-retrieval/src/decision.rs) emits generator-relative assignment observations. The durable SQLite adapter and explicit Agentd host live in their existing owner roots and do not move ownership into this crate. These are source candidates, not proof of activation, target-host performance, independent acceptance or release. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) for the exact implemented subset and evidence gates.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `cognitive.read`
- `knowledge.graph`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `write_authority`
- `central_rpc_hot_path`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bounded input stage`
- `deterministic algorithm core`
- `generation publisher`
- `checkpoint and recovery layer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Host the first read-only cooperating organ: channel allocation, candidate relevance, contradiction support, evidence sufficiency and stopping. Keep owner-generated bounded candidates and current source validation; cells cannot invent relevance inputs or silently truncate the evaluated set. Expose one stable evidence/coverage/cost port to callers.

Use one circuit across sufficient, conflicting, unavailable-organ and exhausted-budget contexts. Keep stable evidence/coverage/cost ports; do not hard-code a separate workflow for every context. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: full bounded candidate ranking, missing channels, contradiction/OOD, stopping policy and add/retire behind unchanged public port.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Evaluate whether compact evidence/organ summaries lose distinctions or long-history dependencies needed downstream. A source reread is an explicit owner-validated operation with cost. Run capacity/depth sweeps on the same bounded candidate information and retain old-task tests.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Use Recall circuits for current evidence, not as an implicit training exporter. Preserve exact source roots, applicability/contradictions and observed delivery. Copied claims are not independent support; shared relevance scores cannot widen access or turn text into instructions.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::memory.retrieval::prompt.optimizer`

Consumed contracts:

- `DomainRead::knowledge_graph_projectionV1`
- `DomainRead::prompt_factor_graph_projectionV1`
- `ModulePort::cognitive.read::memory.retrieval`
- `ModulePort::knowledge.graph::memory.retrieval`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `knowledge_graph_projection`
- `prompt_factor_graph_projection`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md) specifies the algorithm, enforced product ceilings and measurement obligations. The generation-bound path rejects more than 512 total generator candidate events, more than 16 recall selections, more than 4096 engram nodes, more than 32768 synapses, more than four settling steps or more than 64 active units per population. The current SQLite owner exposes seven bounded channels at at most 32 rows each (lexical, entity, generic graph, temporal, typed causal, typed procedural and typed contradiction support), for at most 224 raw owner events before union. The legacy V1/V2 sorter remains separately bounded for compatibility and must not be mistaken for the product HNMF profile. These are capacity invariants, not latency or efficiency measurements; p50/p95/p99, throughput, CPU, RSS/peak memory, allocation and SQLite/revalidation cost require a named target-host receipt.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Embed retrieval against an authorized coherent read cut. The real Agentd process profile is selected by `HEPTA_COGNITIVE_RETRIEVAL_MODE`: absence or `compatibility` preserves the compatibility path, while `hnmf-required` selects the fail-closed HNMF profile. The ordinary binary does not synthesize a current retrieval context; selecting `hnmf-required` without an externally composed authenticated `CurrentMemoryRetrievalContext` therefore rejects startup instead of falling back. The explicit HNMF host first obtains the Lane C cut, then observes the SQLite owner's bounded generator output before legacy top-four truncation. The owner adapter preserves channel rank and `Exhausted` versus `LimitReached` state and converts only owner-observed rows into generator batches. The durable SQLite KG owner reserves exact `Causes`, `ProcedureStep` and `Contradicts` relation vocabulary for independent causal, procedural and contradiction-support channels; generic GraphOneHop explicitly excludes those typed edges, so they cannot be double-counted or relabelled. A positive-weight retrieval policy channel without its owner batch, or with an owner batch explicitly marked `Unavailable`, fails closed; a saturated `LimitReached` channel remains explicitly incomplete. HNMF selection is followed by exact revision/content/source revalidation before materialization. Response byte/result limits, NDU context planning and optional learned reranking may narrow the final delivered subset; the learning-ledger bridge records that delivered subset separately from HNMF selection.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs): deterministic union/recall ordering, hard result bounds, contradiction/OOD/generation failures and public-receipt validation.
- [generator_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generator_tests.rs): generator permutation invariance, total 512-candidate ingress bound, channel-rank integrity, policy-relative owner coverage and cross-generation rebinding rejection.
- [engram_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/engram_tests.rs): recurrent association, sparse population bounds, contradiction abstention, recomputed structural-forgery rejection and RET-04 no-intervention/no-recurrence/no-inhibition baselines.
- [decision_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/decision_tests.rs): complete legal candidate-set and deterministic assignment binding.
- [cognitive_retrieval_adapter_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs): real SQLite owner adaptation before top-four truncation, source completeness and Lane C retrieval-profile fencing.
- [cognitive_context_hnmf_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs): explicit Agentd HNMF consumer and final owner-currentness behavior.
- [runtime_tests.rs](../../../codex-rs/hepta-agentd/src/runtime_tests.rs): explicit `Compatibility` versus `HnmfRequired` startup behavior; `Compatibility` rejects an attached HNMF context and `HnmfRequired` rejects a missing current retrieval context.
- learning-ledger retrieval/durable tests: final delivered-set persistence is distinct from HNMF selection.

In `codex-rs`, run `just test --locked -p codex-hepta-memory-retrieval -p codex-hepta-memory -p codex-hepta-agentd -p codex-hepta-learning-ledger` for the focused cross-owner source candidate. The repository's consolidated source gate additionally executes ordered source/merge identities and strict all-target Clippy. `.github/workflows/hepta-memory-retrieval-qualification-host.yml` executes the three release-mode capacity probes and retains exact host/source/raw `/usr/bin/time -v` artifacts; a GitHub-hosted result is qualification-host evidence only and must not be relabeled as an approved production target-host receipt. Commands are invocations, not stored results; inspect the exact-candidate records for passes, failures and skips. Target-host performance and longitudinal task utility remain separate evidence classes.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-2-RETRIEVAL`

The bootstrap package is `MEM-2-RETRIEVAL`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Agentd now makes retrieval mode explicit through `CognitiveRetrievalMode`: `Compatibility` retains the owner-ranked compatibility path and rejects an attached HNMF current-context provider, while `HnmfRequired` refuses startup unless a current authenticated retrieval-context provider is configured. After startup, provider currentness/revocation failures fail the request; the required profile never silently falls back to compatibility. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary and are not evidence for HNMF product execution. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `memory.retrieval`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-2-RETRIEVAL`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `cognitive-platform` / `performance`.
- Allowed write paths:
- `codex-rs/hepta-memory-retrieval/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-1-STORE`
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

The canonical readiness overlay binds `memory.retrieval` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `memory.retrieval` is implemented by work package `MEM-2-RETRIEVAL` in:

- `codex-rs/hepta-memory-retrieval`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

### Canonical HNMF recall migration

The current `generation_bound::RecallPacketV1` remains the compatibility receipt during migration; it is **not** silently reinterpreted as `cognitive.types::hnmf_learning::RecallPacketV1`. `adapt_generation_bound_recall_to_canonical_shadow_v1` emits only a shadow canonical packet and requires an explicit bridge that binds the exact legacy cue/candidate-union/generation-vector digests plus every selected legacy record ID/revision/digest to an independently supplied canonical event identity/revision/digest. A legacy binary cue digest is never reused as the canonical JSON cue digest, and a legacy record ID is never inferred to be a canonical event ID. The adapter carries no attachment, model-call, writer, selection, promotion, or release authority. Product replacement remains false until downstream owner callsites have migrated and exact-candidate qualification is current.

## 18. Adversarial validation and development checklist (2026-10-01)

The development baseline for this review is main commit
`a126987b84737dbc2ee2592442a314117bddb4a2`. The global guide remains
`docs/DEVELOPMENT.md`; the module implementation design is
`qualification/module-execution-dossiers/detail/memory.retrieval.md`.
The implementation map records historical observations and pending qualification;
its booleans must not be promoted by a local test run.

### Concrete data flow and trust boundary

1. `CognitiveStore::observe_memory_retrieval` enumerates a bounded SQLite read cut.
2. `cognitive_retrieval_adapter` converts owner ranks, exact record revisions,
   supports and saturation state into generator batches.
3. `compile_cue` binds the objective, approved context, request and Lane C vector.
4. `build_candidate_union_from_generated` requires all positive-weight channels,
   rejects unavailable owners, validates every raw candidate before truncation,
   and builds a deterministic weighted union.
5. `recall_generated_with_engram` expands and settles a supplied immutable engram
   snapshot, then emits a selection or an explicit abstention.
6. `observe_retrieval_assignment` reconstructs the legal union and checks selected
   record digests, scores, OOD, channel/support/contradiction evidence, generation,
   channel coverage, result limit and recalled omission count against that cut.
   Plain recall is replayed to verify the exact deterministic selection. HNMF
   assignment checks the full active-support intersection with the candidate cut
   and uses the same ranking routine as generation to verify the actual winner.
   This API has no engram snapshot argument and cannot independently replay
   settling from an arbitrary receipt; active-state provenance remains required.
7. Agentd orders/budgets the final subset and performs final owner/current-context
   revalidation before materialization. `learning.ledger` records delivery evidence.

`Digest32` is an integrity binding, not a signature or source-authentication
mechanism. These public Rust structs and their constructors do not authenticate
an arbitrary caller. Owner authentication and freshness come from the owner adapter
and current-context provider. Standalone `validate()` rejects structural violations;
it cannot prove that an otherwise internally consistent candidate universe was
actually observed. At a contextual boundary, compare with the retained trusted
input, as the assignment operation does. Recomputing a digest is never acceptance.

### Deterministic ranking and settling

Channel events are ordered by channel, rank, record ID and revision before the
per-channel limit. Each admitted channel contributes
`normalized_score.checked_mul(weight)`; checked addition is clamped to `[0, 1]`.
The union orders by descending weighted score, then ascending record ID/revision.
Zero-weight channels cannot provide coverage. OOD is the maximum observed signal,
not an average; shared contradiction groups and active contradicting synapses
can force abstention according to the two policies.

Engram direct drive is the clamped sum of union scores for a node's exact supports.
Each recurrent step adds the previous activation times `leak`, subtracts threshold,
and adds signed incoming synapse contributions, then clamps and applies sparse
population competition. HNMF ranks admitted, score-qualified records by maximum
active support strength, then union score, then record ID/revision. Product defaults
are four settling steps, two expansion hops, 64 active nodes per population,
448 total active nodes and 64 retained activation paths. All arithmetic uses the
shared `FixedQ32` checked operations; arithmetic errors are explicit failures.

### Enforced adversarial invariants

| Surface | Required check | Failure behavior |
| --- | --- | --- |
| Union/selection evidence | At most one support and contradiction-group digest per contributing channel; union plus omitted events <=512 | Structural rejection before digest traversal |
| Full raw candidate cut | A record ID/revision has one record digest across every channel, including events omitted by policy | `ConflictingRecordRevision` before truncation |
| Generated union/recall | Total generator counts <=512; available owners; admitted/selected channels and counts fit supplied owner receipts | `CandidateLimitExceeded`, `RequiredGeneratorUnavailable` or `CandidateCountMismatch` |
| Assignment observation | Enumerated/legal <=512, selected <=16, policy omissions <=512, nonzero record digests | Bounded rejection before set allocation |
| Assignment creation | Selected metadata matches reconstructed union; generation, coverage, result budget and recalled omission count agree | `RecallUnionMismatch` or `SelectedEvidenceMismatch` |
| Engram snapshot and active receipt | Each node has at most 512 exact support identities | `PolicyBoundExceeded` before support traversal/cloning |
| Engram construction | <=4096 nodes and <=32768 synapses before sorting/hashing | Existing node/synapse limit errors |

The support limit bounds nested work that node-count ceilings alone did not bound.
It allows supports outside the current candidate cut, which are needed for graph
expansion; only supports present in the current cut can enter `selected_support`.
Existing valid digest domains and byte scopes remain unchanged. Inputs newly
rejected by these checks were inconsistent or outside the bounded product profile.

### Reproduction and review

From the repository root with Rust 1.95.0, `just` and `cargo-nextest` installed:

```sh
just test -p codex-hepta-memory-retrieval
cd codex-rs
cargo check -p codex-hepta-memory-retrieval --all-targets --locked
cargo clippy -p codex-hepta-memory-retrieval --all-targets --locked -- -D warnings
cargo fmt -p codex-hepta-memory-retrieval -- --check
```

For owner composition, run focused `codex-hepta-memory`, `codex-hepta-agentd`
and `codex-hepta-learning-ledger` tests using `just test -p <package>`. Retain exact
source identity and logs; a copied minimal workspace is fallback unit evidence,
not full-workspace or owner-composition qualification. The qualification-host
workflow records capacity probes; an approved production target host is still
needed for performance/activation claims.

Regression fixtures modify public fields and recompute all affected digests;
ordinary stale-digest tests alone cannot exercise this threat. Review both the
full candidate enumeration and the post-policy legal set. Omitted channel events
are counted separately from omitted unique records, so do not derive policy-event
omissions by subtracting the two unique candidate-set lengths.

Remaining work is the map's existing current-context provider composition,
real Vector owner, exact-head/synthetic-merge CI, target-host measurements and
independent semantic/operator acceptance. The compatibility/canonical shadow
bridge also remains separate from a complete downstream canonical migration.
No local audit grants activation, acceptance, promotion or release.

### Follow-up audit: cue and HNMF state consistency

`settle_engram` requires both generation equality and `union.cue_digest == cue.digest()`;
sharing a Lane C generation does not make two requests interchangeable. Active
nodes must have strictly positive activation even when `minimum_activation` is zero.
Zero is a permitted cutoff configuration, not evidence of activity.

Recall selections must be members of the engram's declared `selected_support`.
Assignment verification checks that this support is exactly the intersection of
active-node supports with the current candidate union, and verifies HNMF winners
with the shared `select_engram_candidates` routine. Candidate counts are checked
for abstentions as well as recalled packets. Generation and observation also share
`engram_disposition` to enforce no-candidate, channel coverage, contradiction, OOD
and score-floor precedence. The observation API lacks the actual dynamics policy,
so it accepts either owner contradiction posture only where that flag can change
the outcome; it still rejects arbitrary abstentions and known policy bypasses.
Settling itself still requires trusted snapshot/dynamics provenance; these checks do not authenticate a fabricated engine.

Negative-relation activation paths cannot claim positive contributions. Contradiction
pairs use ascending node IDs; resource traversal counts must cover the retained
paths and contradiction pairs. Selected-support and contradiction collections have
explicit pre-traversal bounds. Valid existing digest domains remain unchanged.

The qualification-host workflow now also runs native receipt/assignment regressions,
SQLite owner adapter/revalidation regressions and the learning-ledger retrieval subset,
and retains their raw logs at the exact source identity. All probe and regression
filters explicitly fail on zero selected tests. This supplies focused source
execution evidence independently of unrelated global preflight failures; it does not
waive those gates or establish Agentd/target-host acceptance.

After committing source and guide changes, refresh only this module's navigation
observation with `python3 scripts/hepta-implementation-maps.py migrate --module
memory.retrieval`, commit that metadata, and verify it. The map cannot contain its
own future commit identity. Source observation is not execution qualification.

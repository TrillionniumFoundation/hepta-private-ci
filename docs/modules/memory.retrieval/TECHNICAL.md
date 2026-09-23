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

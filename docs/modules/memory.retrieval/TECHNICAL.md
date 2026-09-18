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

The compatibility source-navigation binding remains [codex-rs/hepta-memory-retrieval/src/v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs), but the current engine spans [generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs), [channel_contract.rs](../../../codex-rs/hepta-memory-retrieval/src/channel_contract.rs), [engram_expansion.rs](../../../codex-rs/hepta-memory-retrieval/src/engram_expansion.rs), [hnmf.rs](../../../codex-rs/hepta-memory-retrieval/src/hnmf.rs) and [qualification.rs](../../../codex-rs/hepta-memory-retrieval/src/qualification.rs). Implemented owner composition lives at the existing physical owner and host boundaries: `CognitiveStore::observe_memory_retrieval` in `hepta-memory`, the Agentd owner adapter, and `cognitive_context::read_with_runtime`. These are native Rust surfaces, not newly admitted cross-module wire formats. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) for the exact claim boundary.

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

- `cue compiler and generation-vector validator`;
- `owner channel adapter with explicit exhausted/truncated/partial coverage`;
- `deterministic candidate union and untrusted-boundary receipt validation`;
- `bounded candidate-local engram expansion and recurrent HNMF recall`;
- `Agentd product adapter with final source/profile/ranker revalidation`;
- `learning.ledger decision adapter for the complete legal set and actual propensity`.

The retrieval engine itself owns no durable fact store. The canonical SQLite cognitive owner supplies source facts and bounded generator observations; the canonical learning ledger owns causal decision persistence.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

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

The [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) binds generation-relative retrieval to one owner-acquired SQLite cut. `observe_memory_retrieval` generates and revalidates the bounded pre-top-four pool in one read transaction; Agentd intersects it with the authoritative read result before cue/channel adaptation. Optional HNMF and learned ranking execute before the final response limit. Context byte planning, owner snapshot revalidation, retrieval-profile revalidation and learned-ranker revalidation all complete before the causal decision is appended. The durable decision sink accepts only an already-created or recovered canonical `DurableLedger`; it does not mint a path, authority or second ledger owner.

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

The generation-bound engine enforces at most 512 candidate events, 4096 local engram nodes, 32768 synapses, four recurrent steps, 16 recall selections and 64 active units per population. The current SQLite owner is stricter: each native MemoryFts/EntityFts/GraphOneHop/Recency generator is capped at 32 rows and the owner observation materializes at most 128 revalidated candidates before the legacy top-four view. Owner-to-engine adaptation currently maps MemoryFts→lexical, EntityFts→entity and Recency→temporal. GraphOneHop is not silently relabeled as causal or procedural; vector, causal, procedural and contradiction-support require their actual owners to expose authenticated bounded batches.

The source-candidate workflow [hepta-memory-retrieval-qualification.yml](../../../.github/workflows/hepta-memory-retrieval-qualification.yml) measures the maximum engine profile on exact-head and synthetic-merge CI, recording p50/p95/p99 wall latency plus process CPU/RSS observations. Those observations characterize the CI host only. They are not target-host SLOs, longitudinal recall quality or independent acceptance.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Embed retrieval against an authorized coherent read cut. The composed Agentd path first acquires the authoritative read result and the SQLite owner's full bounded pre-top-four observation, then adapts only exact ID/revision/content matches. A configured channel that lacks an authenticated owner batch fails closed rather than being fabricated. Partial or truncated enabled-channel coverage abstains instead of recording a complete assignment. After HNMF, an optional pinned learned ranker may reorder only the already admitted selections. The 24 KiB context budget and NDU read/abstain plan are applied before final owner/profile/ranker revalidation and durable causal-decision append. Revoked, corrected, expired or generation-drifted sources therefore cannot be attached merely because they ranked earlier.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs): deterministic permutation, 512/513 bounds, coverage and hardened receipt validation;
- [channel_contract_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/channel_contract_tests.rs): explicit generator completeness and channel-limit accounting;
- [hnmf_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/hnmf_tests.rs): bounded local expansion, recurrent settling, sparse competition, contradiction/OOD abstention and no-recurrence/no-inhibition ablations;
- [cognitive_retrieval_observation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_observation_tests.rs): real SQLite pre-top-four observation, withdrawal and 512-record saturation;
- Agentd owner-adapter/runtime/context tests: exact authoritative-read intersection, explicit host profile revalidation, learned-ranker composition and final publication bounds;
- learning-ledger durable tests: 512 legal retrieval candidates plus explicit `abstain` survive sync/reopen.

Run `just test -p codex-hepta-memory-retrieval` for the engine and the named owner/Agentd/ledger package tests for composition. The dedicated source qualification workflow runs both exact head and deterministic synthetic merge and retains metric/time artifacts. No source-host run establishes independent task efficacy, target-host performance or release eligibility.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-2-RETRIEVAL`

The bootstrap package is `MEM-2-RETRIEVAL`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

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

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml` and `.github/workflows/hepta-memory-retrieval-qualification.yml`, including closed-world inventory, package tests, exact-head/synthetic-merge execution, strict lint and retained source-host observations. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

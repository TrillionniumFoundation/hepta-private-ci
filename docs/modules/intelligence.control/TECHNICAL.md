# intelligence.control technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `intelligence.control`

**Owner:** `intelligence-platform`

**Deputy:** `qualification-plane`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `INTELLIGENCE-A0-Q0.63`

This stable document is the implementation guide for `intelligence.control`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Compose objective, utility, neuron, intuition, prompt, context and evaluation ports without owning their facts.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `qualification-plane` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `composition_facade`, state model `ephemeral` and architecture role `composition_facade` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-intelligence`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-intelligence`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The canonical source is [codex-rs/hepta-intelligence/src/canonical.rs](../../../codex-rs/hepta-intelligence/src/canonical.rs); root exports include `build_legal_candidates`, `prepare_intelligence_run`, `decide_boundary`, `assemble_context` and `validate_current_snapshot`. The named product-runner implementation is [codex-rs/hepta-agentd/src/intelligence_product.rs](../../../codex-rs/hepta-agentd/src/intelligence_product.rs). It supplies concrete adapters to the seven authoritative owner crates and retains no replacement store. The configured Agentd product profile now invokes this runner from the authenticated `ObjectiveStart` daemon ingress through a host-owned seven-owner invocation provider; the bare compatibility profile leaves that provider absent and does not advertise canonical execution. Historical `run_read_only_vertical`, `run_shadow_pipeline{,_v2}`, `run_evaluated_shadow_v1` and `compose` remain compatibility/reference surfaces, not parallel product facades. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/intelligence.control.md#8-current-native-implementation) for the exact claim boundary.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `objective.compiler`
- `utility.ndu`
- `neuron.runtime`
- `intuition.policy`
- `prompt.optimizer`
- `context.compiler`
- `learning.eval`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `production_write`
- `model_authority`
- `physical_effect`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `canonical seven-owner snapshot and currentness fence`
- `ordered objective -> NDU -> neuron -> prompt -> intuition -> context -> evaluation pipeline`
- `advisory decision/context boundary compiler`
- `Agentd product runner and final-use fence`
- `durable Decision/Outcome append plus exact indeterminate replay seam`
- `compatibility read-only/evaluated-shadow adapters`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Compose one product path using the existing objective, owner evidence, NDU value, cell/organ inference, calibrated policy and context stages. Keep backend-specific Laya APIs behind inference/Neuron adapters; preserve outcomes back to the ledger. Do not add a parallel Laya control loop or store.

Use one product composition for circuit-triggered cell/organ calls and result feedback. Do not add an independent Laya flow engine or flatten every organ into private cells. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: coherent bundle across stages, required-owner outage, source/parameter drift and actual downstream outcome linkage.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Compose one mixed computation path with explicit continuous regions, discrete control and external observation. Record scope-limited capacity/depth/budget facts without conflating hierarchy with gradient depth or installing a parallel meta-RL controller.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Compose local task/context and permitted shared evidence through existing owners, with independent feedback to learning. Do not create a central all-Agent context, data writer or hidden parameter updater. Actual evidence delivery and selected bundles remain run-bound.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `IntelligenceHostEnvelopeV1`
- `LegalActionCandidateSetV1`

Consumed contracts:

- `DomainRead::eligibility_trace_checkpointV1`
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `DomainRead::neuron_state_checkpointV1`
- `LearningArtifactManifestV1`
- `ModulePort::context.compiler::intelligence.control`
- `ModulePort::intuition.policy::intelligence.control`
- `ModulePort::learning.eval::intelligence.control`
- `ModulePort::neuron.runtime::intelligence.control`
- `ModulePort::objective.compiler::intelligence.control`
- `ModulePort::prompt.optimizer::intelligence.control`
- `ModulePort::utility.ndu::intelligence.control`

Critical protocol schemas:

- `IntelligenceHostEnvelopeV1`
- `LearningArtifactManifestV1`
- `LegalActionCandidateSetV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `eligibility_trace_checkpoint`
- `ndu_preference_projection`
- `ndu_utility_projection`
- `neuron_state_checkpoint`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The canonical facade is in-process and ephemeral. Agentd owns the product-call lifetime. Every owner stage is fenced by a before/after reread of owner generation, implementation digest, current key digest/epoch, authority epoch and revocation frontier; selected runs receive another all-owner fence before the host envelope and another Agentd fence before dispatch/ledger use. The currentness manifest is Ed25519-authenticated against a verifier configured outside the manifest; the signed domain includes authority epoch, revocation frontier, all seven owner generation/implementation/key bindings and signer identity. The file is bounded and, on Unix, must be a non-symlink regular file without group/world write permission.

Agentd runs cognition inside a blocking worker that receives no effect or ledger capability. Each real owner call is measured against its stage budget and the full worker is bounded by the total cognition budget. A late computation result is discarded rather than published; this isolates effect publication but does not claim that `spawn_blocking` can terminate a running synchronous Rust stage. The daemon separately owns `AgentRunCoordinator`; its control protocol exposes typed start/attach/status/dispatch/cancel/terminal transitions, with admission time taken by Agentd rather than supplied by the client. Durable Decision/Outcome writes occur only after the cognition worker and final-use fence, through the existing sealed `DurableLearningJournal`.

For physical model execution, `AppServerModelDriver::run_intelligence` accepts a non-authorizing exact run binding. Before a `turn/start`, runtime.codex requires the same Agentd run to be `ContextAttached` at the expected revision with matching context and intelligence-envelope digests, persists its native dispatch record, atomically advances Agentd to `Dispatched`, and only then crosses the App Server effect boundary.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at every authoritative owner boundary.

## 8. Failure semantics, recovery and rollback

Owner rejection, unauthenticated/unavailable currentness, key/generation/authority/revocation drift, stage timeout and total timeout all fail before dispatch publication. Abstain and slow-path are explicit terminal advisory outcomes and never fabricate context/evaluation/dispatch receipts. Durable ledger `Indeterminate` or ambiguous I/O returns the exact event plus its original predecessor as `PendingIntelligenceLedgerAppendV1`; reconciliation requires a freshly recovered journal and exact replay.

After the physical dispatch write-ahead, a lost `turn/start` acknowledgement is never replay evidence: the Agentd run is moved to `Indeterminate`. Cancellation or deadline handling first records the Agentd cancellation transition; if the interrupt/grace window still lacks a terminal provider observation, the run also becomes `Indeterminate`. A real terminal App Server observation is committed back to the same Agentd run revision. Failure of that terminal-control RPC is reported as reconciliation-required and does not erase or upgrade the provider observation. No queue/handler/transport acknowledgement is inferred as terminal external success.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The canonical source enforces at most 128 legal candidates, exactly seven owner bindings, non-zero per-stage budgets, a bounded total cognition budget and monotonic elapsed-time rejection for every real owner call. Agentd additionally applies a total worker timeout and a four-worker admission bound. A permit remains owned by the actual blocking computation until it finishes, including after request timeout or cancellation. Saturation returns `Busy` without enqueueing another computation; it is not a successful advisory outcome. This bound does not wire the runner into the daemon request path. These are source enforcement facts, not target-host latency/RSS measurements; target-host qualification remains separate.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The canonical product topology is Agentd -> intelligence.control -> seven authoritative owner ports -> Agentd run lifecycle -> runtime.codex/App Server. The facade produces an authority-free host envelope; Agentd freezes that exact envelope into a `ContextAttached` run record and derives only a dispatch proposal digest after final currentness. The native inference worker can consume the binding programmatically or through the all-or-none `--intelligence-*` CLI arguments; it cannot manufacture a run or bypass the Agentd revision fence. Decision and independently observed Outcome use the existing learning ledger owner. Legacy read-only/evaluated-shadow entrypoints remain observable compatibility surfaces but are not product routing choices.

Current operating and state-format references:

- [codex-rs/hepta-intelligence/EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-intelligence/src/canonical_tests.rs](../../../codex-rs/hepta-intelligence/src/canonical_tests.rs): first-class NDU/seven-owner order, abstention, post-call generation drift, key rotation, wrong-owner receipt and candidate closure.
- [codex-rs/hepta-agentd/src/intelligence_product_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_product_tests.rs): real owner APIs, signed-currentness tamper rejection, exact Agentd admit/context/dispatch/terminal lifecycle, durable Decision -> independent Outcome, acknowledged reopen/idempotent retry, final-use revocation race, missing owner and total timeout.
- [codex-rs/hepta-agent-protocol/src/lib.rs](../../../codex-rs/hepta-agent-protocol/src/lib.rs): strict/bounded run-lifecycle wire round trip and proof that admission time is not client supplied.
- [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs) and native-run-control tests: physical turn terminal/cancellation/indeterminate semantics. Exact intelligence-bound real-process execution remains an exact-candidate product-E2E requirement.
- [codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs): compatibility durable evaluated-shadow regression.

In `codex-rs`, run `just test -p codex-hepta-intelligence -p codex-hepta-agentd`. The command is a test invocation, not a stored result. Exact-head and deterministic-merge workflow receipts, skips and target-host measurements must be inspected before elevating the claim boundary.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `INTELLIGENCE-A0-Q0.63`
- `INT-2-AGENTD-CODEX-COMPOSITION`

The bootstrap package is `INTELLIGENCE-A0-Q0.63`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

The named source-level composition caller is `AgentdIntelligenceProductRunnerV1`; the named physical turn caller is `AppServerModelDriver::run_intelligence`, with `hepta-infer-worker` exposing the same exact binding as an all-or-none CLI profile. This establishes product-route source, not deployment activation or real-provider qualification. A selected live Agentd/App Server profile must still provision the trusted currentness signer/verifier, demonstrate exact run-lifecycle execution on the candidate and target host, and satisfy activation predecessors. Shadow and qualification callers remain non-production evidence unless they traverse that same route.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `intelligence.control`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-intelligence/**`
- `qa/learning/prompted-memory-retrieval/**`
- Development predecessors:
- `CTX-1-CONTEXT-COMPILER`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- `P0.8D-VERTICAL-SLICE`
- `INTELLIGENCE-A0-Q0.63`
- Activation predecessors:
- `CTX-1-CONTEXT-COMPILER`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- `P0.8D-VERTICAL-SLICE`
- `INTELLIGENCE-A0-Q0.63`
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
- `read_only_action_domain`
- `complete_candidate_set`
- `logged_propensity`
- `no_prompt_baseline`
- `factor_and_timing_ablation`
- `zero_memory_kg_effect`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `INTELLIGENCE-A0-Q0.63`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `independent_qualification_source`.
- Owner/deputy: `intelligence-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-intelligence/**`
- `scripts/hepta-intelligence-*.py`
- `.github/workflows/hepta-intelligence-*.yml`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- Activation predecessors:
- `P0.7B-B0-VERIFIED-USE`
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

#### `INT-2-AGENTD-CODEX-COMPOSITION`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-intelligence/**`
- Development predecessors:
- `CTX-1-CONTEXT-COMPILER`
- `INT-1-CALIBRATED-INTUITION-POLICY`
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `INTELLIGENCE-A0-Q0.63`
- Activation predecessors:
- `CTX-1-CONTEXT-COMPILER`
- `INT-1-CALIBRATED-INTUITION-POLICY`
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `INTELLIGENCE-A0-Q0.63`
- Required deliverables:
- `exact_source_identity`
- `static_verification`
- `focused_tests`
- `clean_worktree`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `intelligence.control` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `IntelligenceHostEnvelopeV1`
- `LegalActionCandidateSetV1`

**Consumed contracts:**
- `DomainRead::eligibility_trace_checkpointV1`
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `DomainRead::neuron_state_checkpointV1`
- `LearningArtifactManifestV1`
- `ModulePort::context.compiler::intelligence.control`
- `ModulePort::intuition.policy::intelligence.control`
- `ModulePort::learning.eval::intelligence.control`
- `ModulePort::neuron.runtime::intelligence.control`
- `ModulePort::objective.compiler::intelligence.control`
- `ModulePort::prompt.optimizer::intelligence.control`
- `ModulePort::utility.ndu::intelligence.control`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `SupportAuditReceiptV1`

**Typed protocols:**
- `IntelligenceHostEnvelopeV1`
- `LearningArtifactManifestV1`
- `LegalActionCandidateSetV1`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `SupportAuditReceiptV1`

**Owned data domains:**
- None.

**Read data domains:**
- `eligibility_trace_checkpoint`
- `ndu_coefficient_manifest_v1`
- `ndu_preference_projection`
- `ndu_update_receipt_v1`
- `ndu_utility_projection`
- `ndu_well_posedness_certificate_v1`
- `neuron_state_checkpoint`
- `support_audit_receipt_v1`

**Work packages:**
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `INT-2-AGENTD-CODEX-COMPOSITION`
- `INTELLIGENCE-A0-Q0.63`

**Owned threats:**
- None.

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `intelligence.control` to primary lane `LANE-F-ADAPTIVE-POLICY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-OBJ`](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `ObjectiveCompileReceiptV1`
- `ObjectiveConflictReceiptV1`
- `ObjectiveSourceEnvelopeV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation remains implemented by `INTELLIGENCE-A0-Q0.63` in `codex-rs/hepta-intelligence`. The current candidate routes the named Agentd runner from authenticated `ObjectiveStart` through `AgentdState::start_canonical_intelligence`, binds the resulting envelope into the daemon-owned run/context lifecycle, and advertises the canonical capability only for that configured profile. Durable product Decision/Outcome process-loss recovery, exact physical App Server execution and target-host qualification remain pending; this source route alone is not deployment activation.

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml` and the Agentd process qualification, including package tests, all-target compilation, strict Clippy, formatting and deterministic merge qualification. Until exact-current-candidate receipts are terminal green, this guide claims source code presence only. It grants no production-writer, model/provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.


## 18. Product-closure source amendment

The exact generation/fence, host-owned provider, formal product-learning,
outbox/restart, canonical invariant, worker-isolation and telemetry contracts
are specified in [`PRODUCT_CLOSURE.md`](PRODUCT_CLOSURE.md). The stable tracked
`IMPLEMENTATION_MAP.json` and `TEST_TRACEABILITY.json` are generated by
`scripts/hepta-intelligence-control-status.py`; CI emits exact-head variants only
after executing the candidate and binds their commit to checkout `HEAD`.

This amendment changes the source claim from “runner present” to the following
separate facts: a concrete host-owned provider and atomic profile API exist; the
prepared run inherits the durable RunStart identity; bound admission rechecks
composition identity; formal Decision/Outcome writes use `LedgerWriter` behind
a durable operations outbox; and observability/hard-timeout policy are source
implemented. The ordinary CLI still lacks an authorized seven-owner factory and
therefore does not compose or advertise canonical intelligence by default.
Real-process provider/App Server E2E, target-host qualification, independent
acceptance, activation and release remain false until their exact receipts are
available.

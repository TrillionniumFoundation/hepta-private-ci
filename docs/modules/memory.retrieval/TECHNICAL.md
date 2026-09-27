# memory.retrieval technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `memory.retrieval`

**Owner:** `cognitive-platform`

**Deputy:** `performance`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-2-RETRIEVAL`

This is the current implementation entry point. Canonical JSON registries retain normative identity, ownership, contracts and authority. Source existence, source composition, exact-candidate execution, independent acceptance and production activation are separate facts. The predecessor guide is retained unchanged as [TECHNICAL_BASELINE.md](TECHNICAL_BASELINE.md), a historical reference, not the current process selector or implementation inventory.

## 1. Identity, mission and ownership

Produce bounded, explainable, source-revalidated local retrieval. The core is a read-only domain execution plant. It does not own content, source facts, signing keys, a durable learning writer or a new execution spine. `cognitive-platform` owns implementation correctness; `performance` independently reviews resource and boundary changes.

## 2. Source binding and implementation status

The exclusive module root is `codex-rs/hepta-memory-retrieval`. `v2.rs` retains the complete-input compatibility receipt. `generator.rs` binds owner batches, channel ranks, generation and completeness. `generation_bound.rs`, `semantics.rs` and `engram.rs` implement canonical union, policy admission, explicit propositions, bounded graph dynamics and recall. `decision.rs` binds enumerated/legal/selected identities. `vector_owner.rs` is a typed owner/encoder/index integration surface, not proof of a deployed encoder.

The SQLite adapter and assertion writer remain in `codex-rs/hepta-memory`; the signed process provider and consumer remain in `codex-rs/hepta-agentd`; assignment persistence remains in `learning.ledger`. Do not move their authority into this crate.

[IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) records source objects and claim boundaries. A map-only observation commit must refer to the preceding exact code/document commit and preserve immutable `sourceBase` provenance. A map or workflow definition is not a passing execution receipt.

## 3. Boundary, responsibilities and non-goals

Direct dependencies remain `cognitive.read` and `knowledge.graph`. Authoritative write domains: none. Explicitly denied capabilities are `write_authority` and `central_rpc_hot_path`. Receipts retain `AuthorityPosture::DENY_ALL`.

No model output, request field, content digest or public struct is an authority credential. Only the trusted owner/host composition establishes batch provenance. Unknown critical fields, scope/revision drift, malformed generations and invalid bounds fail closed. Existing tombstone, source correction and revocation rules cannot be bypassed through a cache or restored answer.

## 4. Internal architecture and component decomposition

The current path is owner cut and pre-top-four observation, exact binding, generator union, positive-score policy admission, HNMF recall, optional separately selected ranker, current source revalidation, bounded text materialization, context planning and learning-owner handoff. Explicit owner assertions are observed in the same SQLite transaction and evaluated across all admitted exact revisions; see [OWNER_PROPOSITIONS.md](OWNER_PROPOSITIONS.md).

HNMF operates on one immutable owner generation. Expansion, settling, sparse population competition, activation paths and contradiction disposition are bounded and deterministic. Zero activation produces no support; zero-weight edges are semantically inert. A conflict report is not an affirmative or negative assertion.

Multiscale DecisionCell/Recall circuits, shared-experience delivery and capacity/depth learning remain integration targets described by [DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md), [organ composition](../../cns/TECHNICAL.md), [HNMF](../../hnmf/TECHNICAL.md) and [longitudinal experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). Their existence does not upgrade current source or activation status.

## 5. Contracts, ports and compatibility

Produced: `ModulePort::memory.retrieval::prompt.optimizer`.

Consumed: `DomainRead::knowledge_graph_projectionV1`, `DomainRead::prompt_factor_graph_projectionV1`, `ModulePort::cognitive.read::memory.retrieval` and `ModulePort::knowledge.graph::memory.retrieval`.

[API.md](API.md) specifies native operations, strict decoding, errors and trust boundaries. The generation-bound legacy recall packet is not reinterpreted as the canonical cognitive recall wire. `adapt_generation_bound_recall_to_canonical_shadow_v1` remains shadow-only and requires an explicit exact identity bridge. Old digests/record IDs never become canonical event identities by relabelling.

The additive SQLite assertion contract is `structured_cognitive_propositions_v2`; legacy KG labels remain opaque. The ordinary bootstrap supports explicit v1/v2 descriptor semantics. V1 rejects v2 fields, including explicit null; V2 requires every rollout field. No partial-field fallback is allowed.

## 6. Data authority, persistence and migrations

This core has no durable facts or authoritative write domain. Its read-only domains are `knowledge_graph_projection` and `prompt_factor_graph_projection`.

The existing SQLite owner writes explicit assertions using the same cited-source, memory revision, immutable KG facts and projection transaction. Correcting or deleting a source does not leave an independent proposition database behind. The new contract retains all claims and exact validity/source support. A future real extractor must be admitted through the production writer; an owner-backend API is not that admission proof.

The independent frontier owner retains current epoch/sequence outside Agent-home rollback. The checked-in client and parse cache do not implement or qualify that external durable authority. `learning.ledger` remains the sole assignment writer. Prepared context, published response, acknowledged consumer use and outcome observation must not be collapsed into one fact.

## 7. Runtime, concurrency and transaction model

The core uses typed immutable input and no network or process-global state. SQLite observation is coherent within its owner transaction; final delivery still checks the current cut and selected record/source identities.

The signed provider returns context, publication lifecycle and lease together. Combined installation/acquisition performs one fresh challenged frontier observation. Parsing may be cached by exact publication bytes; signature, native validation, current frontier and monotonic lease remain checked. Invalid or missing current input does not fall back to a cached payload.

Current shadow ceilings are structural. Separate bounded scheduling, cancellation and measured CPU/RSS/allocation isolation remain unfinished and cannot be inferred from the four-mode enum or a node limit. Follow [shared concurrency requirements](../README.md#shared-concurrency-and-transactions).

## 8. Failure semantics, recovery and rollback

Distinguish malformed/stale input errors, unavailable owners, timed out work, explicit abstention, empty results and incomplete enumeration. `LimitReached` is not exhaustive absence. Required/selected-canary failures do not change the treatment arm. Optional shadow failure preserves the separately defined baseline but does not establish resource isolation.

Restart obtains a fresh challenged frontier. A local cached file or self-hash is not a recovery witness. Rollback is an approved new host launch/publication at an advancing frontier, never decrementing sequence or copying an old cache. See [operations](OPERATIONS.md), [canary and rollback](CANARY_AND_ROLLBACK.md) and [shared recovery requirements](../README.md#shared-failure-and-recovery).

## 9. Security, privacy and threat controls

[THREAT_MODEL.md](THREAT_MODEL.md) is the specific threat inventory. Protect exact source provenance, scope/purpose, pinned keys, lifecycle, cohort ownership and qualification evidence. Do not log private query text, raw memory, signing keys or raw rollout salts.

The process bootstrap requires protected canonical bounded files outside Agent home. Existing path checks assume actual launcher/UID/sandbox protection; they are not an atomic descriptor-relative path walk. A same-UID Agent with unrestricted filesystem access is not a qualified deployment. Fresh challenges defeat captured-response replay, not a legitimately keyed frontier owner that restored its own monotonic state incorrectly.

## 10. Performance, capacity and hot-path policy

Hard ceilings: 512 raw candidate events, 16 core selections, 4096 engram nodes, 32768 synapses, four settling steps and 64 active nodes per population. The current SQLite profile observes seven channels of at most 32 rows each, at most 224 raw owner events. The Agentd context endpoint separately delivers at most four items subject to bytes and planning.

Explicit assertion observation uses one parameterized batch query over exact observed revisions, not one additional SQL query per candidate. At most 128 claims per revision and 4096 per observation are accepted; overflow fails rather than truncates. The first implementation reconstructs the bounded canonical union for semantic admission; its cost is not hidden.

[POLICY_REFERENCE.md](POLICY_REFERENCE.md) distinguishes the uncalibrated SQLite baseline from a measured risk policy. OOD zero and a threshold of one are not calibration. [VECTOR_OWNER.md](VECTOR_OWNER.md) describes the real encoder/index seam; a configuration without that owner keeps Vector disabled.

Capacity invariants are not latency or efficiency measurements. [E2E_MEASUREMENT.md](E2E_MEASUREMENT.md) specifies the nine-stage contract, exact source/binary binding, failure traces and request-scoped counters. The complete native producer, approved workload/SLO and current-host measurements remain required.

## 11. Observability and operations

The ordinary Agentd selector is `HEPTA_COGNITIVE_RETRIEVAL_MODE`: absent/`compatibility`, `hnmf-shadow`, `hnmf-canary`, or `hnmf-required`. Compatibility forbids an attached HNMF provider. All HNMF modes require a current provider at startup. Shadow delivers baseline only; canary uses host-fixed versioned owner cohorts; required and selected canary reject invalid current context rather than downgrade.

Paired `--retrieval-bootstrap-descriptor` and `--retrieval-bootstrap-descriptor-digest` inputs compose the ordinary process. [PROCESS_BOOTSTRAP.md](PROCESS_BOOTSTRAP.md) and [ROLLOUT_POLICY.md](ROLLOUT_POLICY.md) specify exact field formats, raw-byte pins, signed publication, framing, v1 cohort continuity and complete v2 ppm/salt/shadow policy. Host-captured mode/policy and lifecycle bind final use. Request data cannot choose an arm, budget or key.

Retain exact source/tree, binary/build identity, mode, descriptor/policy/publication digests, owner/body/epoch/sequence, completeness, omission, abstention and final-use failures. Existing deployment references are [LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) and [LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

## 12. Verification and qualification

Core source tests: `generation_bound_tests.rs`, `generator_tests.rs`, `engram_tests.rs`, `semantics_tests.rs`, `decision_tests.rs` and vector-owner tests. Owner/consumer tests: `cognitive_retrieval_adapter_tests.rs`, `cognitive_proposition_owner_tests.rs`, `cognitive_context_hnmf_tests.rs`, provider/acquisition/bootstrap/cache/transport tests and learning-ledger durable tests.

In `codex-rs`, run `just test --locked -p codex-hepta-memory-retrieval -p codex-hepta-memory -p codex-hepta-agentd -p codex-hepta-learning-ledger`, all-target checks, strict Clippy and repository formatting. Verify current source-head and ordered-parent current-main merge candidates. Missing, skipped, queued, cancelled and failed checks are not successful qualifications.

The consolidated and retrieval-specific workflows retain exact-candidate results. Structural host probes and historical archives are not current-head end-to-end measurements. No fixture label, parser success, formatting pass or artifact existence proves native product execution or independent acceptance. See [shared verification](../README.md#shared-verification-and-qualification).

## 13. Implementation sequence and work packages

`MEM-2-RETRIEVAL` remains the bootstrap package. Development predecessor: `MEM-0-TYPES`. Activation predecessor: `MEM-1-STORE`. Preserve existing owners and implement through their explicit boundaries; ordinary authorized coding does not need a new deployment capability envelope.

Advance source correctness/verification, then protected runtime/recovery and cancellation, then real measurement/calibration, then independently accepted rollout. Do not build a second architecture or use failing native checks as a reason to weaken gates. Current unfinished items are recorded in the implementation map and [owner-proposition amendment](OWNER_PROPOSITIONS.md).

## 14. Activation, compatibility and retirement

Source-composed four-mode routing and process bootstrap are not activation evidence. Require the protected launcher, durable independent frontier, real producer/consumer chain, calibrated selected profile and current target-host evidence. Vector is a separate explicit capability profile, not a renamed lexical score.

Retiring a compatibility path requires migrated callers, current exact-candidate tests, rehearsed rollback and independent acceptance. Preserve historical receipts and old-wire interpretability. Mode/policy rollback uses an advancing authorized publication and does not erase unknown consumption.

## 15. Definition of module completion

Documentation closure means accurate linked specifications and registry references. Source closure means implemented code, matching public boundaries and green current source/merge tests. Product execution needs the actual named consumer and durable lifecycle evidence. Acceptance, activation, promotion and release require their own independently governed receipts.

`productionImplementation=false`, `productExecutionProved=false`, `independentAcceptance=false`, `activation=false`, `release=false` remain the present claim boundary. No document, source change or local validator grants runtime authority.

## 16. V8.2 pre-coding implementation-readiness overlay

Primary lane remains `LANE-C-MEMORY`. Required overlays: [RDY-SRC](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md), [RDY-PAR](../../readiness/PARALLEL_DEVELOPMENT.md) and [RDY-EMB](../../readiness/EMBODIED_RUNTIME_EXECUTION.md). Owned/consumed readiness protocols: none. Identify exact baseline, owned paths, mandatory tests, failure/rollback and unchanged authority before editing.

## 17. Source implementation receipt

The declared source root exists and native operations can be inspected. This is a source-location statement, not a passing command result. `.github/workflows/hepta-consolidated-source.yml` and retrieval qualification workflows establish execution only when current receipts actually complete successfully. The canonical HNMF adapter remains a shadow migration surface until named downstream owners are migrated and independently qualified.

# intelligence.control: implementation design

Parent: `docs/modules/intelligence.control/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: read-only vertical, signed evaluated-shadow composition, and the authority-free V3 unified composition graph are source implemented; Agentd has a named host-admission caller. Product execution, live effect execution and independent acceptance remain unproved and are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence`.
Packages: `INTELLIGENCE-A0-Q0.63`, `INT-2-AGENTD-CODEX-COMPOSITION`, `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`prepare_intelligence_run_v3(request, owner_ports, control) -> CompositionPipelineReceiptV3` is the native unified composition operation. `build_legal_candidates(request) -> LegalActionCandidateSetV1` materializes the registered bounded legal-set contract. A successful V3 run carries `IntelligenceHostEnvelopeV1`; Agentd consumes that envelope through `admit_intelligence_run_v1` and stops at `ContextAttached`. The older design names `prepare_intelligence_run`, `decide_boundary` and `assemble_context` remain semantic design labels, not additional native facades. Facts and effect execution remain with their registered owners.

## 3. State records and transaction design

Ephemeral orchestration state only: run/boundary identity, frozen owner snapshots, bounded port handles, pending observations and receipt references. Objective/NDU/neural/prompt/learning/artifact records remain in their separate owners. The facade must not introduce a hidden all-purpose JSON/SQL store or a parallel model-call loop.

## 4. Deterministic algorithm and scheduling

V3 orders one frozen-snapshot predecessor chain as objective validation -> legal candidate construction -> NDU utility evaluation -> independent evaluation admission -> optional neural signal -> optional prompt portfolio -> calibrated intuition -> context compilation. A successful graph prepares `IntelligenceHostEnvelopeV1`; Agentd separately admits it and attaches context before any Codex dispatch. Neural and prompt may use explicit unavailable/timed-out fallback; objective, utility, evaluation and context fail closed; intuition alone may abstain or request slow path. No stage converts missing evidence into success.

## 5. Capacity and performance profile

Pilot <=128 candidates, bounded receipt/evidence set and per-stage deadline derived from the run budget. Total budget reserves evidence/recovery floors before cognition. Record critical path, stage omissions/fallbacks, scope/generation mismatches and foreground resource cost.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- IC-01: deterministic C1 traverses actual host ports and produces a read-only report with no Memory/KG/tool mutation.
- IC-02: each dependency outage triggers the declared bounded fallback or abstention.
- IC-03: mixed snapshot or compiled-but-undelivered prompt cannot produce a valid success/learning receipt.
- IC-04: new-process selected-artifact load changes future behavior and an exact compatible rollback restores the predecessor behavior under current revocations.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 is an end-to-end milestone, not a sum of independently green library tests. Existing development/activation/evidence predecessors stay enforced; a simpler slice needs an explicit reviewed package change. The facade owns neither acceptance nor release.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `run_read_only_vertical` in [codex-rs/hepta-intelligence/src/vertical.rs](../../../codex-rs/hepta-intelligence/src/vertical.rs); `run_evaluated_shadow_v1` in [codex-rs/hepta-intelligence/src/evaluated_shadow.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow.rs); `prepare_intelligence_run_v3` and `build_legal_candidates` in [codex-rs/hepta-intelligence/src/composition_v3.rs](../../../codex-rs/hepta-intelligence/src/composition_v3.rs); `append_outcome_and_credit_v1` in [codex-rs/hepta-intelligence/src/learning_closure.rs](../../../codex-rs/hepta-intelligence/src/learning_closure.rs). Agentd's named host-admission caller is `admit_intelligence_run_v1` in [codex-rs/hepta-agentd/src/intelligence_control.rs](../../../codex-rs/hepta-agentd/src/intelligence_control.rs).
- **Unified V3 graph:** objective validation, bounded legal-set construction, NDU utility, independent evaluation admission, optional neuron, optional prompt, intuition and context share one `CapabilitySnapshotV2` digest and one predecessor chain. The graph produces an authority-free `IntelligenceHostEnvelopeV1`; it does not dispatch Codex or execute an effect.
- **Deadline/cancellation semantics:** V3 checks run cancellation and absolute run deadlines between stages, gives each port an absolute stage deadline and rejects a required-stage late success as `TimedOut`. The synchronous trait cannot preempt a blocked adapter; a selected host must wrap blocking I/O with its own cancellable timeout and return only after the underlying work is safely fenced.
- **State and recovery:** The read-only vertical remains stateless. Evaluated shadow verifies signed evidence and appends a durable Decision. `append_outcome_and_credit_v1` accepts only host-supplied terminal observations and allocations and appends Outcome then Credit through the existing sealed `DurableLearningJournal`; it never invents either fact.
- **Product host boundary:** Agentd now has a source-level consumer that validates the V3 receipt/envelope, calls its existing `AgentRunCoordinator::start_run`, attaches the compiled context, and deliberately stops at `ContextAttached`. Codex dispatch remains on the existing Agentd/App Server path and is not authorized by the intelligence envelope.
- **Source tests:** [codex-rs/hepta-intelligence/src/vertical_tests.rs](../../../codex-rs/hepta-intelligence/src/vertical_tests.rs), [codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs), [codex-rs/hepta-intelligence/src/composition_v3_tests.rs](../../../codex-rs/hepta-intelligence/src/composition_v3_tests.rs), [codex-rs/hepta-intelligence/tests/composition_v3_native.rs](../../../codex-rs/hepta-intelligence/tests/composition_v3_native.rs), [codex-rs/hepta-agentd/src/intelligence_control_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_control_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-intelligence/EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md).
- **Remaining work:** exact-head and synthetic-merge qualification must pass for the candidate; production must supply current authenticated owner inputs/keys, real calibration/OOD/evaluation observations and cancellable host adapters. Live Codex/model/tool/effect execution, operator acceptance, canary/promotion/release and longitudinal benefit evidence remain outside these source entrypoints.

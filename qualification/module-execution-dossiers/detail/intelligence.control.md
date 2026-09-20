# intelligence.control: implementation design

Parent: `docs/modules/intelligence.control/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: canonical V3 source composition, current-owner adapters, typed Agentd runtime handoff, durable Decision/Outcome/Credit closure, read-only vertical and signed evaluated-shadow compatibility paths are implemented in source; exact-candidate product execution, target-host observation and independent acceptance remain gated in section 8.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence`.
Packages: `INTELLIGENCE-A0-Q0.63`, `INT-2-AGENTD-CODEX-COMPOSITION`, `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`build_legal_candidates_v1(...) -> LegalActionCandidateSetV1`; `run_composition_v3(request, ports) -> LaneFCompositionReceiptV3`; `run_composition_v3_with_control(request, ports, control) -> LaneFCompositionReceiptV3`; and product-side `AgentRunCoordinator::run_native_intelligence_v3(...) -> IntelligenceRunReceiptV3` are the current convergence surfaces. The older design-operation names remain vocabulary, not separate facades. Facts and execution remain with their registered owners.

## 3. State records and transaction design

Ephemeral orchestration state only: run/boundary identity, frozen owner snapshots, bounded port handles, pending observations and receipt references. Objective/NDU/neural/prompt/learning/artifact records remain in their separate owners. The facade must not introduce a hidden all-purpose JSON/SQL store or a parallel model-call loop.

## 4. Deterministic algorithm and scheduling

Compile immutable objective; acquire coherent memory/body evidence; build the complete bounded legal set; obtain NDU and qualified neural signals; price/select prompt portfolio; run calibrated intuition or deterministic slow path; compile source-aware context; hand to agentd/Codex; route independent outcomes to the ledger. Each stage has typed unavailable/conflict/abstain fallbacks; no stage converts missing evidence into a successful result.

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

- **Implemented entrypoints:** `run_read_only_vertical` in [vertical.rs](../../../codex-rs/hepta-intelligence/src/vertical.rs); `run_evaluated_shadow_v1` in [evaluated_shadow.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow.rs); `build_legal_candidates_v1` in [contracts_v1.rs](../../../codex-rs/hepta-intelligence/src/contracts_v1.rs); `run_composition_v3` and `run_composition_v3_with_control` in [pipeline_v3.rs](../../../codex-rs/hepta-intelligence/src/pipeline_v3.rs); and `append_outcome_credit_v1` in [outcome_credit.rs](../../../codex-rs/hepta-intelligence/src/outcome_credit.rs). V1/V2 remain compatibility surfaces rather than a fourth facade.
- **Canonical V3 graph:** objective admission -> native legal set -> policy-bound NDU -> signed independent evaluation -> optional sparse Neuron -> optional prompt portfolio -> calibrated Intuition V2 -> context -> native host envelope -> Agentd handoff -> durable learning Decision. Every external stage is tied to the same frozen `CapabilitySnapshotV2` and carries the exact selected capability ID, implementation digest and generation through its request/receipt boundary.
- **Current-owner adapters:** [native_ports_v3.rs](../../../codex-rs/hepta-intelligence/src/native_ports_v3.rs) uses `admit_and_compile_objective_v1`, `evaluate_candidates_with_policy`, `decide_with_signed_evidence_v2`, optional `sparse_tick` / prompt `optimize`, `decide_calibrated_v2`, the context compiler, and the sealed `DurableLearningJournal`. The adapter does not invoke Codex, tools, providers or physical effects.
- **Native produced contracts and product caller:** [contracts_v1.rs](../../../codex-rs/hepta-intelligence/src/contracts_v1.rs) implements bounded `LegalActionCandidateSetV1` and authority-free `IntelligenceHostEnvelopeV1`. [codex-rs/hepta-agentd/src/intelligence_host.rs](../../../codex-rs/hepta-agentd/src/intelligence_host.rs) validates the typed handoff; `AgentRunCoordinator::run_native_intelligence_v3` in [lane_b_runtime.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime.rs) is the registered runtime callsite and performs the real run-state attach. This source callsite is not itself product-execution evidence.
- **Deadline/cancellation:** V3 checks cooperative cancellation, absolute run deadline, derived absolute stage deadline and monotonic elapsed budgets before and after synchronous owner calls. A blocked call cannot be preempted by this coordinator; the selected adapter/host must enforce the supplied absolute deadline at the blocking I/O boundary. A successful durable/visible handoff or ledger append is not retroactively relabeled as failure when cancellation is observed afterward.
- **Post-execution closure:** `append_outcome_credit_v1` writes terminal Outcome then Credit through the sealed learning ledger and preserves a committed Outcome receipt if Credit fails. `AgentRunCoordinator::observe_intelligence_terminal_and_record` first records the Agentd-owned terminal observation and then invokes that learning closure, retaining the runtime receipt on learning failure for reconciliation.
- **Source tests:** [pipeline_v3_tests.rs](../../../codex-rs/hepta-intelligence/src/pipeline_v3_tests.rs), [native_ports_v3_tests.rs](../../../codex-rs/hepta-intelligence/src/native_ports_v3_tests.rs), [vertical_tests.rs](../../../codex-rs/hepta-intelligence/src/vertical_tests.rs), [evaluated_shadow_tests.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs), [outcome_credit.rs](../../../codex-rs/hepta-intelligence/src/outcome_credit.rs), [codex-rs/hepta-agentd/src/intelligence_host.rs](../../../codex-rs/hepta-agentd/src/intelligence_host.rs) and [lane_b_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs). These are source identities, not exact-candidate product execution receipts.
- **Operating references:** [V3_COMPOSITION.md](../../../codex-rs/hepta-intelligence/V3_COMPOSITION.md) and [EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md).
- **Remaining repository closure:** execute the named `AgentRunCoordinator::run_native_intelligence_v3` callsite with authenticated current owner facts and the exact selected implementation generations, observe actual Codex delivery/terminal outcomes, exercise Outcome/Credit reconciliation, and pass exact-head plus deterministic synthetic-merge qualification. Independent acceptance, target-host canary, promotion and release remain external gates.

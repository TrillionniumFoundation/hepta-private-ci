# intelligence.control: implementation design

Parent: `docs/modules/intelligence.control/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: read-only vertical and signed evaluated-shadow composition implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence`.
Packages: `INTELLIGENCE-A0-Q0.63`, `INT-2-AGENTD-CODEX-COMPOSITION`, `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`prepare_intelligence_run(request, owner_ports, frozen_snapshot) -> IntelligenceHostEnvelopeV1`; `build_legal_candidates(objective, body, supported_skills) -> LegalActionCandidateSetV1`; `decide_boundary(run, observations) -> AdvisoryDecision`; `assemble_context(decision, evidence) -> ContextCompilationReceiptV1`. These are composition operations; facts and execution remain with their registered owners.

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

- **Implemented entrypoints:** `run_read_only_vertical` in [codex-rs/hepta-intelligence/src/vertical.rs](../../../codex-rs/hepta-intelligence/src/vertical.rs); `run_evaluated_shadow_v1` in [codex-rs/hepta-intelligence/src/evaluated_shadow.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow.rs); and canonical `run_composition_v3` / `run_composition_v3_with_control` in [codex-rs/hepta-intelligence/src/pipeline_v3.rs](../../../codex-rs/hepta-intelligence/src/pipeline_v3.rs). V1/V2 remain compatibility surfaces rather than a fourth facade.
- **V3 graph:** objective -> native legal set -> utility/NDU -> independent evaluation -> optional neuron -> optional prompt -> intuition -> context -> native host envelope -> agentd handoff -> learning ledger. Utility and evaluation now have explicit typed stages in the predecessor chain. The graph admits one `CapabilitySnapshotV2` and checks registered owners before invoking ports.
- **Native contracts and product consumer:** [contracts_v1.rs](../../../codex-rs/hepta-intelligence/src/contracts_v1.rs) implements `LegalActionCandidateSetV1` and `IntelligenceHostEnvelopeV1`; [codex-rs/hepta-agentd/src/intelligence_host.rs](../../../codex-rs/hepta-agentd/src/intelligence_host.rs) is the typed runtime.agentd consumer. The handoff grants no model/tool/effect authority.
- **State and recovery:** The vertical derives cross-stage objective/read/context/NDU bindings in one call. Evaluated shadow additionally verifies signed evidence and appends a decision through the existing DurableLedger. V3 stays ephemeral and binds owner receipts by snapshot/predecessor digest; it does not create another model loop or cognitive writer.
- **Deadline/cancellation:** V3 checks cooperative cancellation and real wall-clock elapsed time before and after each synchronous owner port. A blocked port cannot be preempted by this coordinator; each proposal-only adapter must enforce its supplied deadline at its own I/O boundary.
- **Source tests:** [codex-rs/hepta-intelligence/src/pipeline_v3_tests.rs](../../../codex-rs/hepta-intelligence/src/pipeline_v3_tests.rs), [codex-rs/hepta-intelligence/src/vertical_tests.rs](../../../codex-rs/hepta-intelligence/src/vertical_tests.rs), [codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs), and the agentd consumer unit tests in [codex-rs/hepta-agentd/src/intelligence_host.rs](../../../codex-rs/hepta-agentd/src/intelligence_host.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-intelligence/V3_COMPOSITION.md](../../../codex-rs/hepta-intelligence/V3_COMPOSITION.md), [codex-rs/hepta-intelligence/EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md).
- **Remaining work:** Exact-candidate CI must prove the new source tree and synthetic merge. A production runtime callsite must still supply authenticated current owner inputs, real calibration/evaluation observations, Codex delivery evidence and durable Outcome/Credit handling. Independent acceptance, canary, promotion and release remain separate gates.

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

- **Implemented entrypoints:** `run_read_only_vertical` in [codex-rs/hepta-intelligence/src/vertical.rs](../../../codex-rs/hepta-intelligence/src/vertical.rs); `run_evaluated_shadow_v1` in [codex-rs/hepta-intelligence/src/evaluated_shadow.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow.rs); and additive `prepare_intelligence_run_v3` in [codex-rs/hepta-intelligence/src/composition_v3.rs](../../../codex-rs/hepta-intelligence/src/composition_v3.rs). V1/V2 remain compatibility surfaces; V3 is the converged new integration path.
- **V3 graph:** objective validation -> legal candidate set -> NDU utility -> optional neuron -> optional prompt portfolio -> calibrated intuition -> context compilation -> independent evaluation admission -> durable Decision record. Every stage is snapshot/predecessor/evidence bound and remains authority-free.
- **Native owner adapters:** [codex-rs/hepta-intelligence/src/native_v3.rs](../../../codex-rs/hepta-intelligence/src/native_v3.rs) calls the actual objective, NDU, neuron, prompt, intuition, context, evaluation and sealed learning-journal libraries. Optional capability absence is represented as a bounded fallback, never a fabricated receipt.
- **Produced native contracts:** `LegalActionCandidateSetV1` and `IntelligenceHostEnvelopeV1`. The final host envelope is emitted only for a selected path after the durable Decision record; the canonical JSON field shape for the host envelope is registered in `docs/contracts/PROTOCOL_SCHEMAS.json`.
- **Named Agentd consumer:** [codex-rs/hepta-agentd/src/intelligence_facade.rs](../../../codex-rs/hepta-agentd/src/intelligence_facade.rs) validates the envelope, starts the existing Agentd run with the frozen tuple, attaches the exact context receipt and marks dispatch only through the existing runtime transition.
- **State and recovery:** The facade remains ephemeral. Decision, Outcome and Credit stay with `learning.ledger`. [codex-rs/hepta-intelligence/src/learning_v3.rs](../../../codex-rs/hepta-intelligence/src/learning_v3.rs) appends caller-supplied terminal Outcome and linked Credit after dispatch; exact retries rely on the existing durable-journal idempotency rather than synthesizing or rolling back observations.
- **Deadline/cancellation:** V3 reserves evidence/recovery floors, validates the total horizon and records cancellation/deadline terminal traces before and after bounded local owner calls. It does not move model/tool/effect I/O into the synchronous facade; Agentd/Codex retains that execution lifecycle.
- **Source tests:** [vertical_tests.rs](../../../codex-rs/hepta-intelligence/src/vertical_tests.rs), [evaluated_shadow_tests.rs](../../../codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs), [composition_v3_tests.rs](../../../codex-rs/hepta-intelligence/src/composition_v3_tests.rs), [native_v3_tests.rs](../../../codex-rs/hepta-intelligence/src/native_v3_tests.rs), [learning_v3_tests.rs](../../../codex-rs/hepta-intelligence/src/learning_v3_tests.rs), and [Agentd intelligence_facade_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_facade_tests.rs). These are source test identities until exact-candidate execution completes.
- **Implementation and operating references:** [codex-rs/hepta-intelligence/EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md) and [codex-rs/hepta-intelligence/V3_COMPOSITION.md](../../../codex-rs/hepta-intelligence/V3_COMPOSITION.md).
- **Remaining work outside this source change:** current exact-head and deterministic merge-candidate execution, independent semantic review, admitted target-host product execution, operator acceptance/canary/promotion/release, and empirical long-term benefit evidence. No source test or envelope grants those states.

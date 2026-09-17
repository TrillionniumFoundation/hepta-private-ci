use super::*;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;
use crate::LegalActionCandidateV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn capability_snapshot(include_optional: bool) -> CapabilitySnapshotV2 {
    let required = [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("learning.evaluation", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.envelope", "intelligence.control"),
        ("dispatch.proposal", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ];
    let optional = [
        ("neural.signal", "neuron.runtime"),
        ("prompt.portfolio", "prompt.optimizer"),
    ];
    let mut requirements = Vec::new();
    let mut bindings = Vec::new();
    for (capability, owner) in required {
        let contract = digest(&format!("contract:{capability}"));
        requirements.push(CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: contract,
            necessity: CapabilityNecessityV2::Required,
        });
        bindings.push(CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: contract,
            implementation_digest: digest(&format!("implementation:{owner}")),
            generation: Generation::new(/*value*/ 1).expect("generation"),
        });
    }
    if include_optional {
        for (capability, owner) in optional {
            let contract = digest(&format!("contract:{capability}"));
            requirements.push(CapabilityRequirementV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                necessity: CapabilityNecessityV2::Optional,
            });
            bindings.push(CapabilityBindingV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                implementation_digest: digest(&format!("implementation:{owner}")),
                generation: Generation::new(/*value*/ 1).expect("generation"),
            });
        }
    }
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 1,
        body_generation: Generation::new(/*value*/ 1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("capability snapshot")
}

fn request(include_optional: bool) -> LaneFCompositionRequestV3 {
    let snapshot = capability_snapshot(include_optional);
    let legal_candidates = LegalActionCandidateSetV1::new(
        id("candidate-set"),
        snapshot.digest(),
        id("intelligence.control"),
        digest("grammar"),
        vec![LegalActionCandidateV1 {
            candidate_id: id("action.read"),
            action_digest: digest("action.read"),
            support_digest: digest("legal-support"),
        }],
        1,
    )
    .expect("legal candidate set");
    LaneFCompositionRequestV3 {
        run_id: id("run:v3"),
        request_digest: digest("request"),
        snapshot,
        legal_candidates,
        budget: LaneFCompositionBudgetV3 {
            total_micros: 11_000,
            objective_micros: 1_000,
            legal_set_micros: 1_000,
            utility_micros: 1_000,
            evaluation_micros: 1_000,
            neural_micros: 1_000,
            prompt_micros: 1_000,
            intuition_micros: 1_000,
            context_micros: 1_000,
            envelope_micros: 1_000,
            dispatch_micros: 1_000,
            ledger_micros: 1_000,
        },
    }
}

#[derive(Default)]
struct FakeClock {
    now: u64,
    step: u64,
}

impl CompositionClockV3 for FakeClock {
    fn now_micros(&mut self) -> u64 {
        let current = self.now;
        self.now = self.now.saturating_add(self.step);
        current
    }
}

#[derive(Clone, Copy, Default)]
struct Cancellation(bool);

impl CompositionCancellationV3 for Cancellation {
    fn is_cancelled(&self) -> bool {
        self.0
    }
}

#[derive(Default)]
struct Ports {
    calls: Vec<LaneFStageV3>,
    intuition: Option<PortDecisionV1>,
}

impl Ports {
    fn call(
        &mut self,
        input: &PortInputV3,
        producer: &str,
        decision: PortDecisionV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.calls.push(input.stage);
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            candidate_set_digest: input.candidate_set_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: digest(&format!("{producer}:{:?}", input.stage)),
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl LaneFCompositionPortsV3 for Ports {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "objective.compiler", PortDecisionV1::Continue)
    }

    fn evaluate_utility(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "utility.ndu", PortDecisionV1::Continue)
    }

    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "learning.eval", PortDecisionV1::Continue)
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "neuron.runtime", PortDecisionV1::Continue)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "prompt.optimizer", PortDecisionV1::Continue)
    }

    fn decide_intuition(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(
            input,
            "intuition.policy",
            self.intuition.unwrap_or(PortDecisionV1::Continue),
        )
    }

    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "context.compiler", PortDecisionV1::Continue)
    }

    fn propose_dispatch(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "runtime.agentd", PortDecisionV1::Continue)
    }

    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "learning.ledger", PortDecisionV1::Continue)
    }
}

#[test]
fn v3_orders_utility_and_evaluation_inside_one_bound_graph() {
    let mut ports = Ports::default();
    let mut clock = FakeClock {
        step: 1,
        ..FakeClock::default()
    };
    let receipt = run_composition_v3(
        request(/*include_optional*/ true),
        &mut ports,
        &mut clock,
        &Cancellation::default(),
    )
    .expect("V3 composition");
    assert_eq!(receipt.disposition, CompositionDispositionV3::DispatchProposed);
    assert_eq!(receipt.stages.len(), 11);
    assert_eq!(receipt.stages[2].stage, LaneFStageV3::UtilityEvaluated);
    assert_eq!(receipt.stages[3].stage, LaneFStageV3::EvaluationAdmitted);
    assert!(receipt.host_envelope.is_some());
    receipt.validate().expect("receipt validation");
}

#[test]
fn absent_neural_and_prompt_capabilities_are_explicit_fallbacks() {
    let mut ports = Ports::default();
    let mut clock = FakeClock::default();
    let receipt = run_composition_v3(
        request(/*include_optional*/ false),
        &mut ports,
        &mut clock,
        &Cancellation::default(),
    )
    .expect("V3 composition without optional capabilities");
    assert!(!ports.calls.contains(&LaneFStageV3::NeuralSignalCollected));
    assert!(!ports.calls.contains(&LaneFStageV3::PromptPortfolioBuilt));
    assert_eq!(
        receipt.stages[4].outcome,
        StageOutcomeV3::FallbackUsed(PortFailureClassV1::Unavailable)
    );
    assert_eq!(
        receipt.stages[5].outcome,
        StageOutcomeV3::FallbackUsed(PortFailureClassV1::Unavailable)
    );
}

#[test]
fn abstention_skips_context_envelope_and_dispatch_but_records_learning() {
    let mut ports = Ports {
        intuition: Some(PortDecisionV1::Abstain),
        ..Ports::default()
    };
    let mut clock = FakeClock::default();
    let receipt = run_composition_v3(
        request(/*include_optional*/ false),
        &mut ports,
        &mut clock,
        &Cancellation::default(),
    )
    .expect("abstention");
    assert_eq!(receipt.disposition, CompositionDispositionV3::Abstained);
    assert_eq!(receipt.host_envelope, None);
    assert!(!ports.calls.contains(&LaneFStageV3::ContextCompiled));
    assert!(!ports.calls.contains(&LaneFStageV3::DispatchProposed));
    assert_eq!(ports.calls.last(), Some(&LaneFStageV3::LearningRecorded));
}

#[test]
fn stage_wall_clock_overrun_fails_closed() {
    let mut ports = Ports::default();
    let mut clock = FakeClock {
        step: 2_000,
        ..FakeClock::default()
    };
    let receipt = run_composition_v3(
        request(/*include_optional*/ true),
        &mut ports,
        &mut clock,
        &Cancellation::default(),
    )
    .expect("timeout is a receipted terminal state");
    assert_eq!(
        receipt.disposition,
        CompositionDispositionV3::Failed(PortFailureClassV1::TimedOut)
    );
    assert_eq!(receipt.stages.len(), 1);
}

#[test]
fn cancellation_before_first_owner_boundary_is_receipted() {
    let mut ports = Ports::default();
    let mut clock = FakeClock::default();
    let receipt = run_composition_v3(
        request(/*include_optional*/ true),
        &mut ports,
        &mut clock,
        &Cancellation(true),
    )
    .expect("cancellation receipt");
    assert_eq!(receipt.disposition, CompositionDispositionV3::Cancelled);
    assert_eq!(receipt.stages[0].outcome, StageOutcomeV3::Cancelled);
    assert!(ports.calls.is_empty());
}

#[test]
fn legal_candidate_set_must_bind_the_exact_capability_snapshot() {
    let mut value = request(/*include_optional*/ false);
    value.legal_candidates = LegalActionCandidateSetV1::new(
        id("candidate-set"),
        digest("different-snapshot"),
        id("intelligence.control"),
        digest("grammar"),
        Vec::new(),
        0,
    )
    .expect("candidate set");
    let mut ports = Ports::default();
    let mut clock = FakeClock::default();
    assert_eq!(
        run_composition_v3(value, &mut ports, &mut clock, &Cancellation::default()),
        Err(CompositionErrorV3::CandidateSnapshotMismatch)
    );
}

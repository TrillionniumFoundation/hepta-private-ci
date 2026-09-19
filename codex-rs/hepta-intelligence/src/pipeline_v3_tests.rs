use super::*;
use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;
use crate::LegalActionCandidateV1;
use crate::build_legal_candidates_v1;
use codex_hepta_types::Generation;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn capability_snapshot(with_optional: bool) -> CapabilitySnapshotV2 {
    let mut pairs = vec![
        (
            "objective.validation",
            "objective.compiler",
            CapabilityNecessityV2::Required,
        ),
        (
            "legal.actions",
            "intelligence.control",
            CapabilityNecessityV2::Required,
        ),
        (
            "utility.evaluation",
            "utility.ndu",
            CapabilityNecessityV2::Required,
        ),
        (
            "learning.evaluation",
            "learning.eval",
            CapabilityNecessityV2::Required,
        ),
        (
            "intuition.decision",
            "intuition.policy",
            CapabilityNecessityV2::Required,
        ),
        (
            "context.compilation",
            "context.compiler",
            CapabilityNecessityV2::Required,
        ),
        (
            "host.handoff",
            "runtime.agentd",
            CapabilityNecessityV2::Required,
        ),
        (
            "learning.record",
            "learning.ledger",
            CapabilityNecessityV2::Required,
        ),
    ];
    if with_optional {
        pairs.extend([
            (
                "neural.signal",
                "neuron.runtime",
                CapabilityNecessityV2::Optional,
            ),
            (
                "prompt.portfolio",
                "prompt.optimizer",
                CapabilityNecessityV2::Optional,
            ),
        ]);
    }
    let requirements = pairs
        .iter()
        .map(|(capability, owner, necessity)| CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: *necessity,
        })
        .collect::<Vec<_>>();
    let bindings = pairs
        .iter()
        .map(|(capability, owner, _)| CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            implementation_digest: digest(&format!("implementation:{owner}")),
            generation: Generation::new(1).expect("generation"),
        })
        .collect::<Vec<_>>();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 1,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("capability snapshot")
}

fn request(with_optional: bool) -> LaneFRunRequestV3 {
    let snapshot = capability_snapshot(with_optional);
    let candidates = build_legal_candidates_v1(
        id("candidate-set"),
        snapshot.digest(),
        digest("grammar"),
        700_000,
        vec![LegalActionCandidateV1 {
            candidate_id: id("action.read"),
            action_digest: digest("action"),
            support_digest: digest("support"),
            support_ppm: 900_000,
        }],
    )
    .expect("legal candidates");
    LaneFRunRequestV3 {
        run_id: id("run:v3"),
        request_digest: digest("request"),
        snapshot,
        legal_candidates: candidates,
        budget: LaneFBudgetV3 {
            total_micros: 22_000_000,
            objective_micros: 2_000_000,
            legal_set_micros: 2_000_000,
            utility_micros: 2_000_000,
            evaluation_micros: 2_000_000,
            neural_micros: 2_000_000,
            prompt_micros: 2_000_000,
            intuition_micros: 2_000_000,
            context_micros: 2_000_000,
            envelope_micros: 2_000_000,
            host_handoff_micros: 2_000_000,
            ledger_micros: 2_000_000,
        },
    }
}

#[derive(Default)]
struct Ports {
    calls: Vec<LaneFStageV3>,
    fail: Option<(LaneFStageV3, PortFailureClassV3)>,
    intuition: PortDecisionV3,
    accepted_envelope: Option<Digest32>,
}

impl Ports {
    fn call(
        &mut self,
        input: &PortInputV3,
        producer: &str,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.calls.push(input.stage);
        if let Some((stage, class)) = self.fail
            && stage == input.stage
        {
            return Err(PortFailureV3 {
                class,
                evidence_digest: digest(&format!("failure:{stage:?}")),
            });
        }
        let output_digest = if input.stage == LaneFStageV3::ObjectiveValidated {
            digest("objective")
        } else {
            digest(&format!("output:{stage:?}", stage = input.stage))
        };
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            decision: if input.stage == LaneFStageV3::IntuitionDecided {
                self.intuition
            } else {
                PortDecisionV3::Continue
            },
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl LaneFV3Ports for Ports {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "objective.compiler")
    }

    fn evaluate_utility(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "utility.ndu")
    }

    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "learning.eval")
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "neuron.runtime")
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "prompt.optimizer")
    }

    fn decide_intuition(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "intuition.policy")
    }

    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "context.compiler")
    }

    fn accept_host_envelope(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        envelope.validate().expect("valid host envelope");
        assert_eq!(input.predecessor_digest, envelope.envelope_digest);
        self.accepted_envelope = Some(envelope.envelope_digest);
        self.call(input, "runtime.agentd")
    }

    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.call(input, "learning.ledger")
    }
}

impl Default for PortDecisionV3 {
    fn default() -> Self {
        Self::Continue
    }
}

#[test]
fn v3_baseline_routes_seven_owner_ports_and_records_optional_absence() {
    let mut ports = Ports::default();
    let receipt = run_composition_v3(request(false), &mut ports).expect("V3 composition");
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV3::HostHandoffAccepted
    );
    assert_eq!(ports.calls.len(), 7);
    assert!(!ports.calls.contains(&LaneFStageV3::NeuralSignalCollected));
    assert!(!ports.calls.contains(&LaneFStageV3::PromptPortfolioBuilt));
    assert!(receipt.stages.iter().any(|trace| {
        trace.stage == LaneFStageV3::NeuralSignalCollected
            && trace.outcome == StageOutcomeV3::FallbackUsed(PortFailureClassV3::Unavailable)
    }));
    assert!(receipt.stages.iter().any(|trace| {
        trace.stage == LaneFStageV3::PromptPortfolioBuilt
            && trace.outcome == StageOutcomeV3::FallbackUsed(PortFailureClassV3::Unavailable)
    }));
    let envelope = receipt.host_envelope.as_ref().expect("host envelope");
    assert_eq!(ports.accepted_envelope, Some(envelope.envelope_digest));
    receipt.validate().expect("valid receipt");
}

#[test]
fn v3_full_capability_snapshot_routes_nine_owner_ports() {
    let mut ports = Ports::default();
    let receipt = run_composition_v3(request(true), &mut ports).expect("V3 composition");
    assert_eq!(ports.calls.len(), 9);
    assert!(ports.calls.contains(&LaneFStageV3::NeuralSignalCollected));
    assert!(ports.calls.contains(&LaneFStageV3::PromptPortfolioBuilt));
    assert!(
        receipt
            .stages
            .iter()
            .all(|trace| !matches!(trace.outcome, StageOutcomeV3::FallbackUsed(_)))
    );
}

#[test]
fn utility_and_evaluation_are_required_predecessor_stages() {
    for stage in [
        LaneFStageV3::UtilityEvaluated,
        LaneFStageV3::EvaluationAdmitted,
    ] {
        let mut ports = Ports {
            fail: Some((stage, PortFailureClassV3::Rejected)),
            ..Ports::default()
        };
        let receipt = run_composition_v3(request(false), &mut ports).expect("terminal receipt");
        assert_eq!(
            receipt.disposition,
            PipelineDispositionV3::Failed(PortFailureClassV3::Rejected)
        );
        assert_eq!(receipt.stages.last().map(|trace| trace.stage), Some(stage));
        assert!(!ports.calls.contains(&LaneFStageV3::IntuitionDecided));
    }
}

#[derive(Default)]
struct Cancelled;

impl CompositionControlV3 for Cancelled {
    fn cancelled(&self) -> bool {
        true
    }
}

#[test]
fn cancellation_fails_before_any_owner_call() {
    let mut ports = Ports::default();
    let receipt = run_composition_v3_with_control(request(false), &mut ports, &Cancelled)
        .expect("cancelled receipt");
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV3::Failed(PortFailureClassV3::Cancelled)
    );
    assert!(ports.calls.is_empty());
    assert_eq!(
        receipt.stages.last().map(|trace| trace.stage),
        Some(LaneFStageV3::ObjectiveValidated)
    );
}

#[test]
fn abstain_skips_context_and_agentd_but_still_records_learning() {
    let mut ports = Ports {
        intuition: PortDecisionV3::Abstain,
        ..Ports::default()
    };
    let receipt = run_composition_v3(request(false), &mut ports).expect("abstained");
    assert_eq!(receipt.disposition, PipelineDispositionV3::Abstained);
    assert!(receipt.host_envelope.is_none());
    assert!(!ports.calls.contains(&LaneFStageV3::ContextCompiled));
    assert!(!ports.calls.contains(&LaneFStageV3::HostHandoffAccepted));
    assert_eq!(ports.calls.last(), Some(&LaneFStageV3::LearningRecorded));
}

#[test]
fn candidate_set_must_bind_the_exact_capability_snapshot() {
    let mut value = request(false);
    value.legal_candidates = build_legal_candidates_v1(
        id("candidate-set:drift"),
        digest("different-state"),
        digest("grammar"),
        700_000,
        vec![LegalActionCandidateV1 {
            candidate_id: id("action.read"),
            action_digest: digest("action"),
            support_digest: digest("support"),
            support_ppm: 900_000,
        }],
    )
    .expect("drifted candidate set");
    let mut ports = Ports::default();
    assert_eq!(
        run_composition_v3(value, &mut ports),
        Err(PipelineErrorV3::CandidateStateMismatch)
    );
    assert!(ports.calls.is_empty());
}

#[test]
fn optional_rejection_is_terminal_and_cannot_be_downgraded_to_fallback() {
    let mut ports = Ports {
        fail: Some((
            LaneFStageV3::NeuralSignalCollected,
            PortFailureClassV3::Rejected,
        )),
        ..Ports::default()
    };
    let receipt = run_composition_v3(request(true), &mut ports).expect("terminal receipt");
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV3::Failed(PortFailureClassV3::Rejected)
    );
    assert_eq!(
        receipt.stages.last().map(|trace| trace.stage),
        Some(LaneFStageV3::NeuralSignalCollected)
    );
    assert!(!ports.calls.contains(&LaneFStageV3::PromptPortfolioBuilt));
}

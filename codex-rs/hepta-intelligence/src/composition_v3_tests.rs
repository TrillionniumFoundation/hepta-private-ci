use std::cell::Cell;
use std::rc::Rc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn snapshot(include_optional: bool) -> CapabilitySnapshotV2 {
    let required = [
        ("objective.validation", "objective.compiler"),
        ("utility.evaluation", "utility.ndu"),
        ("evaluation.admission", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
    ];
    let optional = [
        ("neural.signal", "neuron.runtime"),
        ("prompt.portfolio", "prompt.optimizer"),
    ];
    let mut requirements = Vec::new();
    let mut bindings = Vec::new();
    for (capability, owner) in required {
        requirements.push(CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: CapabilityNecessityV2::Required,
        });
        bindings.push(CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            implementation_digest: digest(&format!("implementation:{owner}")),
            generation: generation(1),
        });
    }
    for (capability, owner) in optional {
        requirements.push(CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: CapabilityNecessityV2::Optional,
        });
        if include_optional {
            bindings.push(CapabilityBindingV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: digest(&format!("contract:{capability}")),
                implementation_digest: digest(&format!("implementation:{owner}")),
                generation: generation(1),
            });
        }
    }
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 1,
        body_generation: generation(1),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .unwrap_or_else(|error| panic!("snapshot: {error:?}"))
}

fn legal_candidates(snapshot_digest: Digest32) -> LegalActionCandidateSetV1 {
    build_legal_candidates(LegalActionCandidateSetRequestV1 {
        candidate_set_id: id("candidate-set"),
        state_digest: snapshot_digest,
        grammar_digest: digest("grammar"),
        candidates: vec![
            LegalActionCandidateV1 {
                candidate_id: id("action-b"),
                action_digest: digest("action-b"),
                support_digest: digest("support-b"),
                support_ppm: 950_000,
            },
            LegalActionCandidateV1 {
                candidate_id: id("action-a"),
                action_digest: digest("action-a"),
                support_digest: digest("support-a"),
                support_ppm: 900_000,
            },
        ],
        support_floor_ppm: 800_000,
    })
    .unwrap_or_else(|error| panic!("legal candidates: {error:?}"))
}

fn request(snapshot: CapabilitySnapshotV2) -> CompositionRunRequestV3 {
    CompositionRunRequestV3 {
        run_id: id("run:v3"),
        request_digest: digest("request"),
        body_digest: digest("body"),
        artifact_set_digest: digest("artifacts"),
        legal_candidates: legal_candidates(snapshot.digest()),
        snapshot,
        budget: CompositionBudgetV3 {
            total_micros: 800,
            objective_micros: 100,
            legal_set_micros: 100,
            utility_micros: 100,
            evaluation_micros: 100,
            neural_micros: 100,
            prompt_micros: 100,
            intuition_micros: 100,
            context_micros: 100,
        },
        deadline_unix_micros: 10_000,
    }
}

#[derive(Clone)]
struct Control {
    now: Rc<Cell<u64>>,
    cancelled: Rc<Cell<bool>>,
}

impl Default for Control {
    fn default() -> Self {
        Self {
            now: Rc::new(Cell::new(1_000)),
            cancelled: Rc::new(Cell::new(false)),
        }
    }
}

impl CompositionControlV3 for Control {
    fn now_unix_micros(&self) -> u64 {
        self.now.get()
    }

    fn is_cancelled(&self, _: &StableId) -> bool {
        self.cancelled.get()
    }
}

struct Ports {
    objective_digest: Digest32,
    calls: Vec<CompositionStageV3>,
    intuition: CompositionPortDecisionV3,
    failure: Option<(CompositionStageV3, CompositionFailureClassV3)>,
    advance_stage: Option<CompositionStageV3>,
    clock: Rc<Cell<u64>>,
}

impl Ports {
    fn new(control: &Control) -> Self {
        Self {
            objective_digest: digest("objective"),
            calls: Vec::new(),
            intuition: CompositionPortDecisionV3::Continue,
            failure: None,
            advance_stage: None,
            clock: Rc::clone(&control.now),
        }
    }

    fn call(
        &mut self,
        input: &CompositionPortInputV3,
        producer: &str,
        decision: CompositionPortDecisionV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        if self.advance_stage == Some(input.stage) {
            self.clock
                .set(input.deadline_unix_micros.saturating_add(1));
        }
        if let Some((stage, class)) = self.failure
            && stage == input.stage
        {
            return Err(CompositionPortFailureV3 {
                class,
                evidence_digest: digest(&format!("failure:{stage:?}")),
            });
        }
        let output_digest = if input.stage == CompositionStageV3::ObjectiveValidated {
            self.objective_digest
        } else {
            digest(&format!("output:{producer}"))
        };
        Ok(CompositionPortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            evidence_digest: digest(&format!("receipt:{producer}")),
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl CompositionPortsV3 for Ports {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.call(
            input,
            "objective.compiler",
            CompositionPortDecisionV3::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.call(input, "utility.ndu", CompositionPortDecisionV3::Continue)
    }

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.call(input, "learning.eval", CompositionPortDecisionV3::Continue)
    }

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.call(
            input,
            "neuron.runtime",
            CompositionPortDecisionV3::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.call(
            input,
            "prompt.optimizer",
            CompositionPortDecisionV3::Continue,
        )
    }

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.call(input, "intuition.policy", self.intuition)
    }

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.call(
            input,
            "context.compiler",
            CompositionPortDecisionV3::Continue,
        )
    }
}

#[test]
fn v3_graph_includes_utility_and_evaluation_and_prepares_host_envelope() {
    let control = Control::default();
    let mut ports = Ports::new(&control);
    let receipt = prepare_intelligence_run_v3(request(snapshot(true)), &mut ports, &control)
        .unwrap_or_else(|error| panic!("V3 composition: {error:?}"));

    assert_eq!(
        receipt.disposition,
        CompositionDispositionV3::HostEnvelopePrepared
    );
    assert_eq!(receipt.stages.len(), 8);
    assert_eq!(
        receipt
            .stages
            .iter()
            .map(|stage| stage.stage)
            .collect::<Vec<_>>(),
        STAGE_ORDER_V3
    );
    assert_eq!(
        ports.calls,
        vec![
            CompositionStageV3::ObjectiveValidated,
            CompositionStageV3::UtilityEvaluated,
            CompositionStageV3::EvaluationAdmitted,
            CompositionStageV3::NeuralSignalCollected,
            CompositionStageV3::PromptPortfolioBuilt,
            CompositionStageV3::IntuitionDecided,
            CompositionStageV3::ContextCompiled,
        ]
    );
    let envelope = receipt.envelope.as_ref().expect("prepared envelope");
    envelope.validate().expect("valid envelope");
    assert_eq!(envelope.composition_trace_digest, receipt.trace_digest);
    assert_eq!(envelope.objective_digest, digest("objective"));
    assert!(envelope.neural_signal_digest.is_some());
    assert!(envelope.prompt_portfolio_digest.is_some());
    assert!(!receipt.authority.grants_any());
    receipt.validate().expect("valid receipt");
}

#[test]
fn missing_required_utility_capability_fails_before_owner_calls() {
    let control = Control::default();
    let mut value = CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 1,
        body_generation: generation(1),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements: Vec::new(),
        bindings: Vec::new(),
    };
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("evaluation.admission", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
    ] {
        value.requirements.push(CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(capability),
            necessity: CapabilityNecessityV2::Required,
        });
        value.bindings.push(CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(capability),
            implementation_digest: digest(owner),
            generation: generation(1),
        });
    }
    let snapshot = CapabilitySnapshotV2::admit(value).expect("snapshot");
    let mut ports = Ports::new(&control);
    assert_eq!(
        prepare_intelligence_run_v3(request(snapshot), &mut ports, &control),
        Err(CompositionErrorV3::MissingCapability("utility.evaluation"))
    );
    assert!(ports.calls.is_empty());
}

#[test]
fn optional_neural_and_prompt_absence_is_explicit_and_never_calls_adapters() {
    let control = Control::default();
    let mut ports = Ports::new(&control);
    let receipt = prepare_intelligence_run_v3(request(snapshot(false)), &mut ports, &control)
        .expect("fallback composition");

    assert_eq!(
        receipt.disposition,
        CompositionDispositionV3::HostEnvelopePrepared
    );
    assert!(!ports.calls.contains(&CompositionStageV3::NeuralSignalCollected));
    assert!(!ports.calls.contains(&CompositionStageV3::PromptPortfolioBuilt));
    for stage in [
        CompositionStageV3::NeuralSignalCollected,
        CompositionStageV3::PromptPortfolioBuilt,
    ] {
        let trace = receipt
            .stages
            .iter()
            .find(|trace| trace.stage == stage)
            .expect("fallback trace");
        assert_eq!(
            trace.outcome,
            CompositionStageOutcomeV3::FallbackUsed(CompositionFailureClassV3::Unavailable)
        );
        assert_eq!(trace.producer, id("intelligence.control"));
    }
    let envelope = receipt.envelope.expect("envelope");
    assert_eq!(envelope.neural_signal_digest, None);
    assert_eq!(envelope.prompt_portfolio_digest, None);
}

#[test]
fn evaluation_rejection_is_terminal_and_context_is_not_called() {
    let control = Control::default();
    let mut ports = Ports::new(&control);
    ports.failure = Some((
        CompositionStageV3::EvaluationAdmitted,
        CompositionFailureClassV3::Rejected,
    ));
    let receipt = prepare_intelligence_run_v3(request(snapshot(true)), &mut ports, &control)
        .expect("terminal receipt");

    assert_eq!(
        receipt.disposition,
        CompositionDispositionV3::Failed(CompositionFailureClassV3::Rejected)
    );
    assert_eq!(
        receipt.stages.last().map(|stage| stage.stage),
        Some(CompositionStageV3::EvaluationAdmitted)
    );
    assert!(!ports.calls.contains(&CompositionStageV3::IntuitionDecided));
    assert!(receipt.envelope.is_none());
}

#[test]
fn stage_budget_overrun_cannot_be_reported_as_success() {
    let control = Control::default();
    let mut ports = Ports::new(&control);
    ports.advance_stage = Some(CompositionStageV3::UtilityEvaluated);
    let receipt = prepare_intelligence_run_v3(request(snapshot(true)), &mut ports, &control)
        .expect("timed-out receipt");

    assert_eq!(
        receipt.disposition,
        CompositionDispositionV3::Failed(CompositionFailureClassV3::TimedOut)
    );
    assert_eq!(
        receipt.stages.last().map(|stage| stage.outcome),
        Some(CompositionStageOutcomeV3::Failed(
            CompositionFailureClassV3::TimedOut
        ))
    );
    assert!(!ports.calls.contains(&CompositionStageV3::EvaluationAdmitted));
    assert!(receipt.envelope.is_none());
}

#[test]
fn cancellation_before_entry_never_calls_an_owner() {
    let control = Control::default();
    control.cancelled.set(true);
    let mut ports = Ports::new(&control);
    let receipt = prepare_intelligence_run_v3(request(snapshot(true)), &mut ports, &control)
        .expect("cancel receipt");
    assert_eq!(receipt.disposition, CompositionDispositionV3::Cancelled);
    assert!(receipt.stages.is_empty());
    assert!(ports.calls.is_empty());
    assert!(receipt.envelope.is_none());
}

#[test]
fn intuition_abstention_stops_before_context_and_host_handoff() {
    let control = Control::default();
    let mut ports = Ports::new(&control);
    ports.intuition = CompositionPortDecisionV3::Abstain;
    let receipt = prepare_intelligence_run_v3(request(snapshot(true)), &mut ports, &control)
        .expect("abstain receipt");

    assert_eq!(receipt.disposition, CompositionDispositionV3::Abstained);
    assert_eq!(receipt.stages.len(), 7);
    assert!(!ports.calls.contains(&CompositionStageV3::ContextCompiled));
    assert!(receipt.envelope.is_none());
}

#[test]
fn legal_candidate_contract_is_canonical_and_bounded() {
    let snapshot_digest = digest("snapshot");
    let value = legal_candidates(snapshot_digest);
    assert_eq!(value.candidates[0].candidate_id, id("action-a"));
    assert_eq!(value.candidates[1].candidate_id, id("action-b"));
    assert!(!value.digest().is_zero());

    let mut invalid = value.clone();
    invalid.candidates[0].support_ppm = invalid.support_floor_ppm - 1;
    assert!(matches!(
        invalid.validate(),
        Err(LegalActionCandidateSetErrorV1::InvalidCandidate(_))
    ));
}

#[test]
fn envelope_digest_detects_transport_mutation() {
    let control = Control::default();
    let mut ports = Ports::new(&control);
    let mut receipt = prepare_intelligence_run_v3(request(snapshot(true)), &mut ports, &control)
        .expect("composition");
    let envelope = receipt.envelope.as_mut().expect("envelope");
    envelope.context_digest = digest("tampered-context");
    assert_eq!(
        envelope.validate(),
        Err(CompositionErrorV3::EnvelopeDigestMismatch)
    );
}

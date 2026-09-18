use std::cell::Cell;
use std::rc::Rc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;
use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn capability_snapshot(with_optional: bool) -> CapabilitySnapshotV2 {
    let required = [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("evaluation.admission", "learning.eval"),
        ("learning.record", "learning.ledger"),
        ("dispatch.proposal", "runtime.agentd"),
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
            generation: Generation::new(1).expect("generation"),
        });
    }
    for (capability, owner) in optional {
        let contract = digest(&format!("contract:{capability}"));
        requirements.push(CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: contract,
            necessity: CapabilityNecessityV2::Optional,
        });
        if with_optional {
            bindings.push(CapabilityBindingV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                implementation_digest: digest(&format!("implementation:{owner}")),
                generation: Generation::new(1).expect("generation"),
            });
        }
    }
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 7,
        body_generation: Generation::new(3).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("capability snapshot")
}

fn candidate_set(snapshot: &CapabilitySnapshotV2) -> LegalActionCandidateSetV1 {
    LegalActionCandidateSetV1::new(
        id("candidate-set"),
        snapshot.digest(),
        id("intelligence.control"),
        digest("grammar"),
        vec![
            LegalActionCandidateV1 {
                candidate_id: id("action.a"),
                support_digest: digest("support:a"),
                support_ppm: 900_000,
            },
            LegalActionCandidateV1 {
                candidate_id: id("action.b"),
                support_digest: digest("support:b"),
                support_ppm: 800_000,
            },
        ],
        500_000,
    )
    .expect("candidate set")
}

fn request(with_optional: bool) -> CompositionRunRequestV3 {
    let snapshot = capability_snapshot(with_optional);
    let candidates = candidate_set(&snapshot);
    CompositionRunRequestV3 {
        run_id: id("run:v3"),
        request_digest: digest("request"),
        snapshot,
        body_digest: digest("body"),
        artifact_set_digest: digest("artifacts"),
        started_at_micros: 1_000,
        deadline_micros: 3_000,
        budget: CompositionBudgetV3 {
            total_micros: 1_200,
            evidence_floor_micros: 100,
            recovery_floor_micros: 100,
            objective_micros: 100,
            legal_set_micros: 100,
            utility_micros: 100,
            neural_micros: 100,
            prompt_micros: 100,
            intuition_micros: 100,
            context_micros: 100,
            evaluation_micros: 100,
            ledger_micros: 100,
        },
        candidate_set: candidates,
    }
}

#[derive(Clone)]
struct Control {
    now: Rc<Cell<u64>>,
    cancelled: Rc<Cell<bool>>,
}

impl Control {
    fn new(now: u64) -> Self {
        Self {
            now: Rc::new(Cell::new(now)),
            cancelled: Rc::new(Cell::new(false)),
        }
    }
}

impl CompositionControlV3 for Control {
    fn now_micros(&self) -> u64 {
        self.now.get()
    }

    fn is_cancelled(&self) -> bool {
        self.cancelled.get()
    }
}

struct Ports {
    snapshot_digest: Digest32,
    objective_digest: Digest32,
    calls: Vec<CompositionStageV3>,
    intuition: PortDecisionV1,
    fail: Option<(CompositionStageV3, PortFailureClassV1)>,
    wrong_snapshot: Option<CompositionStageV3>,
    authority_widening: Option<CompositionStageV3>,
}

impl Ports {
    fn new(request: &CompositionRunRequestV3) -> Self {
        Self {
            snapshot_digest: request.snapshot.digest(),
            objective_digest: request.snapshot.objective_digest(),
            calls: Vec::new(),
            intuition: PortDecisionV1::Continue,
            fail: None,
            wrong_snapshot: None,
            authority_widening: None,
        }
    }

    fn call(
        &mut self,
        input: &CompositionPortInputV3,
        producer: &str,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.calls.push(input.stage);
        if let Some((stage, class)) = self.fail
            && stage == input.stage
        {
            return Err(PortFailureV1 {
                class,
                evidence_digest: digest(&format!("failure:{stage:?}")),
            });
        }
        let output = match input.stage {
            CompositionStageV3::ObjectiveValidated => self.objective_digest,
            CompositionStageV3::ContextCompiled => digest("compiled-context"),
            _ => digest(&format!("output:{producer}:{:?}", input.stage)),
        };
        let evidence = if input.stage == CompositionStageV3::ContextCompiled {
            digest("context-compilation-receipt")
        } else {
            output
        };
        let mut authority = AuthorityPosture::DENY_ALL;
        if self.authority_widening == Some(input.stage) {
            authority.runtime = true;
        }
        Ok(CompositionPortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: if self.wrong_snapshot == Some(input.stage) {
                digest("mixed-snapshot")
            } else {
                self.snapshot_digest
            },
            predecessor_digest: input.predecessor_digest,
            output_digest: output,
            evidence_digest: evidence,
            decision: if input.stage == CompositionStageV3::IntuitionDecided {
                self.intuition
            } else {
                PortDecisionV1::Continue
            },
            authority,
        })
    }
}

impl CompositionPortsV3 for Ports {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "objective.compiler")
    }

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "utility.ndu")
    }

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "neuron.runtime")
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "prompt.optimizer")
    }

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "intuition.policy")
    }

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "context.compiler")
    }

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "learning.eval")
    }

    fn record_decision(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "learning.ledger")
    }
}

#[test]
fn v3_orders_utility_and_evaluation_in_one_predecessor_chain() {
    let request = request(false);
    let control = Control::new(request.started_at_micros);
    let mut ports = Ports::new(&request);
    let receipt =
        prepare_intelligence_run_v3(request, &mut ports, &control).expect("prepared run");

    assert_eq!(receipt.disposition, CompositionDispositionV3::ReadyForDispatch);
    assert_eq!(receipt.stages.len(), 9);
    assert_eq!(
        receipt
            .stages
            .iter()
            .map(|stage| stage.stage)
            .collect::<Vec<_>>(),
        vec![
            CompositionStageV3::ObjectiveValidated,
            CompositionStageV3::LegalSetBuilt,
            CompositionStageV3::UtilityEvaluated,
            CompositionStageV3::NeuralSignalCollected,
            CompositionStageV3::PromptPortfolioBuilt,
            CompositionStageV3::IntuitionDecided,
            CompositionStageV3::ContextCompiled,
            CompositionStageV3::EvaluationAdmitted,
            CompositionStageV3::DecisionRecorded,
        ]
    );
    assert!(receipt.stages.iter().any(|stage| {
        stage.stage == CompositionStageV3::NeuralSignalCollected
            && stage.outcome
                == StageOutcomeV3::FallbackUsed(PortFailureClassV1::Unavailable)
    }));
    assert!(receipt.stages.iter().any(|stage| {
        stage.stage == CompositionStageV3::PromptPortfolioBuilt
            && stage.outcome
                == StageOutcomeV3::FallbackUsed(PortFailureClassV1::Unavailable)
    }));
    assert!(!ports.calls.contains(&CompositionStageV3::NeuralSignalCollected));
    assert!(!ports.calls.contains(&CompositionStageV3::PromptPortfolioBuilt));
    assert!(ports.calls.contains(&CompositionStageV3::UtilityEvaluated));
    assert!(ports.calls.contains(&CompositionStageV3::EvaluationAdmitted));
    let envelope = receipt.envelope.expect("host envelope");
    envelope.validate().expect("valid envelope");
    assert_eq!(envelope.authority_epoch, 7);
    assert_eq!(envelope.context_digest, digest("compiled-context"));
    assert_eq!(
        envelope.context_receipt_digest,
        digest("context-compilation-receipt")
    );
}

#[test]
fn present_optional_capabilities_invoke_native_owner_ports() {
    let request = request(true);
    let control = Control::new(request.started_at_micros);
    let mut ports = Ports::new(&request);
    let receipt =
        prepare_intelligence_run_v3(request, &mut ports, &control).expect("prepared run");
    assert_eq!(receipt.disposition, CompositionDispositionV3::ReadyForDispatch);
    assert!(ports.calls.contains(&CompositionStageV3::NeuralSignalCollected));
    assert!(ports.calls.contains(&CompositionStageV3::PromptPortfolioBuilt));
    assert!(receipt.stages.iter().all(|stage| {
        !matches!(stage.outcome, StageOutcomeV3::FallbackUsed(_))
    }));
}

#[test]
fn abstention_skips_dispatch_inputs_but_records_the_decision() {
    let request = request(false);
    let control = Control::new(request.started_at_micros);
    let mut ports = Ports::new(&request);
    ports.intuition = PortDecisionV1::Abstain;
    let receipt =
        prepare_intelligence_run_v3(request, &mut ports, &control).expect("abstained");
    assert_eq!(receipt.disposition, CompositionDispositionV3::Abstained);
    assert_eq!(
        receipt.stages.last().map(|stage| stage.stage),
        Some(CompositionStageV3::DecisionRecorded)
    );
    assert_eq!(
        receipt.stages.last().map(|stage| stage.outcome),
        Some(StageOutcomeV3::Completed)
    );
    assert!(receipt.envelope.is_none());
    assert!(!ports.calls.contains(&CompositionStageV3::ContextCompiled));
    assert!(!ports.calls.contains(&CompositionStageV3::EvaluationAdmitted));
    assert!(ports.calls.contains(&CompositionStageV3::DecisionRecorded));
}

#[test]
fn utility_failure_is_terminal_and_never_reaches_intuition() {
    let request = request(false);
    let control = Control::new(request.started_at_micros);
    let mut ports = Ports::new(&request);
    ports.fail = Some((
        CompositionStageV3::UtilityEvaluated,
        PortFailureClassV1::Unavailable,
    ));
    let receipt = prepare_intelligence_run_v3(request, &mut ports, &control)
        .expect("failure is receipted");
    assert_eq!(
        receipt.disposition,
        CompositionDispositionV3::Failed(PortFailureClassV1::Unavailable)
    );
    assert_eq!(
        receipt.stages.last().map(|stage| stage.stage),
        Some(CompositionStageV3::UtilityEvaluated)
    );
    assert!(!ports.calls.contains(&CompositionStageV3::IntuitionDecided));
}

#[test]
fn cancellation_and_deadline_fail_closed_before_owner_call() {
    let request = request(false);
    let control = Control::new(request.started_at_micros);
    control.cancelled.set(true);
    let mut ports = Ports::new(&request);
    let cancelled =
        prepare_intelligence_run_v3(request.clone(), &mut ports, &control).expect("cancelled");
    assert_eq!(cancelled.disposition, CompositionDispositionV3::Cancelled);
    assert!(ports.calls.is_empty());

    let late = Control::new(request.deadline_micros);
    let mut ports = Ports::new(&request);
    let expired =
        prepare_intelligence_run_v3(request, &mut ports, &late).expect("deadline receipt");
    assert_eq!(
        expired.disposition,
        CompositionDispositionV3::DeadlineExceeded
    );
    assert!(ports.calls.is_empty());
}

#[test]
fn mixed_snapshot_and_authority_widening_are_rejected() {
    let request = request(false);
    let control = Control::new(request.started_at_micros);
    let mut ports = Ports::new(&request);
    ports.wrong_snapshot = Some(CompositionStageV3::UtilityEvaluated);
    assert_eq!(
        prepare_intelligence_run_v3(request.clone(), &mut ports, &control),
        Err(CompositionErrorV3::SnapshotMismatch)
    );

    let mut ports = Ports::new(&request);
    ports.authority_widening = Some(CompositionStageV3::EvaluationAdmitted);
    assert_eq!(
        prepare_intelligence_run_v3(request, &mut ports, &control),
        Err(CompositionErrorV3::AuthorityWidening)
    );
}

#[test]
fn candidate_set_digest_is_canonical_under_input_reordering() {
    let snapshot = capability_snapshot(false);
    let first = candidate_set(&snapshot);
    let mut reversed = first.candidates.clone();
    reversed.reverse();
    let second = LegalActionCandidateSetV1::new(
        first.candidate_set_id.clone(),
        first.state_digest,
        first.generator_id.clone(),
        first.grammar_digest,
        reversed,
        first.support_floor_ppm,
    )
    .expect("candidate set");
    assert_eq!(first.digest(), second.digest());
}

#[test]
fn caller_candidate_limit_reserves_ledger_control_slots() {
    let snapshot = capability_snapshot(false);
    let candidates = (0..127)
        .map(|index| LegalActionCandidateV1 {
            candidate_id: id(&format!("action.{index:03}")),
            support_digest: digest(&format!("support:{index:03}")),
            support_ppm: 1_000_000,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        LegalActionCandidateSetV1::new(
            id("candidate-set-overflow"),
            snapshot.digest(),
            id("intelligence.control"),
            digest("grammar"),
            candidates,
            500_000,
        ),
        Err(LegalActionCandidateSetErrorV1::CandidateLimitExceeded)
    );
}

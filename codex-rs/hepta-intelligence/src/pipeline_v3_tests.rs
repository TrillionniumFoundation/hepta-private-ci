use super::*;
use codex_hepta_types::Generation;
use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn snapshot() -> CapabilitySnapshotV2 {
    let required = [
        ("objective.validation", "objective.compiler"),
        ("evaluation.admission", "learning.eval"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.handoff", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ];
    let contract = digest("contract");
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 1,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements: required
            .iter()
            .map(|(capability, owner)| CapabilityRequirementV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                necessity: CapabilityNecessityV2::Required,
            })
            .chain(
                [
                    ("neural.signal", "neuron.runtime"),
                    ("prompt.portfolio", "prompt.optimizer"),
                ]
                .iter()
                .map(|(capability, owner)| CapabilityRequirementV2 {
                    capability_id: id(capability),
                    owner_id: id(owner),
                    contract_digest: contract,
                    necessity: CapabilityNecessityV2::Optional,
                }),
            )
            .collect(),
        bindings: required
            .iter()
            .map(|(capability, owner)| CapabilityBindingV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                implementation_digest: digest(owner),
                generation: Generation::new(1).expect("generation"),
            })
            .collect(),
    })
    .expect("snapshot")
}

fn request() -> IntelligenceRunRequestV3 {
    IntelligenceRunRequestV3 {
        run_id: id("run:v3"),
        request_digest: digest("request"),
        snapshot: snapshot(),
        budget: IntelligenceBudgetV3 {
            total_micros: 10_000,
            objective_micros: 1_000,
            evaluation_micros: 1_000,
            legal_set_micros: 1_000,
            utility_micros: 1_000,
            neural_micros: 1_000,
            prompt_micros: 1_000,
            intuition_micros: 1_000,
            context_micros: 1_000,
            handoff_micros: 1_000,
            ledger_micros: 1_000,
        },
    }
}

#[derive(Default)]
struct Ports {
    calls: Vec<IntelligenceStageV3>,
    abstain: bool,
}

impl Ports {
    fn receipt(
        &mut self,
        input: &IntelligencePortInputV3,
        producer: &str,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.calls.push(input.stage);
        Ok(IntelligencePortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: digest(&format!("{producer}:{:?}", input.stage)),
            decision: if self.abstain && input.stage == IntelligenceStageV3::IntuitionDecided {
                IntelligencePortDecisionV3::Abstain
            } else {
                IntelligencePortDecisionV3::Continue
            },
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

macro_rules! port {
    ($name:ident, $owner:literal) => {
        fn $name(
            &mut self,
            input: &IntelligencePortInputV3,
        ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
            self.receipt(input, $owner)
        }
    };
}

impl IntelligenceCompositionPortsV3 for Ports {
    port!(validate_objective, "objective.compiler");
    port!(admit_evaluation, "learning.eval");
    port!(build_legal_set, "intelligence.control");
    port!(evaluate_utility, "utility.ndu");
    port!(collect_neural_signal, "neuron.runtime");
    port!(build_prompt_portfolio, "prompt.optimizer");
    port!(decide_intuition, "intuition.policy");
    port!(compile_context, "context.compiler");
    port!(handoff_to_host, "runtime.agentd");
    port!(record_learning, "learning.ledger");
}

#[test]
fn v3_binds_evaluation_and_utility_into_one_predecessor_chain() {
    let mut ports = Ports::default();
    let receipt = run_composition_v3(request(), &mut ports).expect("composition");
    assert_eq!(receipt.disposition, IntelligenceDispositionV3::HostHandedOff);
    assert_eq!(
        ports.calls,
        vec![
            IntelligenceStageV3::ObjectiveValidated,
            IntelligenceStageV3::EvaluationAdmitted,
            IntelligenceStageV3::LegalSetBuilt,
            IntelligenceStageV3::UtilityEvaluated,
            IntelligenceStageV3::IntuitionDecided,
            IntelligenceStageV3::ContextCompiled,
            IntelligenceStageV3::HostHandoff,
            IntelligenceStageV3::LearningRecorded,
        ]
    );
    assert_eq!(receipt.stages.len(), 10);
    for pair in receipt.stages.windows(2) {
        assert_eq!(pair[1].predecessor_digest, pair[0].output_digest);
    }
    let envelope = receipt.host_envelope.expect("host envelope");
    assert_eq!(envelope.utility_receipt_digest, receipt.stages[3].output_digest);
    assert_eq!(
        envelope.evaluation_receipt_digest,
        receipt.stages[1].output_digest
    );
    assert_eq!(envelope.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn absent_optional_neuron_and_prompt_are_explicit_fallbacks() {
    let mut ports = Ports::default();
    let receipt = run_composition_v3(request(), &mut ports).expect("composition");
    assert!(!ports.calls.contains(&IntelligenceStageV3::NeuralSignalCollected));
    assert!(!ports.calls.contains(&IntelligenceStageV3::PromptPortfolioBuilt));
    assert!(receipt.stages.iter().any(|trace| {
        trace.stage == IntelligenceStageV3::NeuralSignalCollected
            && trace.outcome
                == IntelligenceStageOutcomeV3::FallbackUsed(
                    IntelligenceFailureClassV3::Unavailable,
                )
    }));
}

#[test]
fn abstain_skips_context_and_host_handoff_but_records_learning() {
    let mut ports = Ports {
        abstain: true,
        ..Ports::default()
    };
    let receipt = run_composition_v3(request(), &mut ports).expect("composition");
    assert_eq!(receipt.disposition, IntelligenceDispositionV3::Abstained);
    assert!(receipt.host_envelope.is_none());
    assert!(!ports.calls.contains(&IntelligenceStageV3::ContextCompiled));
    assert!(!ports.calls.contains(&IntelligenceStageV3::HostHandoff));
    assert_eq!(ports.calls.last(), Some(&IntelligenceStageV3::LearningRecorded));
}

#[test]
fn native_legal_candidate_contract_is_bounded_and_digest_stable() {
    let first = LegalActionCandidateSetV1::new(
        id("set"),
        digest("state"),
        id("generator"),
        digest("grammar"),
        vec![id("b"), id("a")],
        900_000,
    )
    .expect("candidate set");
    let second = LegalActionCandidateSetV1::new(
        id("set"),
        digest("state"),
        id("generator"),
        digest("grammar"),
        vec![id("a"), id("b")],
        900_000,
    )
    .expect("candidate set");
    assert_eq!(first, second);
}

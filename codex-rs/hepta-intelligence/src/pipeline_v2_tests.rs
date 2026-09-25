use super::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;
use crate::LaneFStageV1;
use crate::PipelineDispositionV1;
use crate::PortDecisionV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn snapshot_request() -> CapabilitySnapshotRequestV2 {
    let pairs = [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("dispatch.proposal", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ];
    let contract = Digest32::of_bytes(b"contract");
    CapabilitySnapshotRequestV2 {
        objective_digest: Digest32::of_bytes(b"objective"),
        authority_epoch: 1,
        body_generation: Generation::new(/*value*/ 1).expect("generation"),
        configuration_digest: Digest32::of_bytes(b"configuration"),
        revocation_frontier_digest: Digest32::of_bytes(b"revocations"),
        requirements: pairs
            .iter()
            .map(|(capability, owner)| CapabilityRequirementV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                necessity: CapabilityNecessityV2::Required,
            })
            .collect(),
        bindings: pairs
            .iter()
            .map(|(capability, owner)| CapabilityBindingV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                implementation_digest: Digest32::of_bytes(owner.as_bytes()),
                generation: Generation::new(/*value*/ 1).expect("generation"),
            })
            .collect(),
    }
}

fn request(snapshot: CapabilitySnapshotRequestV2) -> LaneFRunRequestV2 {
    LaneFRunRequestV2 {
        run_id: id("run"),
        request_digest: Digest32::of_bytes(b"request"),
        snapshot: CapabilitySnapshotV2::admit(snapshot).expect("snapshot"),
        budget: LaneFBudgetV1 {
            total_micros: 800,
            objective_micros: 100,
            legal_set_micros: 100,
            neural_micros: 100,
            prompt_micros: 100,
            intuition_micros: 100,
            context_micros: 100,
            dispatch_micros: 100,
            ledger_micros: 100,
        },
    }
}

#[derive(Default)]
struct Ports {
    calls: Vec<LaneFStageV1>,
    mixed_snapshot: bool,
    abstain: bool,
}
impl Ports {
    fn call(
        &mut self,
        input: &PortInputV1,
        producer: &str,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.calls.push(input.stage);
        Ok(PortReceiptV1 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: if self.mixed_snapshot {
                Digest32::of_bytes(b"other")
            } else {
                input.snapshot_digest
            },
            predecessor_digest: input.predecessor_digest,
            output_digest: Digest32::of_bytes(producer.as_bytes()),
            decision: if self.abstain && input.stage == LaneFStageV1::IntuitionDecided {
                PortDecisionV1::Abstain
            } else {
                PortDecisionV1::Continue
            },
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}
macro_rules! port {
    ($method:ident, $owner:literal) => {
        fn $method(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
            self.call(input, $owner)
        }
    };
}
impl LaneFShadowPortsV1 for Ports {
    port!(validate_objective, "objective.compiler");
    port!(build_legal_set, "intelligence.control");
    port!(collect_neural_signal, "neuron.runtime");
    port!(build_prompt_portfolio, "prompt.optimizer");
    port!(decide_intuition, "intuition.policy");
    port!(compile_context, "context.compiler");
    port!(propose_dispatch, "runtime.agentd");
    port!(record_learning, "learning.ledger");
}

#[test]
fn existing_stage_engine_runs_without_neural_or_model_artifacts() {
    let mut ports = Ports::default();
    let receipt =
        run_shadow_pipeline_v2(request(snapshot_request()), &mut ports).expect("pipeline");
    assert_eq!(
        receipt.absent_adapters(),
        &["neural.signal", "prompt.portfolio"]
    );
    assert!(!ports.calls.contains(&LaneFStageV1::NeuralSignalCollected));
    assert!(!ports.calls.contains(&LaneFStageV1::PromptPortfolioBuilt));
    assert_eq!(ports.calls.len(), 6);
    assert_eq!(
        receipt.trace().disposition,
        PipelineDispositionV1::DispatchProposed
    );
    assert_eq!(receipt.trace().authority, AuthorityPosture::DENY_ALL);
    receipt.trace().validate().expect("shared trace");
}

#[test]
fn optional_add_remove_changes_routing_and_versioned_receipt() {
    let absent =
        run_shadow_pipeline_v2(request(snapshot_request()), &mut Ports::default()).expect("absent");
    let mut value = snapshot_request();
    value.requirements.push(CapabilityRequirementV2 {
        capability_id: id("neural.signal"),
        owner_id: id("neuron.runtime"),
        contract_digest: Digest32::of_bytes(b"signal contract"),
        necessity: CapabilityNecessityV2::Optional,
    });
    value.bindings.push(CapabilityBindingV2 {
        capability_id: id("neural.signal"),
        owner_id: id("neuron.runtime"),
        contract_digest: Digest32::of_bytes(b"signal contract"),
        implementation_digest: Digest32::of_bytes(b"signal"),
        generation: Generation::new(/*value*/ 1).expect("generation"),
    });
    let mut ports = Ports::default();
    let present = run_shadow_pipeline_v2(request(value.clone()), &mut ports).expect("present");
    assert!(ports.calls.contains(&LaneFStageV1::NeuralSignalCollected));
    assert_ne!(present.digest(), absent.digest());
    value.bindings.pop();
    let mut ports = Ports::default();
    let retired = run_shadow_pipeline_v2(request(value), &mut ports).expect("retired");
    assert!(!ports.calls.contains(&LaneFStageV1::NeuralSignalCollected));
    assert_eq!(retired.trace().authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn absent_core_is_rejected_even_when_manifest_omits_its_requirement() {
    let mut value = snapshot_request();
    value.requirements.remove(0);
    value.bindings.remove(0);
    let mut ports = Ports::default();
    assert_eq!(
        run_shadow_pipeline_v2(request(value), &mut ports),
        Err(PipelineErrorV2::MissingCapability("objective.validation"))
    );
    assert!(ports.calls.is_empty());
}

#[test]
fn self_consistent_wrong_owner_is_rejected_before_any_stage_call() {
    let mut value = snapshot_request();
    value.requirements[0].owner_id = id("other");
    value.bindings[0].owner_id = id("other");
    let mut ports = Ports::default();
    assert_eq!(
        run_shadow_pipeline_v2(request(value), &mut ports),
        Err(PipelineErrorV2::OwnerMismatch("objective.validation"))
    );
    assert!(ports.calls.is_empty());
}

#[test]
fn mixed_snapshot_receipt_still_fails_existing_engine_validation() {
    let mut ports = Ports {
        mixed_snapshot: true,
        ..Ports::default()
    };
    assert!(run_shadow_pipeline_v2(request(snapshot_request()), &mut ports).is_err());
    assert_eq!(ports.calls.len(), 1);
}

#[test]
fn abstention_does_not_dispatch_but_preserves_learning_stage() {
    let mut ports = Ports {
        abstain: true,
        ..Ports::default()
    };
    let receipt =
        run_shadow_pipeline_v2(request(snapshot_request()), &mut ports).expect("abstained");
    assert_eq!(
        receipt.trace().disposition,
        PipelineDispositionV1::Abstained
    );
    assert!(!ports.calls.contains(&LaneFStageV1::DispatchProposed));
    assert_eq!(ports.calls.last(), Some(&LaneFStageV1::LearningRecorded));
}

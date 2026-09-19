use super::*;

use std::fs::OpenOptions;

use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_intelligence_eval::Direction;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intelligence_eval::MetricComparison;
use codex_hepta_intuition::ActionCandidate;
use codex_hepta_intuition::DecisionRequest;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_objective::ActionClass;
use codex_hepta_objective::ConfirmationPolicy;
use codex_hepta_objective::Constraint;
use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::ConstraintRelation;
use codex_hepta_objective::ObjectiveSourceEnvelope;
use codex_hepta_objective::PredicateTerminality;
use codex_hepta_objective::SoftDirection;
use codex_hepta_objective::SoftPreference;
use codex_hepta_objective::SourceTrust;
use codex_hepta_objective::SuccessPredicate;
use codex_hepta_objective::compile as compile_objective;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;
use crate::CapabilitySnapshotV2;
use crate::LaneFBudgetV3;
use crate::LaneFRunRequestV3;
use crate::LegalActionCandidateV1;
use crate::PipelineDispositionV3;
use crate::build_legal_candidates_v1;
use crate::run_composition_v3;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("fixture generation")
}

fn objective() -> ObjectiveSourceEnvelope {
    ObjectiveSourceEnvelope {
        request_id: id("request:v3-native"),
        principal_scope: id("principal:alpha"),
        revision: Revision::new(1).expect("revision"),
        source_trust: SourceTrust::PrincipalStructured,
        source_digest: digest("objective-source"),
        schema_digest: digest("objective-schema"),
        constraints: vec![Constraint {
            id: id("privacy-ceiling"),
            class: ConstraintClass::Constitutional,
            axis: id("privacy-risk"),
            relation: ConstraintRelation::AtMost,
            bound: FixedQ32::ZERO,
            evidence_source: id("constitution-v1"),
        }],
        success_predicates: vec![SuccessPredicate {
            id: id("answer-produced"),
            axis: id("answer-count"),
            relation: ConstraintRelation::AtLeast,
            bound: FixedQ32::ONE,
            evidence_source: id("terminal-observer"),
            terminality: PredicateTerminality::Terminal,
        }],
        allowed_actions: vec![ActionClass {
            id: id("read-local"),
            confirmation: ConfirmationPolicy::NotRequired,
        }],
        forbidden_actions: Vec::new(),
        soft_preferences: vec![SoftPreference {
            dimension: id("quality"),
            direction: SoftDirection::Maximize,
            weight: FixedQ32::ONE,
        }],
    }
}

fn capability_snapshot(objective_digest: Digest32) -> CapabilitySnapshotV2 {
    let pairs = [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("learning.evaluation", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.handoff", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ];
    let requirements = pairs
        .iter()
        .map(|(capability, owner)| CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: CapabilityNecessityV2::Required,
        })
        .collect::<Vec<_>>();
    let bindings = requirements
        .iter()
        .map(|requirement| CapabilityBindingV2 {
            capability_id: requirement.capability_id.clone(),
            owner_id: requirement.owner_id.clone(),
            contract_digest: requirement.contract_digest,
            implementation_digest: digest(&format!("impl:{}", requirement.capability_id.as_str())),
            generation: generation(1),
        })
        .collect();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest,
        authority_epoch: 1,
        body_generation: generation(1),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocation-frontier"),
        requirements,
        bindings,
    })
    .expect("capability snapshot")
}

fn legal_candidates(state_digest: Digest32) -> LegalActionCandidateSetV1 {
    build_legal_candidates_v1(
        id("legal-set:v3"),
        state_digest,
        digest("grammar"),
        0,
        vec![
            LegalActionCandidateV1 {
                candidate_id: id("abstain"),
                action_digest: digest("action:abstain"),
                support_digest: digest("support:abstain"),
                support_ppm: 1_000_000,
            },
            LegalActionCandidateV1 {
                candidate_id: id("read-local"),
                action_digest: digest("action:read-local"),
                support_digest: digest("support:read-local"),
                support_ppm: 1_000_000,
            },
        ],
    )
    .expect("legal candidates")
}

fn utility_set(objective_digest: Digest32) -> ContributionSet {
    let contribution = |candidate: &str, value: FixedQ32| UtilityContribution {
        candidate_id: id(candidate),
        organ_id: id("planner"),
        objective_digest,
        generation: generation(1),
        feasibility: FeasibilityPosture::Feasible,
        utility: vec![AxisValue {
            axis: id("quality"),
            value,
        }],
        risk: Vec::new(),
        resource: Vec::new(),
        uncertainty: vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
        support_digest: digest(&format!("utility-support:{candidate}")),
    };
    ContributionSet {
        objective_digest,
        generation: generation(1),
        contributions: vec![
            contribution("abstain", FixedQ32::ZERO),
            contribution("read-local", FixedQ32::ONE),
        ],
    }
}

fn utility_profile() -> UtilityProfile {
    UtilityProfile {
        profile_id: id("utility:v3"),
        dimensions: vec![(id("quality"), AxisDirection::Maximize)],
        risk_ceilings: Vec::new(),
        resource_ceilings: Vec::new(),
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")],
        },
    }
}

fn evaluation(objective_digest: Digest32) -> EvaluationRequest {
    EvaluationRequest {
        evaluation_id: id("evaluation:v3"),
        evaluator_id: id("independent-evaluator"),
        candidate_id: id("policy:v3"),
        candidate_producer_id: id("learning-operator"),
        baseline_id: id("baseline:v3"),
        objective_digest,
        comparisons: vec![MetricComparison {
            metric_id: id("safety"),
            direction: Direction::Minimize,
            candidate: FixedQ32::ZERO,
            baseline: FixedQ32::ONE,
            minimum_delta: FixedQ32::ZERO,
            hard: true,
            support_digest: digest("evaluation-support"),
        }],
    }
}

fn intuition(objective_digest: Digest32, candidate_set_digest: Digest32) -> DecisionRequest {
    DecisionRequest {
        decision_id: id("placeholder-run"),
        objective_digest,
        candidate_set_digest,
        minimum_confidence: ProbabilityQ32::ONE,
        candidates: vec![ActionCandidate {
            candidate_id: id("read-local"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::ONE,
            confidence: ProbabilityQ32::ONE,
            support_digest: digest("intuition-support"),
        }],
    }
}

fn context(objective_digest: Digest32) -> CompilationRequest {
    CompilationRequest {
        compilation_id: id("context:v3"),
        run_snapshot_digest: digest("placeholder-snapshot"),
        objective_digest,
        token_budget: 8,
        items: vec![ContextItem {
            item_id: id("instruction:v3"),
            role: ContextRole::TrustedInstruction,
            content_digest: digest("instruction"),
            source_digest: digest("instruction-source"),
            token_count: 1,
            contains_secret: false,
        }],
    }
}

#[derive(Default)]
struct RecordingHost {
    accepted: Option<Digest32>,
}

impl HostEnvelopePortV3 for RecordingHost {
    fn accept_host_envelope_v3(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        envelope.validate().map_err(|_| PortFailureV3 {
            class: PortFailureClassV3::Rejected,
            evidence_digest: digest("invalid-envelope"),
        })?;
        self.accepted = Some(envelope.envelope_digest);
        let mut bytes = b"native-v3-host-acceptance".to_vec();
        bytes.extend_from_slice(envelope.envelope_digest.as_array());
        bytes.extend_from_slice(input.predecessor_digest.as_array());
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer: id("runtime.agentd"),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: Digest32::of_bytes(&bytes),
            decision: PortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

fn fixture_inputs(
    objective: ObjectiveSourceEnvelope,
    objective_digest: Digest32,
    legal: &LegalActionCandidateSetV1,
) -> NativeV3OwnerInputs {
    NativeV3OwnerInputs {
        expected_objective_digest: objective_digest,
        legal_candidates: legal.clone(),
        objective,
        utility_set: utility_set(objective_digest),
        utility_profile: utility_profile(),
        utility_scalarization: None,
        evaluation: evaluation(objective_digest),
        neuron: None,
        neuron_previous: None,
        prompt: None,
        intuition: intuition(objective_digest, legal.candidate_set_digest),
        context: context(objective_digest),
        learning: LearningDecisionTemplateV3 {
            episode_id: id("episode:v3"),
            policy_id: id("policy:v3"),
        },
    }
}

fn run_request(
    snapshot: CapabilitySnapshotV2,
    legal: LegalActionCandidateSetV1,
) -> LaneFRunRequestV3 {
    LaneFRunRequestV3 {
        run_id: id("run:v3-native"),
        request_digest: digest("request"),
        body_digest: digest("body"),
        artifact_set_digest: digest("artifact-set"),
        snapshot,
        legal_candidates: legal,
        budget: LaneFBudgetV3 {
            total_micros: 11_000_000,
            objective_micros: 1_000_000,
            legal_set_micros: 1_000_000,
            utility_micros: 1_000_000,
            evaluation_micros: 1_000_000,
            neural_micros: 1_000_000,
            prompt_micros: 1_000_000,
            intuition_micros: 1_000_000,
            context_micros: 1_000_000,
            envelope_micros: 1_000_000,
            host_handoff_micros: 1_000_000,
            ledger_micros: 1_000_000,
        },
        deadline_unix_micros: 4_000_000_000_000_000,
    }
}

#[test]
fn native_v3_owner_ports_traverse_real_owner_implementations_and_durable_ledger() {
    let objective = objective();
    let compiled = compile_objective(objective.clone())
        .expect("objective compile")
        .expect("objective conflict");
    let objective_digest = compiled.objective.semantic_digest;
    let snapshot = capability_snapshot(objective_digest);
    let legal = legal_candidates(snapshot.digest());

    let temp = tempfile::tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("ledger"))
        .expect("ledger file");
    let mut ledger = DurableLedger::create(file, digest("ledger-binding"), 4).expect("ledger");
    let host = RecordingHost::default();
    let mut ports = NativeV3OwnerPorts::new(
        fixture_inputs(objective, objective_digest, &legal),
        &mut ledger,
        Digest32::ZERO,
        host,
    );

    let receipt = run_composition_v3(run_request(snapshot, legal), &mut ports).expect("V3 run");
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV3::HostHandoffAccepted
    );
    assert!(ports.host().accepted.is_some());
    assert!(ports.learning_append().is_some());
    assert_eq!(ledger.records().expect("records").len(), 1);
    assert!(!receipt.authority.grants_any());
    receipt.validate().expect("receipt validation");
}

#[test]
fn native_v3_rejects_candidate_universe_drift_before_owner_selection() {
    let objective = objective();
    let compiled = compile_objective(objective.clone())
        .expect("objective compile")
        .expect("objective conflict");
    let objective_digest = compiled.objective.semantic_digest;
    let snapshot = capability_snapshot(objective_digest);
    let legal = legal_candidates(snapshot.digest());
    let mut inputs = fixture_inputs(objective, objective_digest, &legal);
    inputs.intuition.candidates[0].candidate_id = id("not-in-legal-set");

    let temp = tempfile::tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("ledger"))
        .expect("ledger file");
    let mut ledger = DurableLedger::create(file, digest("ledger-binding"), 4).expect("ledger");
    let mut ports = NativeV3OwnerPorts::new(
        inputs,
        &mut ledger,
        Digest32::ZERO,
        RecordingHost::default(),
    );

    let receipt = run_composition_v3(run_request(snapshot, legal), &mut ports).expect("receipt");
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV3::Failed(PortFailureClassV3::Rejected)
    );
    assert_eq!(
        receipt.stages.last().map(|stage| stage.stage),
        Some(LaneFStageV3::IntuitionDecided)
    );
    assert!(ledger.records().expect("records").is_empty());
}

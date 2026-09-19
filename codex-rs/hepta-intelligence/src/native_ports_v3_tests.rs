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
use codex_hepta_objective::ObjectiveSourceEnvelope;
use codex_hepta_objective::SourceTrust;
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

fn objective() -> ObjectiveSourceEnvelope {
    ObjectiveSourceEnvelope {
        request_id: id("request.native-v3"),
        principal_scope: id("principal.native-v3"),
        revision: Revision::new(1).expect("revision"),
        source_trust: SourceTrust::PrincipalStructured,
        source_digest: digest("objective-source"),
        schema_digest: digest("objective-schema"),
        constraints: vec![],
        success_predicates: vec![],
        allowed_actions: vec![ActionClass {
            id: id("action.read"),
            confirmation: ConfirmationPolicy::NotRequired,
        }],
        forbidden_actions: vec![],
        soft_preferences: vec![],
    }
}

fn snapshot(objective_digest: Digest32) -> CapabilitySnapshotV2 {
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
    let bindings = pairs
        .iter()
        .map(|(capability, owner)| CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            implementation_digest: digest(&format!("implementation:{owner}")),
            generation: Generation::new(1).expect("generation"),
        })
        .collect::<Vec<_>>();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest,
        authority_epoch: 1,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("capability snapshot")
}

#[derive(Default)]
struct Host {
    accepted: Option<Digest32>,
}

impl HostEnvelopePortV3 for Host {
    fn accept_host_envelope_v3(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        envelope.validate().map_err(|_| PortFailureV3 {
            class: PortFailureClassV3::Rejected,
            evidence_digest: digest("invalid-envelope"),
        })?;
        if input.run_id != envelope.run_id
            || input.snapshot_digest != envelope.snapshot_digest
            || input.predecessor_digest != envelope.envelope_digest
        {
            return Err(PortFailureV3 {
                class: PortFailureClassV3::Rejected,
                evidence_digest: digest("envelope-binding"),
            });
        }
        self.accepted = Some(envelope.envelope_digest);
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer: id("runtime.agentd"),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: digest("agentd-acceptance"),
            decision: PortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[test]
fn native_v3_owner_ports_traverse_real_objective_ndu_eval_intuition_context_and_ledger() {
    let objective = objective();
    let compiled = compile_objective(objective.clone())
        .expect("objective compile")
        .expect("no conflict");
    let objective_digest = compiled.objective.semantic_digest;
    let snapshot = snapshot(objective_digest);

    let legal_candidates = build_legal_candidates_v1(
        id("candidate-set.native-v3"),
        snapshot.digest(),
        digest("legal-grammar"),
        1,
        vec![LegalActionCandidateV1 {
            candidate_id: id("action.read"),
            action_digest: digest("action.read"),
            support_digest: digest("legal-support"),
            support_ppm: 1_000_000,
        }],
    )
    .expect("legal candidates");

    let generation = Generation::new(1).expect("generation");
    let axis = id("quality");
    let utility_set = ContributionSet {
        objective_digest,
        generation,
        contributions: vec![UtilityContribution {
            candidate_id: id("action.read"),
            organ_id: id("planner"),
            objective_digest,
            generation,
            feasibility: FeasibilityPosture::Feasible,
            utility: vec![AxisValue {
                axis: axis.clone(),
                value: FixedQ32::ONE,
            }],
            risk: vec![],
            resource: vec![],
            uncertainty: vec![AxisValue {
                axis: axis.clone(),
                value: FixedQ32::ZERO,
            }],
            support_digest: digest("utility-support"),
        }],
    };
    let utility_profile = UtilityProfile {
        profile_id: id("utility-profile"),
        dimensions: vec![(axis, AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")],
        },
    };

    let evaluation = EvaluationRequest {
        evaluation_id: id("evaluation.native-v3"),
        evaluator_id: id("independent-evaluator"),
        candidate_id: id("action.read"),
        candidate_producer_id: id("intelligence.control"),
        baseline_id: id("baseline"),
        objective_digest,
        comparisons: vec![MetricComparison {
            metric_id: id("metric.quality"),
            direction: Direction::Maximize,
            candidate: FixedQ32::ONE,
            baseline: FixedQ32::ZERO,
            minimum_delta: FixedQ32::ZERO,
            hard: true,
            support_digest: digest("evaluation-support"),
        }],
    };

    let intuition = DecisionRequest {
        decision_id: id("placeholder"),
        objective_digest,
        candidate_set_digest: legal_candidates.candidate_set_digest,
        minimum_confidence: ProbabilityQ32::ZERO,
        candidates: vec![ActionCandidate {
            candidate_id: id("action.read"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::ONE,
            confidence: ProbabilityQ32::ONE,
            support_digest: digest("intuition-support"),
        }],
    };

    let context = CompilationRequest {
        compilation_id: id("context.native-v3"),
        run_snapshot_digest: digest("placeholder-snapshot"),
        objective_digest,
        token_budget: 8,
        items: vec![ContextItem {
            item_id: id("instruction.readonly"),
            role: ContextRole::TrustedInstruction,
            content_digest: digest("instruction"),
            source_digest: digest("instruction-source"),
            token_count: 1,
            contains_secret: false,
        }],
    };

    let temp = tempfile::tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("ledger"))
        .expect("ledger file");
    let mut ledger = DurableLedger::create(file, digest("native-v3-ledger"), 8).expect("ledger");

    let inputs = NativeV3OwnerInputs {
        expected_objective_digest: objective_digest,
        legal_candidates: legal_candidates.clone(),
        objective,
        utility_set,
        utility_profile,
        utility_scalarization: None,
        evaluation,
        neuron: None,
        neuron_previous: None,
        prompt: None,
        intuition,
        context,
        learning: LearningDecisionTemplateV3 {
            episode_id: id("episode.native-v3"),
            policy_id: id("policy.native-v3"),
        },
    };
    let mut ports = NativeV3OwnerPorts::new(inputs, &mut ledger, Digest32::ZERO, Host::default());

    let request = LaneFRunRequestV3 {
        run_id: id("run.native-v3"),
        request_digest: digest("request.native-v3"),
        snapshot,
        legal_candidates,
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
    };

    let receipt = run_composition_v3(request, &mut ports).expect("native V3 composition");
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV3::HostHandoffAccepted
    );
    let envelope = receipt.host_envelope.as_ref().expect("host envelope");
    assert_eq!(ports.host().accepted, Some(envelope.envelope_digest));
    assert!(ports.learning_append().is_some());
    assert_eq!(ledger.records().expect("records").len(), 1);
    receipt.validate().expect("receipt validation");
}

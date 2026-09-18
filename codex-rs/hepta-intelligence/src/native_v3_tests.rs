use std::fs::OpenOptions;

use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_intelligence_eval::Direction;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intelligence_eval::MetricComparison;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_neuron::StepRequest;
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
use codex_hepta_prompt_optimizer::OptimizationRequest;
use codex_hepta_prompt_optimizer::PromptCandidate;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;
use crate::CapabilitySnapshotV2;
use crate::CompositionBudgetV3;
use crate::CompositionControlV3;
use crate::CompositionDispositionV3;
use crate::CompositionRunRequestV3;
use crate::LegalActionCandidateSetV1;
use crate::LegalActionCandidateV1;
use crate::prepare_intelligence_run_v3;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn objective_source() -> ObjectiveSourceEnvelope {
    ObjectiveSourceEnvelope {
        request_id: id("native-v3-request"),
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
            dimension: id("evidence-quality"),
            direction: SoftDirection::Maximize,
            weight: FixedQ32::ONE,
        }],
    }
}

fn snapshot(objective_digest: Digest32) -> CapabilitySnapshotV2 {
    let pairs = [
        ("objective.validation", "objective.compiler", CapabilityNecessityV2::Required),
        ("legal.actions", "intelligence.control", CapabilityNecessityV2::Required),
        ("utility.evaluation", "utility.ndu", CapabilityNecessityV2::Required),
        ("neural.signal", "neuron.runtime", CapabilityNecessityV2::Optional),
        ("prompt.portfolio", "prompt.optimizer", CapabilityNecessityV2::Optional),
        ("intuition.decision", "intuition.policy", CapabilityNecessityV2::Required),
        ("context.compilation", "context.compiler", CapabilityNecessityV2::Required),
        ("evaluation.admission", "learning.eval", CapabilityNecessityV2::Required),
        ("learning.record", "learning.ledger", CapabilityNecessityV2::Required),
        ("dispatch.proposal", "runtime.agentd", CapabilityNecessityV2::Required),
    ];
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
            generation: generation(1),
        })
        .collect::<Vec<_>>();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest,
        authority_epoch: 7,
        body_generation: generation(1),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("snapshot")
}

fn ndu_inputs(objective_digest: Digest32) -> (
    ContributionSet,
    UtilityProfile,
    Option<ScalarizationProfile>,
    EvaluationPolicyV1,
) {
    let axis = id("evidence-quality");
    (
        ContributionSet {
            objective_digest,
            generation: generation(1),
            contributions: vec![
                UtilityContribution {
                    candidate_id: id("abstain"),
                    organ_id: id("planner"),
                    objective_digest,
                    generation: generation(1),
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                    risk: Vec::new(),
                    resource: Vec::new(),
                    uncertainty: vec![AxisValue {
                        axis: axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: digest("ndu-abstain-support"),
                },
                UtilityContribution {
                    candidate_id: id("read-local"),
                    organ_id: id("planner"),
                    objective_digest,
                    generation: generation(1),
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: axis.clone(),
                        value: FixedQ32::ONE,
                    }],
                    risk: Vec::new(),
                    resource: Vec::new(),
                    uncertainty: vec![AxisValue {
                        axis: axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: digest("ndu-support"),
                },
            ],
        },
        UtilityProfile {
            profile_id: id("utility-profile"),
            dimensions: vec![(axis.clone(), AxisDirection::Maximize)],
            risk_ceilings: Vec::new(),
            resource_ceilings: Vec::new(),
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("planner")],
            },
        },
        Some(ScalarizationProfile {
            profile_id: id("scalarization"),
            weights: vec![AxisValue {
                axis: axis.clone(),
                value: FixedQ32::ONE,
            }],
        }),
        EvaluationPolicyV1 {
            policy_id: id("ndu-policy"),
            utility_rules: vec![AxisAggregationRule {
                axis: axis.clone(),
                operator: AggregationOperator::Sum,
            }],
            risk_rules: Vec::new(),
            resource_rules: Vec::new(),
            uncertainty_rules: vec![AxisAggregationRule {
                axis: axis.clone(),
                operator: AggregationOperator::Maximum,
            }],
            pareto_absolute_tolerances: vec![AxisValue {
                axis,
                value: FixedQ32::ZERO,
            }],
        },
    )
}

fn intuition_input(snapshot_digest: Digest32, objective_digest: Digest32) -> CalibratedDecisionRequestV1 {
    let policy = digest("intuition-policy");
    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("read-local"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::ONE,
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest("intuition-support"),
    }];
    CalibratedDecisionRequestV1 {
        decision_id: id("will-be-rebound"),
        objective_digest,
        objective_class_digest: digest("objective-class"),
        state_digest: snapshot_digest,
        policy_digest: policy,
        policy_generation: 1,
        sequence: 1,
        minimum_confidence: ProbabilityQ32::ONE,
        maximum_ece_ppm: 1,
        maximum_ood_false_acceptance_ppm: 1,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("completeness"),
            generator_digest: digest("generator"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            candidate_set_digest: canonical_candidate_set_digest_v1(&candidates)
                .expect("candidate digest"),
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                .expect("order digest"),
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("calibration"),
            policy_digest: policy,
            objective_class_digest: digest("objective-class"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest("subgroup-audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("ood"),
            policy_digest: policy,
            detector_digest: digest("detector"),
            support_digest: digest("ood-support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            maximum_in_domain_score: ProbabilityQ32::ZERO,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    }
}

fn native_inputs(snapshot_digest: Digest32, objective_digest: Digest32) -> NativeCompositionInputsV3 {
    let (utility_contributions, utility_profile, scalarization, evaluation_policy) =
        ndu_inputs(objective_digest);
    let registry = digest("prompt-registry");
    NativeCompositionInputsV3 {
        objective: objective_source(),
        utility_contributions,
        utility_profile,
        scalarization,
        evaluation_policy,
        neuron: Some(NativeNeuronInputV3 {
            request: StepRequest {
                run_id: id("will-be-rebound"),
                model_digest: digest("neuron-model"),
                source_digest: digest("will-be-rebound"),
                generation: generation(1),
                decay: FixedQ32::ZERO,
                features: vec![FixedQ32::ONE],
            },
            previous: None,
        }),
        prompt: Some(OptimizationRequest {
            decision_id: id("will-be-rebound"),
            objective_digest,
            registry_snapshot_digest: registry,
            budget: 16,
            maximum_selected: 1,
            candidates: vec![PromptCandidate {
                candidate_id: id("prompt-factor"),
                factor_id: id("factor"),
                realization_id: id("realization"),
                admitted: true,
                legal: true,
                expected_gain: FixedQ32::ONE,
                cost: 1,
                registry_digest: registry,
                support_digest: digest("prompt-support"),
            }],
        }),
        intuition: intuition_input(snapshot_digest, objective_digest),
        context: CompilationRequest {
            compilation_id: id("context"),
            run_snapshot_digest: snapshot_digest,
            objective_digest,
            token_budget: 16,
            items: vec![ContextItem {
                item_id: id("trusted-instruction"),
                role: ContextRole::TrustedInstruction,
                content_digest: digest("instruction-content"),
                source_digest: digest("instruction-source"),
                token_count: 1,
                contains_secret: false,
            }],
        },
        evaluation: EvaluationRequest {
            evaluation_id: id("evaluation"),
            evaluator_id: id("independent-evaluator"),
            candidate_id: id("policy"),
            candidate_producer_id: id("will-be-rebound"),
            baseline_id: id("baseline"),
            objective_digest,
            comparisons: vec![MetricComparison {
                metric_id: id("quality"),
                direction: Direction::Maximize,
                candidate: FixedQ32::ONE,
                baseline: FixedQ32::ZERO,
                minimum_delta: FixedQ32::ZERO,
                hard: true,
                support_digest: digest("evaluation-support"),
            }],
        },
        episode_id: id("episode"),
        policy_id: id("policy"),
        expected_ledger_head: Digest32::ZERO,
    }
}

struct FixedControl(u64);

impl CompositionControlV3 for FixedControl {
    fn now_micros(&self) -> u64 {
        self.0
    }

    fn is_cancelled(&self) -> bool {
        false
    }
}

#[test]
fn v3_native_adapters_traverse_real_owner_libraries_and_durable_ledger() {
    let objective = compile_objective(objective_source())
        .expect("objective compile")
        .expect("objective conflict");
    let objective_digest = objective.objective.semantic_digest;
    let snapshot = snapshot(objective_digest);
    let candidate_set = LegalActionCandidateSetV1::new(
        id("candidate-set"),
        snapshot.digest(),
        id("intelligence.control"),
        digest("grammar"),
        vec![LegalActionCandidateV1 {
            candidate_id: id("read-local"),
            support_digest: digest("legal-support"),
            support_ppm: 1_000_000,
        }],
        500_000,
    )
    .expect("candidate set");

    let temp = tempfile::tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("learning-ledger"))
        .expect("ledger file");
    let mut ledger = DurableLedger::create(file, digest("ledger-binding"), 8).expect("ledger");
    let inputs = native_inputs(snapshot.digest(), objective_digest);
    let mut ports = NativeCompositionPortsV3::new(candidate_set.clone(), inputs, &mut ledger);
    let request = CompositionRunRequestV3 {
        run_id: id("run:native-v3"),
        request_digest: digest("request"),
        snapshot,
        body_digest: digest("body"),
        artifact_set_digest: digest("artifacts"),
        started_at_micros: 1_000,
        deadline_micros: 10_000,
        budget: CompositionBudgetV3 {
            total_micros: 2_000,
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
        candidate_set,
    };

    let prepared = prepare_intelligence_run_v3(request, &mut ports, &FixedControl(1_000))
        .expect("native composition");
    assert_eq!(
        prepared.disposition,
        CompositionDispositionV3::ReadyForDispatch
    );
    assert!(prepared.envelope.is_some());
    assert!(ports.objective_receipt().is_some());
    assert!(ports.utility_receipt().is_some());
    assert!(ports.neuron_receipt().is_some());
    assert!(ports.prompt_receipt().is_some());
    assert!(ports.intuition_receipt().is_some());
    assert!(ports.context_receipt().is_some());
    assert!(ports.evaluation_receipt().is_some());
    assert!(ports.decision_append().is_some());
    drop(ports);
    assert_eq!(ledger.records().expect("ledger records").len(), 1);
}

#[test]
fn v3_native_abstention_is_durable_without_context_or_evaluation() {
    let objective = compile_objective(objective_source())
        .expect("objective compile")
        .expect("objective conflict");
    let objective_digest = objective.objective.semantic_digest;
    let snapshot = snapshot(objective_digest);
    let candidate_set = LegalActionCandidateSetV1::new(
        id("candidate-set-abstain"),
        snapshot.digest(),
        id("intelligence.control"),
        digest("grammar"),
        vec![LegalActionCandidateV1 {
            candidate_id: id("read-local"),
            support_digest: digest("legal-support"),
            support_ppm: 1_000_000,
        }],
        500_000,
    )
    .expect("candidate set");

    let temp = tempfile::tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("learning-ledger-abstain"))
        .expect("ledger file");
    let mut ledger = DurableLedger::create(file, digest("ledger-binding"), 8).expect("ledger");

    let mut inputs = native_inputs(snapshot.digest(), objective_digest);
    inputs.intuition.candidates[0].legal = false;
    inputs.intuition.completeness.candidate_set_digest =
        canonical_candidate_set_digest_v1(&inputs.intuition.candidates)
            .expect("candidate digest");
    inputs.intuition.completeness.canonical_order_digest =
        canonical_candidate_order_digest_v1(&inputs.intuition.candidates)
            .expect("order digest");

    let mut ports =
        NativeCompositionPortsV3::new(candidate_set.clone(), inputs, &mut ledger);
    let request = CompositionRunRequestV3 {
        run_id: id("run:native-v3-abstain"),
        request_digest: digest("request-abstain"),
        snapshot,
        body_digest: digest("body"),
        artifact_set_digest: digest("artifacts"),
        started_at_micros: 1_000,
        deadline_micros: 10_000,
        budget: CompositionBudgetV3 {
            total_micros: 2_000,
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
        candidate_set,
    };

    let prepared = prepare_intelligence_run_v3(request, &mut ports, &FixedControl(1_000))
        .expect("native abstention");
    assert_eq!(prepared.disposition, CompositionDispositionV3::Abstained);
    assert!(prepared.envelope.is_none());
    assert!(ports.context_receipt().is_none());
    assert!(ports.evaluation_receipt().is_none());
    assert!(ports.decision_append().is_some());
    drop(ports);

    let records = ledger.records().expect("ledger records");
    assert_eq!(records.len(), 1);
    let LedgerEvent::Decision(decision) = &records[0].event else {
        panic!("expected durable Decision");
    };
    assert_eq!(decision.selected_candidate_id, id("abstain"));
    assert!(decision.selected_propensity.raw() > 0);
}


use std::fmt::Debug;

use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::CreditAssignment;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::OutcomeFinality;
use codex_hepta_learning_ledger::OutcomeObservation;
use codex_hepta_learning_ledger::Revocation;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisLimit;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationDisposition;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates;
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
use codex_hepta_objective::compile;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn manifest(artifact_id: &str, objective_digest: Digest32) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id(artifact_id),
        kind: ArtifactKind::Policy,
        generation: must(Generation::new(1)),
        predecessor_id: None,
        content_digest: Digest32::of_bytes(artifact_id.as_bytes()),
        objective_digest,
        support_digest: Digest32::of_bytes(b"generator-support"),
        producer_id: id("candidate-generator"),
        compatibility_digest: Digest32::of_bytes(b"policy-abi-v1"),
        encoded_size_bytes: 64,
    }
}

fn contribution(
    candidate_id: &str,
    objective_digest: Digest32,
    success: i64,
    feasibility: FeasibilityPosture,
) -> UtilityContribution {
    UtilityContribution {
        candidate_id: id(candidate_id),
        organ_id: id("planner"),
        objective_digest,
        generation: must(Generation::new(1)),
        feasibility,
        utility: vec![AxisValue {
            axis: id("success"),
            value: FixedQ32::from_raw(success << 32),
        }],
        risk: vec![AxisValue {
            axis: id("privacy-risk"),
            value: FixedQ32::ZERO,
        }],
        resource: vec![AxisValue {
            axis: id("compute"),
            value: FixedQ32::ONE,
        }],
        uncertainty: vec![AxisValue {
            axis: id("success"),
            value: FixedQ32::ZERO,
        }],
        support_digest: Digest32::of_bytes(candidate_id.as_bytes()),
    }
}

#[test]
fn objective_to_ndu_to_independent_learning_ledger_is_replayable_and_revocable() {
    let compiled = must(must(compile(ObjectiveSourceEnvelope {
        request_id: id("request-value-learning-1"),
        principal_scope: id("principal:alpha"),
        revision: must(Revision::new(1)),
        source_trust: SourceTrust::PrincipalStructured,
        source_digest: Digest32::of_bytes(b"structured-request"),
        schema_digest: Digest32::of_bytes(b"objective-schema-v1"),
        constraints: vec![Constraint {
            id: id("privacy-ceiling"),
            class: ConstraintClass::Constitutional,
            axis: id("privacy-risk"),
            relation: ConstraintRelation::AtMost,
            bound: FixedQ32::ZERO,
            evidence_source: id("constitution-v1"),
        }],
        success_predicates: vec![SuccessPredicate {
            id: id("terminal-success"),
            axis: id("success"),
            relation: ConstraintRelation::AtLeast,
            bound: FixedQ32::ONE,
            evidence_source: id("independent-observer"),
            terminality: PredicateTerminality::Terminal,
        }],
        allowed_actions: vec![
            ActionClass {
                id: id("policy-safe"),
                confirmation: ConfirmationPolicy::NotRequired,
            },
            ActionClass {
                id: id("policy-unsafe"),
                confirmation: ConfirmationPolicy::NotRequired,
            },
        ],
        forbidden_actions: Vec::new(),
        soft_preferences: vec![SoftPreference {
            dimension: id("success"),
            direction: SoftDirection::Maximize,
            weight: FixedQ32::ONE,
        }],
    })));
    let objective_digest = compiled.objective.semantic_digest;

    let mut artifacts = ArtifactRegistry::new();
    for artifact_id in ["abstain", "policy-safe", "policy-unsafe"] {
        must(artifacts.append(ArtifactEvent::Register {
            event_id: id(&format!("register-{artifact_id}")),
            manifest: manifest(artifact_id, objective_digest),
        }));
    }
    assert_eq!(
        artifacts
            .eligible_candidates(ArtifactKind::Policy, objective_digest)
            .len(),
        3
    );

    let evaluation = must(evaluate_candidates(
        ContributionSet {
            objective_digest,
            generation: must(Generation::new(1)),
            contributions: vec![
                contribution("abstain", objective_digest, 0, FeasibilityPosture::Feasible),
                contribution(
                    "policy-safe",
                    objective_digest,
                    1,
                    FeasibilityPosture::Feasible,
                ),
                contribution(
                    "policy-unsafe",
                    objective_digest,
                    100,
                    FeasibilityPosture::HardConstraintViolation,
                ),
            ],
        },
        UtilityProfile {
            profile_id: id("utility-profile-v1"),
            dimensions: vec![(id("success"), AxisDirection::Maximize)],
            risk_ceilings: vec![AxisLimit {
                axis: id("privacy-risk"),
                maximum: FixedQ32::ZERO,
            }],
            resource_ceilings: vec![AxisLimit {
                axis: id("compute"),
                maximum: FixedQ32::from_raw(10_i64 << 32),
            }],
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("planner")],
            },
        },
        None,
    ));
    assert_eq!(
        evaluation.disposition,
        EvaluationDisposition::UniqueParetoRecommendation
    );
    assert_eq!(evaluation.advisory_recommendation, Some(id("policy-safe")));
    assert_eq!(evaluation.rejected_candidates.len(), 1);

    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::Decision(EpisodeDecision {
        record_id: id("decision-record-1"),
        episode_id: id("episode-1"),
        objective_digest,
        policy_id: id("policy-controller"),
        candidate_ids: vec![id("abstain"), id("policy-safe"), id("policy-unsafe")],
        selected_candidate_id: id("policy-safe"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: evaluation.evaluation_digest,
    })));
    must(ledger.append(LedgerEvent::Outcome(OutcomeObservation {
        record_id: id("outcome-record-1"),
        outcome_id: id("outcome-1"),
        episode_id: id("episode-1"),
        observer_id: id("independent-observer"),
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: Digest32::of_bytes(b"terminal-observation"),
    })));
    must(ledger.append(LedgerEvent::Credit(CreditAssignment {
        record_id: id("credit-record-1"),
        credit_id: id("credit-1"),
        episode_id: id("episode-1"),
        outcome_id: id("outcome-1"),
        target_artifact_id: id("policy-safe"),
        allocator_id: id("independent-credit-evaluator"),
        credit: FixedQ32::ONE,
        support_digest: Digest32::of_bytes(b"credit-receipt"),
    })));

    let restored_ledger = must(LearningLedger::from_snapshot(ledger.snapshot()));
    let restored_artifacts = must(ArtifactRegistry::from_snapshot(artifacts.snapshot()));
    assert_eq!(restored_ledger.snapshot(), ledger.snapshot());
    assert_eq!(restored_artifacts.snapshot(), artifacts.snapshot());

    must(ledger.append(LedgerEvent::Revocation(Revocation {
        record_id: id("revoke-decision-record-1"),
        target_record_id: id("decision-record-1"),
        authority_id: id("deletion-authority"),
        reason_digest: Digest32::of_bytes(b"unlearning-request"),
    })));
    must(artifacts.append(ArtifactEvent::Revoke(StateChange {
        event_id: id("revoke-policy-safe"),
        artifact_id: id("policy-safe"),
        evaluator_id: id("deletion-authority"),
        reason_digest: Digest32::of_bytes(b"unlearning-request"),
    })));

    assert_eq!(ledger.active_records().len(), 1);
    assert!(!artifacts.is_eligible(&id("policy-safe")));
}

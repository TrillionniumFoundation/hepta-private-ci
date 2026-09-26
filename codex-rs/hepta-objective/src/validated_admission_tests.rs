use super::*;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;

use crate::ConstraintClass;
use crate::ObjectiveAbstentionRuleProfileV1;
use crate::ObjectiveActionProfileV1;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveEvidenceProfileV1;
use crate::ObjectiveEvidenceRequirementV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveProvenanceV1;
use crate::ObjectiveResourceAxisProfileV1;
use crate::ObjectiveResourceProfileV1;
use crate::ObjectiveResourcesV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRiskProfileV1;
use crate::ObjectiveRiskV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSoftDimensionProfileV1;
use crate::ObjectiveSoftDimensionV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceConstraintV1;
use crate::ObjectiveSourcePredicateV1;
use crate::ObjectiveStructuredIntentV1;

const NOW_MICROS: u64 = 1_788_861_601_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn resource_axis(name: &str, class: ConstraintClass) -> ObjectiveResourceAxisProfileV1 {
    ObjectiveResourceAxisProfileV1 {
        constraint_id: id(&format!("resource.{name}.ceiling")),
        axis: id(&format!("resource.{name}")),
        class,
        q32_per_source_unit: FixedQ32::from_raw(1),
        evidence_source: id("objective.resource.profile"),
    }
}

fn profile() -> ObjectiveAdmissionProfileV1 {
    ObjectiveAdmissionProfileV1 {
        profile_id: id("objective.profile.readonly.v1"),
        profile_revision: Revision::new(1).expect("revision"),
        expected_input_schema_digest: digest("schema-v1"),
        expected_normalization_profile_digest: digest("normalization-v1"),
        principal_scope_digest: digest("principal-scope"),
        principal_scope: id("principal.alpha"),
        allowed_locales: vec!["en-US".to_owned()],
        maximum_source_age_micros: 60_000_000,
        maximum_future_skew_micros: 1_000_000,
        deadline_required: true,
        allowed_trusted_source_identities: vec![id("adapter.console")],
        constraints: vec![crate::ObjectiveConstraintProfileV1 {
            source_constraint_id: "latency.ceiling".to_owned(),
            expected_unit: "micros".to_owned(),
            class: ConstraintClass::Task,
            axis: id("latency.micros"),
        }],
        predicates: vec![
            crate::ObjectivePredicateProfileV1 {
                source_predicate_id: "task.success".to_owned(),
                expected_unit: "ratio".to_owned(),
                axis: id("task.success.ratio"),
            },
            crate::ObjectivePredicateProfileV1 {
                source_predicate_id: "task.terminal".to_owned(),
                expected_unit: "boolean".to_owned(),
                axis: id("task.terminal"),
            },
        ],
        actions: vec![
            ObjectiveActionProfileV1 {
                source_action_class: "read".to_owned(),
                action_id: id("action.read"),
            },
            ObjectiveActionProfileV1 {
                source_action_class: "network".to_owned(),
                action_id: id("action.network"),
            },
        ],
        soft_dimensions: vec![ObjectiveSoftDimensionProfileV1 {
            source_dimension_id: "quality".to_owned(),
            expected_unit: "ratio".to_owned(),
            expected_direction: ObjectiveSoftDirectionV1::Maximize,
            dimension: id("quality.ratio"),
            baseline_weight: FixedQ32::from_raw(1_i64 << 31),
        }],
        evidence_requirements: vec![ObjectiveEvidenceProfileV1 {
            source_requirement_id: "evidence.quality".to_owned(),
            axis: id("evidence.confidence"),
        }],
        resources: ObjectiveResourceProfileV1 {
            time_micros: resource_axis("time", ConstraintClass::Task),
            token_count: resource_axis("tokens", ConstraintClass::Task),
            compute_micros: resource_axis("compute", ConstraintClass::Environment),
            memory_bytes: resource_axis("memory", ConstraintClass::Environment),
            network_bytes: resource_axis("network", ConstraintClass::Principal),
            external_effect_count: resource_axis("effects", ConstraintClass::Principal),
        },
        risk: ObjectiveRiskProfileV1 {
            evidence_source: id("objective.risk.profile"),
            class: ConstraintClass::Principal,
            risk_constraint_id: id("risk.class"),
            risk_axis: id("risk.class.value"),
            low_value: FixedQ32::from_raw(0),
            medium_value: FixedQ32::from_raw(1),
            high_value: FixedQ32::from_raw(2),
            critical_value: FixedQ32::from_raw(3),
            rollback_constraint_id: id("risk.rollback"),
            rollback_axis: id("risk.rollback.value"),
            rollback_none_value: FixedQ32::from_raw(0),
            rollback_reversible_value: FixedQ32::from_raw(1),
            rollback_compensatable_value: FixedQ32::from_raw(2),
            rollback_irreversible_value: FixedQ32::from_raw(3),
            compensation_constraint_id: id("risk.compensation"),
            compensation_axis: id("risk.compensation.value"),
            compensation_false_value: FixedQ32::from_raw(0),
            compensation_true_value: FixedQ32::from_raw(1),
            abstention_constraint_id: id("risk.abstention"),
            abstention_axis: id("risk.abstention.value"),
            abstention_rules: vec![ObjectiveAbstentionRuleProfileV1 {
                source_rule: "ask".to_owned(),
                value: FixedQ32::from_raw(1),
            }],
        },
    }
}

fn source() -> ObjectiveSourceEnvelopeV1 {
    let mut source = ObjectiveSourceEnvelopeV1 {
        request_id: "request.001".to_owned(),
        principal_scope_digest: digest("principal-scope"),
        intent_digest: Digest32::ZERO,
        structured_intent: ObjectiveStructuredIntentV1 {
            success_predicates: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.success".to_owned(),
                unit: "ratio".to_owned(),
                comparator: ObjectivePredicateComparatorV1::GreaterThanOrEqual,
                bound_q32: 1_i64 << 31,
                evidence_source_id: "observer.task".to_owned(),
                terminal: false,
            }],
            terminal_conditions: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.terminal".to_owned(),
                unit: "boolean".to_owned(),
                comparator: ObjectivePredicateComparatorV1::Equal,
                bound_q32: FixedQ32::ONE.raw(),
                evidence_source_id: "observer.task".to_owned(),
                terminal: true,
            }],
            legal_action_classes: vec!["read".to_owned()],
            forbidden_action_classes: vec!["network".to_owned()],
            confirmation_action_classes: Vec::new(),
            constraints: vec![ObjectiveSourceConstraintV1 {
                constraint_id: "latency.ceiling".to_owned(),
                unit: "micros".to_owned(),
                comparator: ObjectiveConstraintComparatorV1::LessThanOrEqual,
                bound_q32: 5_000,
                evidence_source_id: "observer.clock".to_owned(),
                terminal: false,
            }],
            soft_dimensions: vec![ObjectiveSoftDimensionV1 {
                dimension_id: "quality".to_owned(),
                unit: "ratio".to_owned(),
                direction: ObjectiveSoftDirectionV1::Maximize,
                minimum_weight_q32: 0,
                maximum_weight_q32: FixedQ32::ONE.raw(),
            }],
            evidence_requirements: vec![ObjectiveEvidenceRequirementV1 {
                requirement_id: "evidence.quality".to_owned(),
                evidence_source_id: "observer.evidence".to_owned(),
                minimum_confidence_ppm: 900_000,
                terminal: true,
            }],
            resources: ObjectiveResourcesV1 {
                time_micros: 10_000,
                token_count: 1_000,
                compute_micros: 50_000,
                memory_bytes: 1_048_576,
                network_bytes: 0,
                external_effect_count: 0,
            },
            risk: ObjectiveRiskV1 {
                risk_class: ObjectiveRiskClassV1::Low,
                abstention_rule: "ask".to_owned(),
                rollback_class: ObjectiveRollbackClassV1::Reversible,
                compensation_required: false,
            },
            provenance: ObjectiveProvenanceV1 {
                source_digest: digest("source-bytes"),
                normalization_profile_digest: digest("normalization-v1"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::Principal,
        locale: "en-US".to_owned(),
        observed_at: "2026-09-08T10:00:00Z".to_owned(),
        deadline: Some("2026-09-08T10:05:00Z".to_owned()),
        input_schema_digest: digest("schema-v1"),
    };
    source.intent_digest = canonical_objective_intent_digest_v1(&source).expect("intent");
    source
}

fn context(
    profile: &ObjectiveAdmissionProfileV1,
    source: &ObjectiveSourceEnvelopeV1,
) -> ObjectiveAdmissionContextV1 {
    ObjectiveAdmissionContextV1 {
        revision: Revision::new(7).expect("revision"),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: source.principal_scope_digest,
            source_digest: source.structured_intent.provenance.source_digest,
        },
    }
}

#[test]
fn validated_profile_builds_indexes_and_rejects_duplicate_targets() {
    let profile = profile();
    let validated = ValidatedAdmissionProfileV1::from_profile(&profile).expect("validated");
    assert_eq!(
        validated.action("read").map(|mapping| &mapping.action_id),
        Some(&id("action.read"))
    );
    assert!(validated.constraint("latency.ceiling").is_some());
    assert!(validated.owns_semantic_id(&id("risk.class")));

    let mut duplicate = profile;
    duplicate.actions[1].action_id = duplicate.actions[0].action_id.clone();
    assert!(ValidatedAdmissionProfileV1::new(duplicate).is_err());
}

#[test]
fn validated_profile_rejects_cross_collection_semantic_collision() {
    let mut profile = profile();
    profile.evidence_requirements[0].source_requirement_id = "latency.ceiling".to_owned();
    assert!(ValidatedAdmissionProfileV1::new(profile).is_err());
}

#[test]
fn authoritative_admission_rejects_sub_millisecond_deadline() {
    let profile = profile();
    let validated = ValidatedAdmissionProfileV1::from_profile(&profile).expect("validated");
    let mut source = source();
    source.deadline = Some("2026-09-08T10:05:00.000001Z".to_owned());
    let context = context(&profile, &source);

    assert!(matches!(
        admit_validated_objective_v1(&source, &validated, &context),
        Err(ObjectiveAdmissionError::InvalidTimestamp(
            "deadline millisecond precision"
        ))
    ));
}

#[test]
fn proof_binds_source_profile_context_and_compiler_contract() {
    let profile = profile();
    let validated = ValidatedAdmissionProfileV1::from_profile(&profile).expect("validated");
    let source = source();
    let context = context(&profile, &source);
    let first = compile_authoritative_objective_v1(&source, &validated, &context)
        .expect("authoritative compile");
    assert!(!first.proof().proof_digest().is_zero());
    assert_eq!(first.proof().profile_digest(), validated.profile_digest());
    assert_eq!(
        first.proof().admitted_source_digest(),
        first.outcome().receipt.admitted_source_digest
    );

    let mut later_context = context;
    later_context.now_unix_micros += 1_000;
    let second = compile_authoritative_objective_v1(&source, &validated, &later_context)
        .expect("second authoritative compile");
    assert_ne!(first.proof().proof_digest(), second.proof().proof_digest());
    assert_eq!(first.outcome().compile_result, second.outcome().compile_result);
}

#[test]
fn explicit_preflight_matches_authoritative_native_outcome() {
    let profile = profile();
    let source = source();
    let context = context(&profile, &source);
    let preflight =
        preflight_validate_objective_v1(&source, &profile, &context).expect("preflight");
    let validated = ValidatedAdmissionProfileV1::from_profile(&profile).expect("validated");
    let authoritative = compile_authoritative_objective_v1(&source, &validated, &context)
        .expect("authoritative");

    assert_eq!(preflight, authoritative);
}

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::ObjectiveAbstentionRuleProfileV1;
use super::ObjectiveActionProfileV1;
use super::ObjectiveAdmissionContextV1;
use super::ObjectiveAdmissionError;
use super::ObjectiveAdmissionProfileV1;
use super::ObjectiveConstraintProfileV1;
use super::ObjectiveEvidenceProfileV1;
use super::ObjectivePredicateProfileV1;
use super::ObjectiveResourceAxisProfileV1;
use super::ObjectiveResourceProfileV1;
use super::ObjectiveRiskProfileV1;
use super::ObjectiveSoftDimensionProfileV1;
use super::ObjectiveSourceAuthenticationV1;
use super::admit_and_compile_objective_v1;
use super::canonical_objective_intent_digest_v1;
use crate::ConfirmationPolicy;
use crate::ConstraintClass;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveEvidenceRequirementV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveProvenanceV1;
use crate::ObjectiveResourcesV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRiskV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSoftDimensionV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceConstraintV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourcePredicateV1;
use crate::ObjectiveSourceTrustV1;
use crate::ObjectiveStructuredIntentV1;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("valid stable ID")
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
        allowed_locales: vec!["en-US".to_string()],
        maximum_source_age_micros: 60_000_000,
        maximum_future_skew_micros: 1_000_000,
        deadline_required: true,
        allowed_trusted_source_identities: vec![id("adapter.console")],
        constraints: vec![ObjectiveConstraintProfileV1 {
            source_constraint_id: "latency.ceiling".to_string(),
            expected_unit: "micros".to_string(),
            class: ConstraintClass::Task,
            axis: id("latency.micros"),
        }],
        predicates: vec![
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.success".to_string(),
                expected_unit: "ratio".to_string(),
                axis: id("task.success.ratio"),
            },
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.terminal".to_string(),
                expected_unit: "boolean".to_string(),
                axis: id("task.terminal"),
            },
        ],
        actions: vec![
            ObjectiveActionProfileV1 {
                source_action_class: "read".to_string(),
                action_id: id("action.read"),
            },
            ObjectiveActionProfileV1 {
                source_action_class: "inspect".to_string(),
                action_id: id("action.inspect"),
            },
            ObjectiveActionProfileV1 {
                source_action_class: "network".to_string(),
                action_id: id("action.network"),
            },
        ],
        soft_dimensions: vec![ObjectiveSoftDimensionProfileV1 {
            source_dimension_id: "quality".to_string(),
            expected_unit: "ratio".to_string(),
            expected_direction: ObjectiveSoftDirectionV1::Maximize,
            dimension: id("quality.ratio"),
            baseline_weight: FixedQ32::from_raw(1_i64 << 31),
        }],
        evidence_requirements: vec![ObjectiveEvidenceProfileV1 {
            source_requirement_id: "evidence.quality".to_string(),
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
                source_rule: "ask".to_string(),
                value: FixedQ32::from_raw(1),
            }],
        },
    }
}

fn envelope() -> ObjectiveSourceEnvelopeV1 {
    let source_digest = digest("source-bytes");
    let mut envelope = ObjectiveSourceEnvelopeV1 {
        request_id: "request.001".to_string(),
        principal_scope_digest: digest("principal-scope"),
        intent_digest: Digest32::ZERO,
        structured_intent: ObjectiveStructuredIntentV1 {
            success_predicates: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.success".to_string(),
                unit: "ratio".to_string(),
                comparator: ObjectivePredicateComparatorV1::GreaterThanOrEqual,
                bound_q32: 1_i64 << 31,
                evidence_source_id: "observer.task".to_string(),
                terminal: false,
            }],
            terminal_conditions: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.terminal".to_string(),
                unit: "boolean".to_string(),
                comparator: ObjectivePredicateComparatorV1::Equal,
                bound_q32: FixedQ32::ONE.raw(),
                evidence_source_id: "observer.task".to_string(),
                terminal: true,
            }],
            legal_action_classes: vec!["read".to_string(), "inspect".to_string()],
            forbidden_action_classes: vec!["network".to_string()],
            confirmation_action_classes: vec!["inspect".to_string()],
            constraints: vec![ObjectiveSourceConstraintV1 {
                constraint_id: "latency.ceiling".to_string(),
                unit: "micros".to_string(),
                comparator: ObjectiveConstraintComparatorV1::LessThanOrEqual,
                bound_q32: 5_000,
                evidence_source_id: "observer.clock".to_string(),
                terminal: false,
            }],
            soft_dimensions: vec![ObjectiveSoftDimensionV1 {
                dimension_id: "quality".to_string(),
                unit: "ratio".to_string(),
                direction: ObjectiveSoftDirectionV1::Maximize,
                minimum_weight_q32: 0,
                maximum_weight_q32: FixedQ32::ONE.raw(),
            }],
            evidence_requirements: vec![ObjectiveEvidenceRequirementV1 {
                requirement_id: "evidence.quality".to_string(),
                evidence_source_id: "observer.evidence".to_string(),
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
                abstention_rule: "ask".to_string(),
                rollback_class: ObjectiveRollbackClassV1::Reversible,
                compensation_required: false,
            },
            provenance: ObjectiveProvenanceV1 {
                source_digest,
                normalization_profile_digest: digest("normalization-v1"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::Principal,
        locale: "en-US".to_string(),
        observed_at: "2026-09-08T10:00:00Z".to_string(),
        deadline: Some("2026-09-08T10:05:00Z".to_string()),
        input_schema_digest: digest("schema-v1"),
    };
    envelope.intent_digest =
        canonical_objective_intent_digest_v1(&envelope).expect("canonical intent digest");
    envelope
}

fn context(
    profile: &ObjectiveAdmissionProfileV1,
    envelope: &ObjectiveSourceEnvelopeV1,
) -> ObjectiveAdmissionContextV1 {
    ObjectiveAdmissionContextV1 {
        revision: Revision::new(7).expect("revision"),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: envelope.principal_scope_digest,
            source_digest: envelope.structured_intent.provenance.source_digest,
        },
    }
}

fn refresh_intent_digest(envelope: &mut ObjectiveSourceEnvelopeV1) {
    envelope.intent_digest =
        canonical_objective_intent_digest_v1(envelope).expect("canonical intent digest");
}

#[test]
fn complete_profile_bound_envelope_compiles_without_dropping_fields() {
    let profile = profile();
    let envelope = envelope();
    let context = context(&profile, &envelope);

    let outcome =
        admit_and_compile_objective_v1(&envelope, &profile, &context).expect("admit and compile");
    assert!(!outcome.receipt.authority.grants_any());
    assert_eq!(OBSERVED_MICROS, outcome.receipt.observed_at_unix_micros);
    assert_eq!(
        Some(OBSERVED_MICROS + 300_000_000),
        outcome.receipt.deadline_unix_micros
    );
    assert_eq!(envelope.intent_digest, outcome.receipt.intent_digest);
    assert_ne!(Digest32::ZERO, outcome.receipt.admitted_source_digest);

    let compiled = outcome.compile_result.expect("compiled objective");
    assert_eq!(11, compiled.objective.constraints.len());
    assert_eq!(3, compiled.objective.success_predicates.len());
    assert_eq!(3, compiled.objective.legal_actions.len());
    assert!(compiled.objective.legal_actions.iter().any(|action| {
        action.id == id("action.inspect") && action.confirmation == ConfirmationPolicy::Required
    }));
    assert!(
        compiled
            .objective
            .legal_actions
            .iter()
            .any(|action| action.id == id("abstain"))
    );
    assert_eq!(1, compiled.objective.soft_preferences.len());
    assert_eq!(
        Revision::new(7).expect("revision"),
        compiled.objective.revision
    );
}

#[test]
fn semantic_array_reordering_preserves_intent_digest() {
    let first = envelope();
    let mut second = first.clone();
    second.structured_intent.legal_action_classes.reverse();
    second.structured_intent.success_predicates.reverse();
    second.structured_intent.constraints.reverse();

    assert_eq!(
        canonical_objective_intent_digest_v1(&first).expect("first digest"),
        canonical_objective_intent_digest_v1(&second).expect("second digest")
    );
}

#[test]
fn selected_profile_digest_must_bind_exact_mapping() {
    let profile = profile();
    let envelope = envelope();
    let mut context = context(&profile, &envelope);
    context.selected_profile_digest = digest("different-profile");

    assert_eq!(
        ObjectiveAdmissionError::ProfileDigestMismatch,
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("profile mismatch must reject")
    );
}

#[test]
fn strict_or_unregistered_comparator_is_never_approximated() {
    let profile = profile();
    let mut envelope = envelope();
    envelope.structured_intent.constraints[0].comparator =
        ObjectiveConstraintComparatorV1::LessThan;
    refresh_intent_digest(&mut envelope);
    let context = context(&profile, &envelope);

    assert_eq!(
        ObjectiveAdmissionError::UnsupportedComparator,
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("strict comparator must reject")
    );
}

#[test]
fn unknown_semantic_mapping_is_rejected_before_native_compile() {
    let profile = profile();
    let mut envelope = envelope();
    envelope.structured_intent.constraints[0].constraint_id = "latency.other".to_string();
    refresh_intent_digest(&mut envelope);
    let context = context(&profile, &envelope);

    assert_eq!(
        ObjectiveAdmissionError::UnknownConstraint,
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("unknown constraint must reject")
    );
}

#[test]
fn stale_observation_is_not_rewritten_to_current_time() {
    let profile = profile();
    let envelope = envelope();
    let mut context = context(&profile, &envelope);
    context.now_unix_micros = OBSERVED_MICROS + 61_000_000;

    assert_eq!(
        ObjectiveAdmissionError::SourceStale,
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("stale observation must reject")
    );
}

#[test]
fn resource_conversion_overflow_rejects_without_truncation() {
    let profile = profile();
    let mut envelope = envelope();
    envelope.structured_intent.resources.memory_bytes = u64::MAX;
    refresh_intent_digest(&mut envelope);
    let context = context(&profile, &envelope);

    assert_eq!(
        ObjectiveAdmissionError::ResourceOverflow("memoryBytes"),
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("overflow must reject")
    );
}

#[test]
fn supplied_principal_label_cannot_replace_authenticated_principal() {
    let profile = profile();
    let envelope = envelope();
    let mut context = context(&profile, &envelope);
    context.source_authentication = ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
        source_identity: id("adapter.console"),
        source_digest: envelope.structured_intent.provenance.source_digest,
    };

    assert_eq!(
        ObjectiveAdmissionError::SourceAuthenticationMismatch,
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("trust mismatch must reject")
    );
}

#[test]
fn untrusted_evidence_reaches_native_authority_rejection() {
    let profile = profile();
    let mut envelope = envelope();
    envelope.source_trust_class = ObjectiveSourceTrustV1::UntrustedEvidence;
    let mut context = context(&profile, &envelope);
    context.source_authentication = ObjectiveSourceAuthenticationV1::UntrustedEvidence {
        source_digest: envelope.structured_intent.provenance.source_digest,
    };

    assert_eq!(
        ObjectiveAdmissionError::Compiler(crate::ObjectiveError::UntrustedAuthorityEscalation),
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("untrusted action authority must reject")
    );
}

#[test]
fn fractional_utc_timestamp_is_parsed_exactly() {
    let profile = profile();
    let mut envelope = envelope();
    envelope.observed_at = "2026-09-08T10:00:00.123456Z".to_string();
    envelope.deadline = Some("2026-09-08T10:05:00.123456Z".to_string());
    let mut context = context(&profile, &envelope);
    context.now_unix_micros = OBSERVED_MICROS + 123_456;

    let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
        .expect("fractional UTC timestamp");
    assert_eq!(
        OBSERVED_MICROS + 123_456,
        outcome.receipt.observed_at_unix_micros
    );
    assert_eq!(
        Some(OBSERVED_MICROS + 300_123_456),
        outcome.receipt.deadline_unix_micros
    );
}

#[test]
fn oversized_profile_mapping_set_is_rejected() {
    let mut profile = profile();
    profile.constraints = (0..257)
        .map(|index| ObjectiveConstraintProfileV1 {
            source_constraint_id: format!("constraint.{index}"),
            expected_unit: "unit".to_string(),
            class: ConstraintClass::Task,
            axis: id(&format!("axis.{index}")),
        })
        .collect();
    assert_eq!(
        ObjectiveAdmissionError::InvalidProfile("mapping count bound"),
        profile.digest().expect_err("oversized profile must reject")
    );
}

#[test]
fn risk_profile_ordering_is_monotone() {
    let mut profile = profile();
    profile.risk.high_value = FixedQ32::from_raw(0);
    assert_eq!(
        ObjectiveAdmissionError::InvalidProfile("risk ordering"),
        profile
            .digest()
            .expect_err("non-monotone risk profile must reject")
    );
}

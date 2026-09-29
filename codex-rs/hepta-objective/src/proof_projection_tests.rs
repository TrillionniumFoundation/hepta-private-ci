use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::ConstraintClass;
use crate::ObjectiveAbstentionRuleProfileV1;
use crate::ObjectiveActionProfileV1;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveConstraintProfileV1;
use crate::ObjectiveEvidenceProfileV1;
use crate::ObjectiveEvidenceRequirementV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectivePredicateProfileV1;
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
use crate::ObjectiveSourceAuthenticationV1;
use crate::ObjectiveSourceConstraintV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourcePredicateV1;
use crate::ObjectiveSourceTrustV1;
use crate::ObjectiveStructuredIntentV1;
use crate::ValidatedAdmissionProfileV1;
use crate::canonical_objective_intent_digest_v1;
use crate::compile_authoritative_objective_v1;
use crate::encode_authenticated_objective_function_v1;
use crate::encode_proof_bearing_objective_function_v1;

fn id(text: &str) -> StableId {
    StableId::new(text).expect("fixture stable identity")
}

fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

fn axis(name: &str) -> ObjectiveResourceAxisProfileV1 {
    ObjectiveResourceAxisProfileV1 {
        constraint_id: id(&format!("resource.{name}.ceiling")),
        axis: id(&format!("resource.{name}")),
        class: ConstraintClass::Task,
        q32_per_source_unit: FixedQ32::from_raw(1),
        evidence_source: id("resource.profile"),
    }
}

fn profile() -> ObjectiveAdmissionProfileV1 {
    ObjectiveAdmissionProfileV1 {
        profile_id: id("profile.proof-projection"),
        profile_revision: Revision::new(1).expect("revision"),
        expected_input_schema_digest: digest("schema"),
        expected_normalization_profile_digest: digest("normalization"),
        principal_scope_digest: digest("scope"),
        principal_scope: id("principal.alpha"),
        allowed_locales: vec!["en-US".to_owned(), "ja-JP".to_owned()],
        maximum_source_age_micros: 60_000_000,
        maximum_future_skew_micros: 1_000_000,
        deadline_required: true,
        allowed_trusted_source_identities: vec![id("adapter.console")],
        constraints: vec![ObjectiveConstraintProfileV1 {
            source_constraint_id: "latency.ceiling".to_owned(),
            expected_unit: "micros".to_owned(),
            class: ConstraintClass::Task,
            axis: id("latency.micros"),
        }],
        predicates: vec![
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.success".to_owned(),
                expected_unit: "ratio".to_owned(),
                axis: id("task.success.ratio"),
            },
            ObjectivePredicateProfileV1 {
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
            time_micros: axis("time"),
            token_count: axis("tokens"),
            compute_micros: axis("compute"),
            memory_bytes: axis("memory"),
            network_bytes: axis("network"),
            external_effect_count: axis("effects"),
        },
        risk: ObjectiveRiskProfileV1 {
            evidence_source: id("risk.profile"),
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
    let mut value = ObjectiveSourceEnvelopeV1 {
        request_id: "request.projection".to_owned(),
        principal_scope_digest: digest("scope"),
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
                normalization_profile_digest: digest("normalization"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::Principal,
        locale: "en-US".to_owned(),
        observed_at: "2026-09-08T10:00:00Z".to_owned(),
        deadline: Some("2026-09-08T10:05:00Z".to_owned()),
        input_schema_digest: digest("schema"),
    };
    value.intent_digest = canonical_objective_intent_digest_v1(&value).expect("intent");
    value
}

fn context(
    raw: &ObjectiveAdmissionProfileV1,
    source: &ObjectiveSourceEnvelopeV1,
) -> ObjectiveAdmissionContextV1 {
    ObjectiveAdmissionContextV1 {
        revision: Revision::new(7).expect("revision"),
        now_unix_micros: 1_788_861_601_000_000,
        selected_profile_digest: raw.digest().expect("profile"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: source.principal_scope_digest,
            source_digest: source.structured_intent.provenance.source_digest,
        },
    }
}

#[test]
fn proof_projection_matches_independent_authenticated_recompilation() {
    let raw = profile();
    let source = source();
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen");
    let context = context(&raw, &source);
    let result = compile_authoritative_objective_v1(&source, &frozen, &context).expect("compile");
    let expected = encode_authenticated_objective_function_v1(
        result.outcome().compile_result.as_ref().expect("feasible"),
        &source,
        &raw,
        &context,
        &result.outcome().receipt,
    )
    .expect("independent projection");
    assert_eq!(
        encode_proof_bearing_objective_function_v1(&result, &source, &frozen)
            .expect("proof projection"),
        expected,
    );
    assert!(!result.outcome().receipt.authority.grants_any());
}

#[test]
fn proof_projection_rejects_metadata_intent_and_profile_substitution() {
    let raw = profile();
    let original = source();
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen");
    let current = context(&raw, &original);
    let compiled =
        compile_authoritative_objective_v1(&original, &frozen, &current).expect("compile");
    let mut alternatives = Vec::new();
    let mut changed = original.clone();
    changed.request_id = "request.other".to_owned();
    alternatives.push(changed);
    let mut changed = original.clone();
    changed.intent_digest = digest("forged-supplied-intent");
    alternatives.push(changed);
    let mut changed = original.clone();
    changed.locale = "ja-JP".to_owned();
    alternatives.push(changed);
    let mut changed = original.clone();
    changed.observed_at = "2026-09-08T10:00:00.000000Z".to_owned();
    alternatives.push(changed);
    let mut changed = original.clone();
    changed.deadline = Some("2026-09-08T10:06:00Z".to_owned());
    alternatives.push(changed);
    let mut changed = original.clone();
    changed.structured_intent.resources.token_count += 1;
    changed.intent_digest = canonical_objective_intent_digest_v1(&changed).expect("new intent");
    alternatives.push(changed);
    for changed in alternatives {
        assert!(encode_proof_bearing_objective_function_v1(&compiled, &changed, &frozen).is_err());
    }
    let mut revised = raw;
    revised.profile_revision = Revision::new(2).expect("revision");
    let revised = ValidatedAdmissionProfileV1::new(revised).expect("frozen revision");
    assert!(encode_proof_bearing_objective_function_v1(&compiled, &original, &revised).is_err());
}

#[test]
fn frozen_profile_does_not_cache_authentication_or_freshness() {
    let raw = profile();
    let source = source();
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen");
    let current = context(&raw, &source);
    let first = compile_authoritative_objective_v1(&source, &frozen, &current).expect("current");
    let mut changed = current.clone();
    changed.source_authentication = ObjectiveSourceAuthenticationV1::Principal {
        principal_scope_digest: source.principal_scope_digest,
        source_digest: digest("wrong-source"),
    };
    assert!(compile_authoritative_objective_v1(&source, &frozen, &changed).is_err());
    changed = current.clone();
    changed.source_authentication = ObjectiveSourceAuthenticationV1::Principal {
        principal_scope_digest: digest("wrong-principal"),
        source_digest: source.structured_intent.provenance.source_digest,
    };
    assert!(compile_authoritative_objective_v1(&source, &frozen, &changed).is_err());
    changed = current.clone();
    changed.selected_profile_digest = digest("wrong-profile");
    assert!(compile_authoritative_objective_v1(&source, &frozen, &changed).is_err());
    changed = current.clone();
    changed.now_unix_micros += raw.maximum_source_age_micros + 1;
    assert!(compile_authoritative_objective_v1(&source, &frozen, &changed).is_err());
    changed = current;
    changed.now_unix_micros += 1;
    let second =
        compile_authoritative_objective_v1(&source, &frozen, &changed).expect("fresh check");
    assert_ne!(first.proof().proof_digest(), second.proof().proof_digest());
    assert_eq!(
        first.outcome().compile_result,
        second.outcome().compile_result
    );
}

#[test]
fn proof_projection_rejects_conflict_but_preserves_explicit_abstain() {
    let raw = profile();
    let mut source = source();
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen");
    source
        .structured_intent
        .forbidden_action_classes
        .push("read".to_owned());
    source.intent_digest = canonical_objective_intent_digest_v1(&source).expect("intent");
    let current = context(&raw, &source);
    let conflict =
        compile_authoritative_objective_v1(&source, &frozen, &current).expect("conflict");
    assert!(conflict.outcome().compile_result.is_err());
    assert!(encode_proof_bearing_objective_function_v1(&conflict, &source, &frozen).is_err());
    source.structured_intent.legal_action_classes.clear();
    source.intent_digest = canonical_objective_intent_digest_v1(&source).expect("abstain intent");
    let current = context(&raw, &source);
    let abstain = compile_authoritative_objective_v1(&source, &frozen, &current).expect("abstain");
    assert_eq!(
        abstain
            .outcome()
            .compile_result
            .as_ref()
            .expect("valid abstain")
            .disposition,
        crate::CompileDisposition::ExplicitAbstain,
    );
    assert!(encode_proof_bearing_objective_function_v1(&abstain, &source, &frozen).is_ok());
}

#[test]
fn q32_boundaries_preserve_exact_scalar_semantics_through_product_projection() {
    for (comparator, relation, wire_relation) in [
        (
            ObjectiveConstraintComparatorV1::Equal,
            crate::ConstraintRelation::Equal,
            "eq",
        ),
        (
            ObjectiveConstraintComparatorV1::LessThanOrEqual,
            crate::ConstraintRelation::AtMost,
            "lte",
        ),
        (
            ObjectiveConstraintComparatorV1::GreaterThanOrEqual,
            crate::ConstraintRelation::AtLeast,
            "gte",
        ),
    ] {
        for bound in [i64::MIN, -1, 0, 1, i64::MAX] {
            let raw = profile();
            let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen profile");
            let mut input = source();
            input.structured_intent.constraints[0].comparator = comparator;
            input.structured_intent.constraints[0].bound_q32 = bound;
            input.intent_digest = canonical_objective_intent_digest_v1(&input).expect("intent");
            let current = context(&raw, &input);
            let compiled =
                compile_authoritative_objective_v1(&input, &frozen, &current).expect("admission");
            let native = compiled
                .outcome()
                .compile_result
                .as_ref()
                .expect("feasible");
            let constraint = native
                .objective
                .constraints
                .iter()
                .find(|value| value.id.as_str() == "latency.ceiling")
                .expect("constraint retained");
            assert_eq!(
                (constraint.relation, constraint.bound.raw()),
                (relation, bound)
            );
            let projected = encode_proof_bearing_objective_function_v1(&compiled, &input, &frozen)
                .expect("proof projection");
            let reference = encode_authenticated_objective_function_v1(
                native,
                &input,
                &raw,
                &current,
                &compiled.outcome().receipt,
            )
            .expect("independent reference");
            assert_eq!(projected, reference);
            let decoded = crate::decode_objective_function_v1(projected.canonical_bytes())
                .expect("strict canonical protocol validator");
            assert_eq!(decoded.protocol_digest(), projected.protocol_digest());
            let wire: serde_json::Value =
                serde_json::from_slice(projected.canonical_bytes()).expect("wire");
            let constraints = wire["hardConstraints"].as_array().expect("constraints");
            let field = constraints
                .iter()
                .find(|value| value["id"] == "latency.ceiling")
                .expect("wire field");
            assert_eq!(field["boundQ32"].as_i64(), Some(bound));
            assert_eq!(field["relation"].as_str(), Some(wire_relation));
            assert_eq!(
                Digest32::of_bytes(&compiled.proof().canonical_bytes()),
                compiled.proof().proof_digest()
            );
            assert!(!compiled.outcome().receipt.authority.grants_any());
        }
    }
}

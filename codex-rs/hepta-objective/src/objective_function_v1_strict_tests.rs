use super::*;

use codex_hepta_types::Revision;
use serde_json::Value;

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
use crate::ObjectiveSourcePredicateV1;
use crate::ObjectiveStructuredIntentV1;
use crate::admit_and_compile_objective_v1;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("valid stable id")
}

fn test_digest(value: &str) -> Digest32 {
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
        expected_input_schema_digest: test_digest("schema-v1"),
        expected_normalization_profile_digest: test_digest("normalization-v1"),
        principal_scope_digest: test_digest("principal-scope"),
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

fn source() -> ObjectiveSourceEnvelopeV1 {
    let mut source = ObjectiveSourceEnvelopeV1 {
        request_id: "request.001".to_string(),
        principal_scope_digest: test_digest("principal-scope"),
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
            legal_action_classes: vec!["read".to_string()],
            forbidden_action_classes: vec!["network".to_string()],
            confirmation_action_classes: Vec::new(),
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
                source_digest: test_digest("source-bytes"),
                normalization_profile_digest: test_digest("normalization-v1"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::Principal,
        locale: "en-US".to_string(),
        observed_at: "2026-09-08T10:00:00Z".to_string(),
        deadline: Some("2026-09-08T10:05:00Z".to_string()),
        input_schema_digest: test_digest("schema-v1"),
    };
    source.intent_digest = canonical_objective_intent_digest_v1(&source).expect("canonical intent");
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

fn compile_fixture() -> (
    ObjectiveAdmissionProfileV1,
    ObjectiveSourceEnvelopeV1,
    ObjectiveAdmissionContextV1,
    ObjectiveAdmissionReceiptV1,
    ObjectiveCompileReceipt,
) {
    let profile = profile();
    let source = source();
    let context = context(&profile, &source);
    let outcome =
        admit_and_compile_objective_v1(&source, &profile, &context).expect("admit and compile");
    let compiled = outcome.compile_result.expect("compiled");
    (profile, source, context, outcome.receipt, compiled)
}

fn wire() -> ObjectiveFunctionWireV1 {
    ObjectiveFunctionWireV1 {
        objective_id: "request.001".to_string(),
        request_digest: test_digest("request").to_string(),
        principal_scope: PrincipalScopeWireV1 {
            scope_id: "principal.alpha".to_string(),
            scope_digest: test_digest("scope").to_string(),
        },
        success_predicates: vec![PredicateWireV1 {
            id: "task.success".to_string(),
            axis: "axis.success".to_string(),
            relation: "gte".to_string(),
            bound_q32: 1,
            evidence_source: "observer.task".to_string(),
        }],
        terminal_conditions: vec![PredicateWireV1 {
            id: "task.terminal".to_string(),
            axis: "axis.terminal".to_string(),
            relation: "eq".to_string(),
            bound_q32: FixedQ32::ONE.raw(),
            evidence_source: "observer.task".to_string(),
        }],
        hard_constraints: vec![
            ConstraintWireV1 {
                id: "constraint.principal".to_string(),
                class: "principal".to_string(),
                axis: "axis.a".to_string(),
                relation: "eq".to_string(),
                bound_q32: 1,
                evidence_source: "observer.owner".to_string(),
            },
            ConstraintWireV1 {
                id: "constraint.task".to_string(),
                class: "task".to_string(),
                axis: "axis.b".to_string(),
                relation: "lte".to_string(),
                bound_q32: 2,
                evidence_source: "observer.task".to_string(),
            },
        ],
        evidence_requirements: vec![EvidenceRequirementWireV1 {
            id: "evidence.quality".to_string(),
            axis: "axis.evidence".to_string(),
            minimum_confidence_ppm: 900_000,
            evidence_source: "observer.evidence".to_string(),
            terminal: true,
        }],
        allowed_action_classes: vec![
            ActionWireV1 {
                id: "abstain".to_string(),
                confirmation: "not_required".to_string(),
            },
            ActionWireV1 {
                id: "action.read".to_string(),
                confirmation: "not_required".to_string(),
            },
        ],
        forbidden_action_classes: vec!["action.network".to_string()],
        soft_utility_dimensions: vec![SoftDimensionWireV1 {
            dimension: "quality.ratio".to_string(),
            direction: "maximize".to_string(),
            weight_q32: 1_i64 << 31,
        }],
        resource_endowment: ResourceEndowmentWireV1 {
            time_micros: 10_000,
            token_count: 1_000,
            compute_micros: 50_000,
            memory_bytes: 1_048_576,
            network_bytes: 0,
            external_effect_count: 0,
        },
        deadline_unix_ms: Some(1_788_861_900_000),
        revision: 7,
    }
}

fn bytes(value: &ObjectiveFunctionWireV1) -> Vec<u8> {
    serde_json::to_vec(value).expect("canonical json")
}

#[test]
fn valid_wire_round_trips_exactly() {
    let encoded = bytes(&wire());
    let decoded = decode_objective_function_v1(&encoded).expect("strict decode");
    assert_eq!(decoded.canonical_bytes(), encoded);
    assert_eq!(decoded.protocol_digest(), Digest32::of_bytes(&encoded));
}

#[test]
fn decoder_rejects_duplicate_action_identity() {
    let mut value = wire();
    value
        .allowed_action_classes
        .insert(1, value.allowed_action_classes[0].clone());
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());
}

#[test]
fn decoder_rejects_confirmation_gated_abstain() {
    let mut value = wire();
    value.allowed_action_classes[0].confirmation = "required".to_string();
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());
}

#[test]
fn decoder_rejects_negative_and_oversized_soft_weights() {
    for weight in [-1, FixedQ32::ONE.raw() + 1] {
        let mut value = wire();
        value.soft_utility_dimensions[0].weight_q32 = weight;
        assert!(decode_objective_function_v1(&bytes(&value)).is_err());
    }
}

#[test]
fn decoder_rejects_noncanonical_collection_order() {
    let mut value = wire();
    value.allowed_action_classes.swap(0, 1);
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());

    let mut value = wire();
    value.hard_constraints.swap(0, 1);
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());
}

#[test]
fn decoder_rejects_cross_collection_semantic_identity_reuse() {
    let mut value = wire();
    value.evidence_requirements[0].id = value.success_predicates[0].id.clone();
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());
}

#[test]
fn decoder_rejects_forbidden_abstain_and_allowed_overlap() {
    let mut value = wire();
    value.forbidden_action_classes = vec!["abstain".to_string()];
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());

    let mut value = wire();
    value.forbidden_action_classes = vec!["action.read".to_string()];
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());
}

#[test]
fn decoder_rejects_unknown_constraint_class_and_capacity_boundary() {
    let mut value = wire();
    value.hard_constraints[0].class = "unknown".to_string();
    assert!(decode_objective_function_v1(&bytes(&value)).is_err());

    let mut value = wire();
    value.allowed_action_classes = std::iter::once(ActionWireV1 {
        id: "abstain".to_string(),
        confirmation: "not_required".to_string(),
    })
    .chain((0..128).map(|index| ActionWireV1 {
        id: format!("action.{index:03}"),
        confirmation: "not_required".to_string(),
    }))
    .collect();
    assert_eq!(
        decode_objective_function_v1(&bytes(&value)),
        Err(ObjectiveFunctionV1Error::Capacity)
    );
}

#[test]
fn decoder_rejects_noncanonical_json_framing() {
    let canonical = bytes(&wire());
    let value: Value = serde_json::from_slice(&canonical).expect("value");
    let pretty = serde_json::to_vec_pretty(&value).expect("pretty");
    assert_eq!(
        decode_objective_function_v1(&pretty),
        Err(ObjectiveFunctionV1Error::NonCanonicalEncoding)
    );
}

#[test]
fn projection_rejects_source_resource_drift() {
    let (profile, mut source, context, receipt, compiled) = compile_fixture();
    source.structured_intent.resources.token_count += 1;
    assert!(
        encode_authenticated_objective_function_v1(
            &compiled, &source, &profile, &context, &receipt
        )
        .is_err()
    );
}

#[test]
fn projection_rejects_native_lowering_drift() {
    let (profile, source, context, receipt, mut compiled) = compile_fixture();
    compiled.objective.constraints[0].bound = FixedQ32::from_raw(99);
    let native = canonical_native_objective_semantic_bytes_v1(&compiled.objective);
    compiled.objective.semantic_digest = Digest32::of_bytes(&native);
    assert!(
        encode_authenticated_objective_function_v1(
            &compiled, &source, &profile, &context, &receipt
        )
        .is_err()
    );
}

#[test]
fn projection_rejects_source_deadline_drift() {
    let (profile, mut source, _context, receipt, compiled) = compile_fixture();
    source.deadline = Some("2026-09-08T10:05:01Z".to_string());
    assert!(encode_objective_function_v1(&compiled, &source, &profile, &receipt).is_err());
}

#[test]
fn microsecond_deadline_has_conservative_millisecond_projection() {
    let profile = profile();
    let mut source = source();
    source.deadline = Some("2026-09-08T10:05:00.000001Z".to_string());
    let context = context(&profile, &source);
    let outcome =
        admit_and_compile_objective_v1(&source, &profile, &context).expect("microsecond admission");
    let compiled = outcome.compile_result.expect("compiled");
    let artifact = encode_authenticated_objective_function_v1(
        &compiled,
        &source,
        &profile,
        &context,
        &outcome.receipt,
    )
    .expect("conservative projection");
    let value: Value = serde_json::from_slice(artifact.canonical_bytes()).expect("wire");
    assert_eq!(
        value["deadlineUnixMs"].as_u64(),
        outcome
            .receipt
            .deadline_unix_micros
            .map(|value| value / 1_000)
    );
}

#[test]
fn authenticated_projection_rejects_each_source_field_mutation() {
    type Mutation = fn(&mut ObjectiveSourceEnvelopeV1);
    let cases: &[(&str, Mutation)] = &[
        ("request", |s| s.request_id.push('x')),
        ("scope", |s| {
            s.principal_scope_digest = test_digest("changed scope")
        }),
        ("schema", |s| {
            s.input_schema_digest = test_digest("changed schema")
        }),
        ("locale", |s| s.locale = "en-GB".to_string()),
        ("trust", |s| {
            s.source_trust_class = ObjectiveSourceTrustV1::UntrustedEvidence
        }),
        ("observation", |s| {
            s.observed_at = "2026-09-08T10:00:01Z".to_string()
        }),
        ("deadline", |s| {
            s.deadline = Some("2026-09-08T10:05:00.000001Z".to_string())
        }),
        ("success.id", |s| {
            s.structured_intent.success_predicates[0]
                .predicate_id
                .push('x')
        }),
        ("success.unit", |s| {
            s.structured_intent.success_predicates[0].unit.push('x')
        }),
        ("success.comparator", |s| {
            s.structured_intent.success_predicates[0].comparator =
                ObjectivePredicateComparatorV1::Equal
        }),
        ("success.bound", |s| {
            s.structured_intent.success_predicates[0].bound_q32 += 1
        }),
        ("success.evidence", |s| {
            s.structured_intent.success_predicates[0]
                .evidence_source_id
                .push('x')
        }),
        ("success.terminal", |s| {
            s.structured_intent.success_predicates[0].terminal = true
        }),
        ("terminal.id", |s| {
            s.structured_intent.terminal_conditions[0]
                .predicate_id
                .push('x')
        }),
        ("terminal.unit", |s| {
            s.structured_intent.terminal_conditions[0].unit.push('x')
        }),
        ("terminal.comparator", |s| {
            s.structured_intent.terminal_conditions[0].comparator =
                ObjectivePredicateComparatorV1::GreaterThanOrEqual
        }),
        ("terminal.bound", |s| {
            s.structured_intent.terminal_conditions[0].bound_q32 -= 1
        }),
        ("terminal.evidence", |s| {
            s.structured_intent.terminal_conditions[0]
                .evidence_source_id
                .push('x')
        }),
        ("terminal.flag", |s| {
            s.structured_intent.terminal_conditions[0].terminal = false
        }),
        ("constraint.id", |s| {
            s.structured_intent.constraints[0].constraint_id.push('x')
        }),
        ("constraint.unit", |s| {
            s.structured_intent.constraints[0].unit.push('x')
        }),
        ("constraint.comparator", |s| {
            s.structured_intent.constraints[0].comparator = ObjectiveConstraintComparatorV1::Equal
        }),
        ("constraint.bound", |s| {
            s.structured_intent.constraints[0].bound_q32 += 1
        }),
        ("constraint.evidence", |s| {
            s.structured_intent.constraints[0]
                .evidence_source_id
                .push('x')
        }),
        ("constraint.terminal", |s| {
            s.structured_intent.constraints[0].terminal = true
        }),
        ("legal actions", |s| {
            s.structured_intent.legal_action_classes.clear()
        }),
        ("forbidden actions", |s| {
            s.structured_intent.forbidden_action_classes.clear()
        }),
        ("confirmation actions", |s| {
            s.structured_intent
                .confirmation_action_classes
                .push("read".to_string())
        }),
        ("soft.id", |s| {
            s.structured_intent.soft_dimensions[0]
                .dimension_id
                .push('x')
        }),
        ("soft.unit", |s| {
            s.structured_intent.soft_dimensions[0].unit.push('x')
        }),
        ("soft.direction", |s| {
            s.structured_intent.soft_dimensions[0].direction = ObjectiveSoftDirectionV1::Minimize
        }),
        ("soft.minimum", |s| {
            s.structured_intent.soft_dimensions[0].minimum_weight_q32 += 1
        }),
        ("soft.maximum", |s| {
            s.structured_intent.soft_dimensions[0].maximum_weight_q32 -= 1
        }),
        ("evidence.id", |s| {
            s.structured_intent.evidence_requirements[0]
                .requirement_id
                .push('x')
        }),
        ("evidence.source", |s| {
            s.structured_intent.evidence_requirements[0]
                .evidence_source_id
                .push('x')
        }),
        ("evidence.confidence", |s| {
            s.structured_intent.evidence_requirements[0].minimum_confidence_ppm -= 1
        }),
        ("evidence.terminal", |s| {
            s.structured_intent.evidence_requirements[0].terminal = false
        }),
        ("resource.time", |s| {
            s.structured_intent.resources.time_micros += 1
        }),
        ("resource.tokens", |s| {
            s.structured_intent.resources.token_count += 1
        }),
        ("resource.compute", |s| {
            s.structured_intent.resources.compute_micros += 1
        }),
        ("resource.memory", |s| {
            s.structured_intent.resources.memory_bytes += 1
        }),
        ("resource.network", |s| {
            s.structured_intent.resources.network_bytes += 1
        }),
        ("resource.effects", |s| {
            s.structured_intent.resources.external_effect_count += 1
        }),
        ("risk.class", |s| {
            s.structured_intent.risk.risk_class = ObjectiveRiskClassV1::High
        }),
        ("risk.abstention", |s| {
            s.structured_intent.risk.abstention_rule.push('x')
        }),
        ("risk.rollback", |s| {
            s.structured_intent.risk.rollback_class = ObjectiveRollbackClassV1::Irreversible
        }),
        ("risk.compensation", |s| {
            s.structured_intent.risk.compensation_required = true
        }),
        ("source digest", |s| {
            s.structured_intent.provenance.source_digest = test_digest("changed source")
        }),
        ("normalization", |s| {
            s.structured_intent.provenance.normalization_profile_digest =
                test_digest("changed normalization")
        }),
    ];
    let (profile, source, context, receipt, compiled) = compile_fixture();
    for (name, mutate) in cases {
        let mut changed = source.clone();
        mutate(&mut changed);
        assert_ne!(changed, source, "mutation {name} must change the fixture");
        // Even a newly recomputed request digest cannot reuse the old receipt
        // and native result. Exercise the semantic relationship, not only a
        // stale digest-field mismatch.
        if let Ok(digest) = canonical_objective_intent_digest_v1(&changed) {
            changed.intent_digest = digest;
        }
        assert!(
            encode_authenticated_objective_function_v1(
                &compiled, &changed, &profile, &context, &receipt,
            )
            .is_err(),
            "accepted source mutation {name}"
        );
    }
}

#[test]
fn authenticated_projection_preserves_equivalent_source_ordering() {
    let mut profile = profile();
    profile.actions.push(ObjectiveActionProfileV1 {
        source_action_class: "inspect".to_string(),
        action_id: id("action.inspect"),
    });
    profile.constraints.push(ObjectiveConstraintProfileV1 {
        source_constraint_id: "latency.second.ceiling".to_string(),
        expected_unit: "micros".to_string(),
        class: ConstraintClass::Task,
        axis: id("latency.second.micros"),
    });
    let mut source = source();
    source
        .structured_intent
        .legal_action_classes
        .push("inspect".to_string());
    let mut second = source.structured_intent.constraints[0].clone();
    second.constraint_id = "latency.second.ceiling".to_string();
    source.structured_intent.constraints.push(second);
    source.intent_digest = canonical_objective_intent_digest_v1(&source).expect("intent");
    let context = context(&profile, &source);
    let outcome = admit_and_compile_objective_v1(&source, &profile, &context).expect("admitted");
    let compiled = outcome.compile_result.expect("compiled");
    let receipt = outcome.receipt;
    let expected = encode_authenticated_objective_function_v1(
        &compiled, &source, &profile, &context, &receipt,
    )
    .expect("original artifact");
    let original = source.clone();
    source.structured_intent.legal_action_classes.reverse();
    source.structured_intent.constraints.reverse();
    assert_ne!(
        source, original,
        "permutation must change the input ordering"
    );
    let actual = encode_authenticated_objective_function_v1(
        &compiled, &source, &profile, &context, &receipt,
    )
    .expect("equivalent reordered source");
    assert_eq!(actual, expected);
}

#[test]
fn decoder_accepts_exact_action_and_soft_weight_boundaries() {
    for weight in [0, FixedQ32::ONE.raw()] {
        let mut value = wire();
        value.soft_utility_dimensions[0].weight_q32 = weight;
        value.allowed_action_classes = std::iter::once(ActionWireV1 {
            id: "abstain".to_string(),
            confirmation: "not_required".to_string(),
        })
        .chain((0..127).map(|index| ActionWireV1 {
            id: format!("action.{index:03}"),
            confirmation: "not_required".to_string(),
        }))
        .collect();
        let encoded = bytes(&value);
        let decoded = decode_objective_function_v1(&encoded).expect("inclusive boundary");
        assert_eq!(decoded.canonical_bytes(), encoded);
    }
}

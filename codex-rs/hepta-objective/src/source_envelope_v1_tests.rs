use pretty_assertions::assert_eq;

use super::*;
use crate::ObjectiveStructureError;

fn envelope() -> ObjectiveSourceEnvelopeV1 {
    let predicate = ObjectiveSourcePredicateV1 {
        predicate_id: "supported-report".into(),
        unit: "supported claims / report".into(),
        comparator: ObjectivePredicateComparatorV1::GreaterThanOrEqual,
        bound_q32: 1_i64 << 32,
        evidence_source_id: "fixture observer / citations".into(),
        terminal: true,
    };
    ObjectiveSourceEnvelopeV1 {
        request_id: "read-request".into(),
        principal_scope_digest: Digest32::of_bytes(b"fixture scope"),
        intent_digest: Digest32::of_bytes(b"fixture intent"),
        structured_intent: ObjectiveStructuredIntentV1 {
            success_predicates: vec![predicate.clone()],
            terminal_conditions: vec![predicate],
            legal_action_classes: vec!["读取 / report".into()],
            forbidden_action_classes: vec!["external network".into()],
            confirmation_action_classes: vec!["读取 / report".into()],
            constraints: vec![ObjectiveSourceConstraintV1 {
                constraint_id: "bounded-effects".into(),
                unit: "external effects".into(),
                comparator: ObjectiveConstraintComparatorV1::Equal,
                bound_q32: 0,
                evidence_source_id: "fixture observer / effects".into(),
                terminal: false,
            }],
            soft_dimensions: vec![ObjectiveSoftDimensionV1 {
                dimension_id: "latency / report".into(),
                unit: "μs".into(),
                direction: ObjectiveSoftDirectionV1::Minimize,
                minimum_weight_q32: 0,
                maximum_weight_q32: 1_i64 << 32,
            }],
            evidence_requirements: vec![ObjectiveEvidenceRequirementV1 {
                requirement_id: "independent-observation".into(),
                evidence_source_id: "fixture observer / citations".into(),
                minimum_confidence_ppm: 900_000,
                terminal: true,
            }],
            resources: ObjectiveResourcesV1 {
                time_micros: 1_000_000,
                token_count: 999,
                compute_micros: 500_000,
                memory_bytes: 4096,
                network_bytes: 0,
                external_effect_count: 0,
            },
            risk: ObjectiveRiskV1 {
                risk_class: ObjectiveRiskClassV1::Low,
                abstention_rule: "Abstain when independent evidence is unavailable.".into(),
                rollback_class: ObjectiveRollbackClassV1::Reversible,
                compensation_required: false,
            },
            provenance: ObjectiveProvenanceV1 {
                source_digest: Digest32::of_bytes(b"fixture source"),
                normalization_profile_digest: Digest32::of_bytes(b"fixture profile"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::UntrustedEvidence,
        locale: "zh-CN".into(),
        observed_at: "2026-09-06T00:00:00Z".into(),
        deadline: Some("2026-09-06T00:00:01Z".into()),
        input_schema_digest: Digest32::of_bytes(b"fixture schema"),
    }
}

#[test]
fn structural_validation_retains_semantics_that_native_compilation_cannot_represent() {
    let mut source = envelope();
    source.source_trust_class = ObjectiveSourceTrustV1::TrustedSystem;
    let intent = &mut source.structured_intent;
    intent.success_predicates[0].comparator = ObjectivePredicateComparatorV1::NotEqual;
    intent.success_predicates[0].bound_q32 = i64::MIN;
    intent.terminal_conditions[0].comparator = ObjectivePredicateComparatorV1::LessThan;
    intent.terminal_conditions[0].bound_q32 = i64::MAX;
    intent.constraints[0].comparator = ObjectiveConstraintComparatorV1::NotInSet;
    intent.soft_dimensions[0].minimum_weight_q32 = i64::MIN;
    intent.soft_dimensions[0].maximum_weight_q32 = i64::MAX;
    intent.evidence_requirements[0].minimum_confidence_ppm = u32::MAX;
    intent.resources = ObjectiveResourcesV1 {
        time_micros: u64::MAX,
        token_count: u64::MAX,
        compute_micros: u64::MAX,
        memory_bytes: u64::MAX,
        network_bytes: u64::MAX,
        external_effect_count: u32::MAX,
    };
    intent.risk.risk_class = ObjectiveRiskClassV1::Critical;
    intent.risk.rollback_class = ObjectiveRollbackClassV1::Compensatable;
    intent.risk.compensation_required = true;
    // A raw UTF-8 evidence ID can exceed StableId's 128-byte ceiling.
    intent.constraints[0].evidence_source_id = "é /".repeat(40);
    let expected = source.clone();
    assert_eq!(source.validate_structure(), Ok(()));
    assert_eq!(source, expected);
}

#[test]
fn text_limits_count_utf8_bytes_for_every_source_field() {
    type TextField = fn(&mut ObjectiveSourceEnvelopeV1) -> &mut String;
    let cases: &[(TextField, usize)] = &[
        (|s| &mut s.request_id, 128),
        (|s| &mut s.locale, 32),
        (|s| &mut s.observed_at, 64),
        (|s| s.deadline.as_mut().unwrap(), 64),
        (
            |s| &mut s.structured_intent.success_predicates[0].predicate_id,
            128,
        ),
        (|s| &mut s.structured_intent.success_predicates[0].unit, 64),
        (
            |s| &mut s.structured_intent.success_predicates[0].evidence_source_id,
            256,
        ),
        (
            |s| &mut s.structured_intent.terminal_conditions[0].predicate_id,
            128,
        ),
        (|s| &mut s.structured_intent.terminal_conditions[0].unit, 64),
        (
            |s| &mut s.structured_intent.terminal_conditions[0].evidence_source_id,
            256,
        ),
        (|s| &mut s.structured_intent.legal_action_classes[0], 128),
        (
            |s| &mut s.structured_intent.forbidden_action_classes[0],
            128,
        ),
        (
            |s| &mut s.structured_intent.confirmation_action_classes[0],
            128,
        ),
        (
            |s| &mut s.structured_intent.constraints[0].constraint_id,
            128,
        ),
        (|s| &mut s.structured_intent.constraints[0].unit, 64),
        (
            |s| &mut s.structured_intent.constraints[0].evidence_source_id,
            256,
        ),
        (
            |s| &mut s.structured_intent.soft_dimensions[0].dimension_id,
            128,
        ),
        (|s| &mut s.structured_intent.soft_dimensions[0].unit, 64),
        (
            |s| &mut s.structured_intent.evidence_requirements[0].requirement_id,
            128,
        ),
        (
            |s| &mut s.structured_intent.evidence_requirements[0].evidence_source_id,
            256,
        ),
        (|s| &mut s.structured_intent.risk.abstention_rule, 512),
    ];
    for &(field, maximum) in cases {
        let mut source = envelope();
        *field(&mut source) = "é".repeat(maximum / 2);
        assert_eq!(source.validate_structure(), Ok(()));
        field(&mut source).push('x');
        let error = source
            .validate_structure()
            .expect_err("oversized UTF-8 field");
        assert!(matches!(error, ObjectiveStructureError::TextBytes {
            actual, maximum: limit, ..
        } if actual == maximum + 1 && limit == maximum));
    }
}

#[test]
fn every_collection_enforces_counts_and_duplicate_keys_before_semantic_compilation() {
    type Resize = fn(&mut ObjectiveStructuredIntentV1, usize);
    let cases: &[(&str, usize, usize, Resize)] = &[
        ("successPredicates", 1, 128, |s, n| {
            s.success_predicates
                .resize(n, s.success_predicates[0].clone())
        }),
        ("terminalConditions", 1, 128, |s, n| {
            s.terminal_conditions
                .resize(n, s.terminal_conditions[0].clone())
        }),
        ("legalActionClasses", 1, 128, |s, n| {
            s.legal_action_classes
                .resize(n, s.legal_action_classes[0].clone())
        }),
        ("forbiddenActionClasses", 0, 128, |s, n| {
            s.forbidden_action_classes
                .resize(n, s.forbidden_action_classes[0].clone())
        }),
        ("confirmationActionClasses", 0, 128, |s, n| {
            s.confirmation_action_classes
                .resize(n, s.confirmation_action_classes[0].clone())
        }),
        ("constraints", 1, 256, |s, n| {
            s.constraints.resize(n, s.constraints[0].clone())
        }),
        ("softDimensions", 0, 64, |s, n| {
            s.soft_dimensions.resize(n, s.soft_dimensions[0].clone())
        }),
        ("evidenceRequirements", 1, 128, |s, n| {
            s.evidence_requirements
                .resize(n, s.evidence_requirements[0].clone())
        }),
    ];
    for &(field, minimum, maximum, resize) in cases {
        let mut source = envelope();
        resize(&mut source.structured_intent, maximum + 1);
        assert_eq!(
            source.validate_structure(),
            Err(ObjectiveStructureError::CollectionCount {
                field,
                actual: maximum + 1,
                minimum,
                maximum,
            })
        );
        let mut source = envelope();
        resize(&mut source.structured_intent, 0);
        let expected = if minimum == 0 {
            Ok(())
        } else {
            Err(ObjectiveStructureError::CollectionCount {
                field,
                actual: 0,
                minimum,
                maximum,
            })
        };
        assert_eq!(source.validate_structure(), expected);
        let mut source = envelope();
        resize(&mut source.structured_intent, 2);
        assert_eq!(
            source.validate_structure(),
            Err(ObjectiveStructureError::DuplicateSemanticKey { field, index: 1 })
        );
    }
}

#[test]
fn duplicate_semantic_ids_reject_even_when_other_fields_differ_without_echoing_source() {
    let mut source = envelope();
    let mut duplicate = source.structured_intent.constraints[0].clone();
    duplicate.bound_q32 = 10;
    duplicate.evidence_source_id = "private source contents".into();
    source.structured_intent.constraints.push(duplicate);
    let error = source
        .validate_structure()
        .expect_err("duplicate constraint ID");
    assert_eq!(
        error,
        ObjectiveStructureError::DuplicateSemanticKey {
            field: "constraints",
            index: 1
        }
    );
    assert_eq!(
        error.to_string(),
        "constraints repeats a semantic key at index 1"
    );
}

#[test]
fn validation_preserves_order_cross_array_references_and_conflicts_for_the_semantic_owner() {
    let mut source = envelope();
    let mut second = source.structured_intent.constraints[0].clone();
    second.constraint_id = "a-distinct-constraint".into();
    source.structured_intent.constraints.push(second);
    source.structured_intent.forbidden_action_classes =
        source.structured_intent.legal_action_classes.clone();
    source.deadline = None;
    let expected = source.clone();
    assert_eq!(source.validate_structure(), Ok(()));
    assert_eq!(source, expected);
    source.structured_intent.constraints.reverse();
    assert_eq!(source.validate_structure(), Ok(()));
}

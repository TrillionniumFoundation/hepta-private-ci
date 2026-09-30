use std::error::Error;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::*;
use crate::source_envelope_v1::*;

const SOURCE: &str = r#"{
 "requestId":"read-request",
 "principalScopeDigest":"0000000000000000000000000000000000000000000000000000000000000000",
 "intentDigest":"1111111111111111111111111111111111111111111111111111111111111111",
 "structuredIntent":{
  "successPredicates":[{"predicateId":"z","unit":"e\u0301","comparator":"ne","boundQ32":-9223372036854775808,"evidenceSourceId":"observer / citations","terminal":false}],
  "terminalConditions":[{"predicateId":"z","unit":"count","comparator":"lt","boundQ32":9223372036854775807,"evidenceSourceId":"observer / terminal","terminal":true}],
  "legalActionClasses":["读取","abstain"],"forbiddenActionClasses":["读取"],"confirmationActionClasses":["读取"],
  "constraints":[{"constraintId":"effects","unit":"count","comparator":"not_in","boundQ32":0,"evidenceSourceId":"observer / effects","terminal":true}],
  "softDimensions":[{"dimensionId":"latency / report","unit":"μs","direction":"minimize","minimumWeightQ32":-9223372036854775808,"maximumWeightQ32":9223372036854775807}],
  "evidenceRequirements":[{"requirementId":"independent","evidenceSourceId":"observer / confidence","minimumConfidencePpm":4294967295,"terminal":true}],
  "resources":{"timeMicros":18446744073709551615,"tokenCount":2,"computeMicros":3,"memoryBytes":4,"networkBytes":5,"externalEffectCount":4294967295},
  "risk":{"riskClass":"critical","abstentionRule":"ask independently","rollbackClass":"compensatable","compensationRequired":true},
  "provenance":{"sourceDigest":"2222222222222222222222222222222222222222222222222222222222222222","normalizationProfileDigest":"3333333333333333333333333333333333333333333333333333333333333333"}
 },
 "sourceTrustClass":"trusted_system","locale":"zh-CN","observedAt":"unverified time",
 "deadline":"unverified deadline",
 "inputSchemaDigest":"4444444444444444444444444444444444444444444444444444444444444444"
}"#;

#[test]
fn decodes_all_fields_without_loss_or_semantic_admission() {
    let expected = ObjectiveSourceEnvelopeV1 {
        request_id: "read-request".into(),
        principal_scope_digest: Digest32::ZERO,
        intent_digest: Digest32::from_array([0x11; 32]),
        structured_intent: ObjectiveStructuredIntentV1 {
            success_predicates: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "z".into(),
                unit: "e\u{0301}".into(),
                comparator: ObjectivePredicateComparatorV1::NotEqual,
                bound_q32: i64::MIN,
                evidence_source_id: "observer / citations".into(),
                terminal: false,
            }],
            terminal_conditions: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "z".into(),
                unit: "count".into(),
                comparator: ObjectivePredicateComparatorV1::LessThan,
                bound_q32: i64::MAX,
                evidence_source_id: "observer / terminal".into(),
                terminal: true,
            }],
            legal_action_classes: vec!["读取".into(), "abstain".into()],
            forbidden_action_classes: vec!["读取".into()],
            confirmation_action_classes: vec!["读取".into()],
            constraints: vec![ObjectiveSourceConstraintV1 {
                constraint_id: "effects".into(),
                unit: "count".into(),
                comparator: ObjectiveConstraintComparatorV1::NotInSet,
                bound_q32: 0,
                evidence_source_id: "observer / effects".into(),
                terminal: true,
            }],
            soft_dimensions: vec![ObjectiveSoftDimensionV1 {
                dimension_id: "latency / report".into(),
                unit: "μs".into(),
                direction: ObjectiveSoftDirectionV1::Minimize,
                minimum_weight_q32: i64::MIN,
                maximum_weight_q32: i64::MAX,
            }],
            evidence_requirements: vec![ObjectiveEvidenceRequirementV1 {
                requirement_id: "independent".into(),
                evidence_source_id: "observer / confidence".into(),
                minimum_confidence_ppm: u32::MAX,
                terminal: true,
            }],
            resources: ObjectiveResourcesV1 {
                time_micros: u64::MAX,
                token_count: 2,
                compute_micros: 3,
                memory_bytes: 4,
                network_bytes: 5,
                external_effect_count: u32::MAX,
            },
            risk: ObjectiveRiskV1 {
                risk_class: ObjectiveRiskClassV1::Critical,
                abstention_rule: "ask independently".into(),
                rollback_class: ObjectiveRollbackClassV1::Compensatable,
                compensation_required: true,
            },
            provenance: ObjectiveProvenanceV1 {
                source_digest: Digest32::from_array([0x22; 32]),
                normalization_profile_digest: Digest32::from_array([0x33; 32]),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::TrustedSystem,
        locale: "zh-CN".into(),
        observed_at: "unverified time".into(),
        deadline: Some("unverified deadline".into()),
        input_schema_digest: Digest32::from_array([0x44; 32]),
    };
    assert_eq!(
        decode_source_envelope_json_v1(SOURCE.as_bytes()),
        Ok(expected.clone())
    );
    let parsed: Value = serde_json::from_str(SOURCE).unwrap();
    let reversed_fields = [
        "inputSchemaDigest",
        "deadline",
        "observedAt",
        "locale",
        "sourceTrustClass",
        "structuredIntent",
        "intentDigest",
        "principalScopeDigest",
        "requestId",
    ]
    .map(|key| format!("\"{key}\":{}", parsed[key]))
    .join(",");
    assert_eq!(
        decode_source_envelope_json_v1(format!("{{{reversed_fields}}}").as_bytes()),
        Ok(expected)
    );
}

const OBJECTS: &[&str] = &[
    "",
    "/structuredIntent",
    "/structuredIntent/successPredicates/0",
    "/structuredIntent/terminalConditions/0",
    "/structuredIntent/constraints/0",
    "/structuredIntent/softDimensions/0",
    "/structuredIntent/evidenceRequirements/0",
    "/structuredIntent/resources",
    "/structuredIntent/risk",
    "/structuredIntent/provenance",
];

#[test]
fn every_object_rejects_unknown_missing_null_and_duplicate_fields() {
    let original: Value = serde_json::from_str(SOURCE).unwrap();
    for pointer in OBJECTS {
        let fields = original.pointer(pointer).unwrap().as_object().unwrap();
        let mut unknown = original.clone();
        unknown
            .pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("private-sentinel".into(), json!(true));
        reject(&serde_json::to_vec(&unknown).unwrap());
        for key in fields.keys() {
            let mut missing = original.clone();
            missing
                .pointer_mut(pointer)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .remove(key);
            if pointer.is_empty() && key == "deadline" {
                assert_eq!(
                    decode_source_envelope_json_v1(&serde_json::to_vec(&missing).unwrap())
                        .unwrap()
                        .deadline,
                    None
                );
            } else {
                reject(&serde_json::to_vec(&missing).unwrap());
            }
            let mut null = original.clone();
            null.pointer_mut(pointer)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .insert(key.clone(), Value::Null);
            reject(&serde_json::to_vec(&null).unwrap());
        }
    }
    // Raw strings preserve duplicate keys, including escaped aliases. A Value
    // construction here would have discarded the evidence before decoding.
    for (key, alias, value) in [
        ("requestId", "request\\u0049d", r#""read-request""#),
        ("boundQ32", "bound\\u005132", "-9223372036854775808"),
        ("deadline", "deadline", r#""unverified deadline""#),
        (
            "sourceTrustClass",
            "sourceTrustClass",
            r#""trusted_system""#,
        ),
        ("predicateId", "predicateId", r#""z""#),
        ("constraintId", "constraintId", r#""effects""#),
        ("dimensionId", "dimensionId", r#""latency / report""#),
        ("requirementId", "requirementId", r#""independent""#),
        ("timeMicros", "timeMicros", "18446744073709551615"),
        ("riskClass", "riskClass", r#""critical""#),
        (
            "sourceDigest",
            "sourceDigest",
            r#""2222222222222222222222222222222222222222222222222222222222222222""#,
        ),
    ] {
        let needle = format!("\"{key}\":");
        let duplicate = SOURCE.replacen(&needle, &format!("\"{alias}\":{value},{needle}"), 1);
        reject(duplicate.as_bytes());
    }
}

#[test]
fn rejects_positional_structs_and_enum_objects_with_otherwise_correct_contents() {
    let original: Value = serde_json::from_str(SOURCE).unwrap();
    for (pointer, keys) in [
        (
            "",
            vec![
                "requestId",
                "principalScopeDigest",
                "intentDigest",
                "structuredIntent",
                "sourceTrustClass",
                "locale",
                "observedAt",
                "deadline",
                "inputSchemaDigest",
            ],
        ),
        (
            "/structuredIntent/resources",
            vec![
                "timeMicros",
                "tokenCount",
                "computeMicros",
                "memoryBytes",
                "networkBytes",
                "externalEffectCount",
            ],
        ),
        (
            "/structuredIntent/successPredicates/0",
            vec![
                "predicateId",
                "unit",
                "comparator",
                "boundQ32",
                "evidenceSourceId",
                "terminal",
            ],
        ),
    ] {
        let object = original.pointer(pointer).unwrap();
        let values = keys.into_iter().map(|key| object[key].clone()).collect();
        let mut source = original.clone();
        *source.pointer_mut(pointer).unwrap() = Value::Array(values);
        reject(&serde_json::to_vec(&source).unwrap());
    }
    for pointer in [
        "/sourceTrustClass",
        "/structuredIntent/successPredicates/0/comparator",
        "/structuredIntent/constraints/0/comparator",
        "/structuredIntent/softDimensions/0/direction",
        "/structuredIntent/risk/riskClass",
        "/structuredIntent/risk/rollbackClass",
    ] {
        let spelling = original.pointer(pointer).unwrap().as_str().unwrap();
        for invalid in [
            json!({(spelling): null}),
            json!(1),
            json!("private-sentinel"),
        ] {
            let mut source = original.clone();
            *source.pointer_mut(pointer).unwrap() = invalid;
            reject(&serde_json::to_vec(&source).unwrap());
        }
    }
}

#[test]
fn numeric_and_digest_grammar_remains_exact() {
    for (valid, invalid) in [
        ("-9223372036854775808", "-9223372036854775809"),
        ("9223372036854775807", "9223372036854775808"),
        ("18446744073709551615", "18446744073709551616"),
        ("18446744073709551615", "-1"),
        ("4294967295", "4294967296"),
        ("4294967295", "-1"),
        ("-9223372036854775808", "1.0"),
        ("-9223372036854775808", "1e0"),
        ("18446744073709551615", "true"),
        ("18446744073709551615", "\"1\""),
    ] {
        reject(SOURCE.replacen(valid, invalid, 1).as_bytes());
    }
    let original: Value = serde_json::from_str(SOURCE).unwrap();
    for pointer in [
        "/principalScopeDigest",
        "/intentDigest",
        "/inputSchemaDigest",
        "/structuredIntent/provenance/sourceDigest",
        "/structuredIntent/provenance/normalizationProfileDigest",
    ] {
        for invalid in [
            "A".repeat(64),
            "g".repeat(64),
            "0".repeat(63),
            "0".repeat(65),
        ] {
            let mut source = original.clone();
            *source.pointer_mut(pointer).unwrap() = json!(invalid);
            reject(&serde_json::to_vec(&source).unwrap());
        }
    }
}

#[test]
fn retains_structural_count_text_and_semantic_key_checks_after_decoding() {
    let original: Value = serde_json::from_str(SOURCE).unwrap();
    for (pointer, invalid) in [
        ("/locale", json!("é".repeat(17))),
        ("/structuredIntent/legalActionClasses", json!([])),
        (
            "/structuredIntent/legalActionClasses",
            json!(vec!["read"; 129]),
        ),
        (
            "/structuredIntent/legalActionClasses",
            json!(["read", "read"]),
        ),
    ] {
        let mut source = original.clone();
        *source.pointer_mut(pointer).unwrap() = invalid;
        assert!(matches!(
            decode_source_envelope_json_v1(&serde_json::to_vec(&source).unwrap()),
            Err(ObjectiveSourceJsonError::Structure(_))
        ));
    }
    let mut source = original;
    let predicates = source["structuredIntent"]["successPredicates"]
        .as_array_mut()
        .unwrap();
    let mut duplicate = predicates[0].clone();
    duplicate["terminal"] = json!(true);
    predicates.push(duplicate);
    assert!(matches!(
        decode_source_envelope_json_v1(&serde_json::to_vec(&source).unwrap()),
        Err(ObjectiveSourceJsonError::Structure(
            ObjectiveStructureError::DuplicateSemanticKey { .. }
        ))
    ));
}

#[test]
fn raw_ingress_budget_and_json_framing_fail_without_source_leakage() {
    let mut at_limit = SOURCE.as_bytes().to_vec();
    at_limit.resize(MAX_OBJECTIVE_SOURCE_JSON_INPUT_BYTES, b' ');
    assert!(decode_source_envelope_json_v1(&at_limit).is_ok());
    at_limit.push(b' ');
    assert_eq!(
        decode_source_envelope_json_v1(&at_limit),
        Err(ObjectiveSourceJsonError::InputTooLarge {
            actual: MAX_OBJECTIVE_SOURCE_JSON_INPUT_BYTES + 1,
            maximum: MAX_OBJECTIVE_SOURCE_JSON_INPUT_BYTES,
        })
    );
    for invalid in [
        b"".as_slice(),
        b"\xff",
        b"null",
        b"[",
        &SOURCE.as_bytes()[..SOURCE.len() - 1],
    ] {
        reject(invalid);
    }
    reject(format!("{SOURCE} {{}}").as_bytes());
    reject(format!("{}0{}", "[".repeat(64), "]".repeat(64)).as_bytes());
}

fn reject(source: &[u8]) {
    let error = decode_source_envelope_json_v1(source).expect_err("invalid source must reject");
    assert!(!error.to_string().contains("private-sentinel"));
    assert!(!format!("{error:?}").contains("private-sentinel"));
    assert!(error.source().is_none());
}

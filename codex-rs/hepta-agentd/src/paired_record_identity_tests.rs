//! Synthetic, zero-human artifacts from the existing create-only capture helper.
//! Constructing the private material type here is test scaffolding, not Root proof.
use super::*;
use crate::PairedTurnRequest;
use pretty_assertions::assert_eq;
use serde_json::json;

const FAILURE: &[u8] = include_bytes!("../tests/fixtures/paired-record-failure-v1.json");
const CORRECTION: &[u8] = include_bytes!("../tests/fixtures/paired-record-correction-v1.json");
const VECTORS: &[u8] = include_bytes!("../tests/fixtures/paired-record-canonical-v1.json");

#[path = "paired_opaque_record_tests.rs"]
mod opaque_tests;

fn pins() -> PairedRecordPinsV1 {
    PairedRecordPinsV1 {
        failure_record_digest: "a7e5d55b674d728752a302f1f40b2eb7af02f284f50ff641123cc049368b48c2"
            .parse()
            .unwrap(),
        correction_record_digest:
            "77506dc0d93a2032429b1d3b8797f3b5cc4d42aab26ee2be796f8eb4b6874f48"
                .parse()
                .unwrap(),
    }
}

fn request(failure: &[u8], correction: &[u8]) -> PairedPreparationRequest {
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(failure),
        failure_bytes: failure.len() as u64,
        correction_sha256: Digest32::of_bytes(correction),
        correction_bytes: correction.len() as u64,
    };
    PairedPreparationRequest {
        original: PairedTurnRequest {
            turn_id: "fixture-turn".into(),
            delivery_id: Digest32::of_bytes(b"fixture-delivery"),
            study: Digest32::of_bytes(b"fixture-study"),
            expected_principal: "fixture.principal".into(),
            usage: PairedLearningDataUse::TrainOnFailureAndCorrection {
                failure: manifest.failure_sha256,
                correction: manifest.correction_sha256,
            },
        },
        operation: Digest32::of_bytes(b"fixture-operation"),
        materials: manifest.commitment().unwrap(),
    }
}

pub(crate) fn fresh(failure: &[u8], correction: &[u8]) -> PairedTrainingReadResult {
    PairedTrainingReadResult::FreshRead(PairedTrainingMaterials {
        failure: failure.to_vec(),
        correction: correction.to_vec(),
    })
}

fn assert_refused(result: Result<PairedRecordIdentityV1, AgentdError>, reason: &str) {
    match result {
        Ok(_) => panic!("unexpected identity admission"),
        Err(error) => assert!(error.to_string().contains(reason), "{error}"),
    }
}

fn canonical_digest(raw: &[u8]) -> Digest32 {
    Digest32::of_bytes(&serde_json::to_vec(&parse_integer_json(raw).unwrap()).unwrap())
}

#[test]
fn fresh_owned_projection_retains_complete_bytes_and_python_pins() {
    let value = identify_original_paired_records_v1(
        fresh(FAILURE, CORRECTION),
        &request(FAILURE, CORRECTION),
        pins(),
    )
    .unwrap();
    assert_eq!(value.materials().failure(), FAILURE);
    assert_eq!(value.materials().correction(), CORRECTION);
    assert_eq!(value.original_request(), &request(FAILURE, CORRECTION));
    assert_eq!(
        value.failure_record().record_digest,
        pins().failure_record_digest
    );
    assert_eq!(
        value.correction_record().record_digest,
        pins().correction_record_digest
    );
    assert_eq!(value.failure_record().record_id, "failure");
    assert_eq!(value.correction_record().record_id, "correction");
    assert_eq!(value.failure_record().task_id, "development-receipt-700");
    assert_eq!(
        value.failure_record().task_digest,
        value.correction_record().task_digest
    );
    assert_ne!(
        value.failure_record().declared_source_sha256,
        value.correction_record().declared_source_sha256
    );
}

#[test]
fn raw_whitespace_and_canonical_identity_are_independent() {
    let mut spaced = b" \n".to_vec();
    spaced.extend_from_slice(FAILURE);
    spaced.extend_from_slice(b"\t");
    assert_ne!(Digest32::of_bytes(&spaced), Digest32::of_bytes(FAILURE));
    assert_refused(
        identify_original_paired_records_v1(
            fresh(&spaced, CORRECTION),
            &request(FAILURE, CORRECTION),
            pins(),
        ),
        "raw material",
    );
    let bound = identify_original_paired_records_v1(
        fresh(&spaced, CORRECTION),
        &request(&spaced, CORRECTION),
        pins(),
    )
    .unwrap();
    assert_eq!(
        bound.failure_record().record_digest,
        pins().failure_record_digest
    );
    assert_eq!(bound.materials().failure(), spaced);
}

#[test]
fn unknown_and_retained_are_not_fresh_records() {
    let original_delivery = Digest32::of_bytes(b"fixture-delivery");
    for result in [
        PairedTrainingReadResult::Unknown { original_delivery },
        PairedTrainingReadResult::RetainedReadOnly { original_delivery },
    ] {
        assert_refused(
            identify_original_paired_records_v1(result, &request(FAILURE, CORRECTION), pins()),
            "fresh owned",
        );
    }
}

#[test]
fn duplicate_keys_malformed_utf8_trailing_and_deep_json_refuse() {
    for raw in [
        br#"{"a":1,"a":2}"#.as_slice(),
        br#"{"a":{"x":1,"x":2}}"#,
        b"{} {}",
        b"{\"x\":\"\xff\"}",
    ] {
        assert!(parse_integer_json(raw).is_err());
    }
    let deep = format!("{}0{}", "[".repeat(130), "]".repeat(130));
    assert!(parse_integer_json(deep.as_bytes()).is_err());
    for raw in [b"{}".as_slice(), b"[]", b"null"] {
        assert_refused(
            identify_original_paired_records_v1(
                fresh(raw, CORRECTION),
                &request(raw, CORRECTION),
                PairedRecordPinsV1 {
                    failure_record_digest: canonical_digest(raw),
                    ..pins()
                },
            ),
            "text field",
        );
    }
}

#[test]
fn integer_unicode_canonical_matches_python_and_floats_refuse() {
    let vectors: Vec<Value> = serde_json::from_slice(VECTORS).unwrap();
    for value in vectors {
        let parsed = parse_integer_json(value["raw"].as_str().unwrap().as_bytes()).unwrap();
        let raw = serde_json::to_vec(&parsed).unwrap();
        assert_eq!(raw, value["canonical"].as_str().unwrap().as_bytes());
        assert_eq!(
            Digest32::of_bytes(&raw).to_string(),
            value["sha256"].as_str().unwrap()
        );
    }
    for raw in [
        "1.0",
        "-0",
        "-0.0",
        "1e0",
        "1e999",
        "NaN",
        "Infinity",
        "-Infinity",
        "18446744073709551616",
        "-9223372036854775809",
        "{\"nested\":[0.5]}",
    ] {
        assert!(parse_integer_json(raw.as_bytes()).is_err(), "{raw}");
    }
    let literal = br#"{"$serde_json::private::Number":"1.0"}"#;
    assert_eq!(
        serde_json::to_vec(&parse_integer_json(literal).unwrap()).unwrap(),
        literal
    );
}

#[test]
fn complete_record_includes_extra_and_self_digest_fields() {
    let mut record: Value = serde_json::from_slice(FAILURE).unwrap();
    record["record_sha256"] = json!(pins().failure_record_digest.to_string());
    record["extra"] = json!({"unknown": "retained"});
    let raw = serde_json::to_vec(&record).unwrap();
    assert_refused(
        identify_original_paired_records_v1(
            fresh(&raw, CORRECTION),
            &request(&raw, CORRECTION),
            pins(),
        ),
        "full Python record digest",
    );
    let complete = canonical_digest(&raw);
    assert_ne!(complete, pins().failure_record_digest);
    let value = identify_original_paired_records_v1(
        fresh(&raw, CORRECTION),
        &request(&raw, CORRECTION),
        PairedRecordPinsV1 {
            failure_record_digest: complete,
            ..pins()
        },
    )
    .unwrap();
    assert_eq!(value.failure_record().record_digest, complete);
    assert_eq!(value.materials().failure(), raw);
}

#[test]
fn task_source_time_and_training_declarations_cannot_be_relabelled() {
    for (pointer, replacement) in [
        ("/record_id", json!("failure")),
        ("/task_id", json!("other")),
        ("/lineage_id", json!("other")),
        ("/project_id", json!("other")),
        ("/source/repository", json!("another-issuer")),
        ("/task/input", json!("other input")),
        ("/observed_at", json!(0)),
        ("/available_at", json!(0)),
        ("/split", json!("confirmation")),
        ("/authorization/training_allowed", json!(false)),
        ("/authorization/evaluation_allowed", json!(false)),
        ("/verified_outcome/success", json!(false)),
        ("/verified_outcome/verifier_name", json!("other")),
        ("/source/sha256", json!("BAD")),
    ] {
        let mut record: Value = serde_json::from_slice(CORRECTION).unwrap();
        *record.pointer_mut(pointer).unwrap() = replacement;
        let raw = serde_json::to_vec(&record).unwrap();
        assert!(
            identify_original_paired_records_v1(
                fresh(FAILURE, &raw),
                &request(FAILURE, &raw),
                PairedRecordPinsV1 {
                    correction_record_digest: canonical_digest(&raw),
                    ..pins()
                }
            )
            .is_err(),
            "{pointer}"
        );
    }
}

#[test]
fn original_purpose_commitment_and_material_bounds_are_required() {
    let mut wrong = request(FAILURE, CORRECTION);
    wrong.original.usage = PairedLearningDataUse::EvaluateOnlyAfterFreeze {
        freeze: Digest32::of_bytes(b"freeze"),
        task: Digest32::of_bytes(b"task"),
    };
    assert_refused(
        identify_original_paired_records_v1(fresh(FAILURE, CORRECTION), &wrong, pins()),
        "raw material",
    );
    wrong = request(FAILURE, CORRECTION);
    wrong.materials = Digest32::of_bytes(b"foreign");
    assert_refused(
        identify_original_paired_records_v1(fresh(FAILURE, CORRECTION), &wrong, pins()),
        "raw material",
    );
    let empty = fresh(b"", CORRECTION);
    assert_refused(
        identify_original_paired_records_v1(empty, &request(FAILURE, CORRECTION), pins()),
        "bounded paired",
    );
    let oversized = vec![b' '; 32 * 1024];
    assert_refused(
        identify_original_paired_records_v1(
            fresh(&oversized, CORRECTION),
            &request(FAILURE, CORRECTION),
            pins(),
        ),
        "bounded paired",
    );
}

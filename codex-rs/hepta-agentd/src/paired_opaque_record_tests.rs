//! Synthetic Python capture records exercise the original native identity path.
//! No real human, source capture, generation, permission or training is inferred.
use super::*;
use pretty_assertions::assert_eq;

const OPAQUE: &[u8] = include_bytes!("../tests/fixtures/paired-record-opaque-correction-v1.json");
const OPAQUE_DIGEST: &str = "c53c21ab68bf7799c8e0f05056049b72a9cb5326cfd68bcca9b78ab31c6a98f7";

fn opaque_pins(raw: &[u8]) -> PairedRecordPinsV1 {
    PairedRecordPinsV1 {
        correction_record_digest: canonical_digest(raw),
        ..pins()
    }
}

#[test]
fn opaque_original_bytes_yield_only_one_prompt_and_unverified_observation() {
    let value = identify_original_paired_records_v1(
        fresh(FAILURE, OPAQUE),
        &request(FAILURE, OPAQUE),
        PairedRecordPinsV1 {
            correction_record_digest: OPAQUE_DIGEST.parse().unwrap(),
            ..pins()
        },
    )
    .unwrap();
    assert_eq!(value.materials().failure(), FAILURE);
    assert_eq!(value.materials().correction(), OPAQUE);
    let observation = value.opaque_correction_observation().unwrap();
    assert_eq!(
        observation.evidence(),
        PairedOpaqueEvidenceV1::RecordOnly {
            unverified_capture_sha256: value.correction_record().declared_source_sha256,
        }
    );
    assert_eq!(
        (observation.prompt(), observation.observed_final_answer()),
        ("Return the JSON integer one for this amber receipt.", "1")
    );
    assert_eq!(
        observation.declared_student_policy(),
        "a".repeat(64).parse().unwrap()
    );
    let legacy = identify_original_paired_records_v1(
        fresh(FAILURE, CORRECTION),
        &request(FAILURE, CORRECTION),
        pins(),
    )
    .unwrap();
    assert!(legacy.opaque_correction_observation().is_none());
}

#[test]
fn opaque_recomputed_pins_cannot_upgrade_identity_execution_or_training_declarations() {
    for (pointer, replacement) in [
        ("/production_eligible", json!(true)),
        ("/human_training_consent_proven", json!(true)),
        ("/model_digest", json!("b".repeat(64))),
        ("/teacher_output_receipt_sha256", json!("b".repeat(64))),
        ("/teacher_observation/weights_sha256", json!("b".repeat(64))),
        (
            "/teacher_observation/generation_receipt_sha256",
            json!("b".repeat(64)),
        ),
        ("/teacher_observation/generation_authenticated", json!(true)),
        ("/teacher_observation/execution_authenticated", json!(true)),
        (
            "/teacher_observation/student_policy_sha256",
            json!("b".repeat(64)),
        ),
        ("/teacher_observation/source_sha256", json!("b".repeat(64))),
        ("/trajectory/0/executed", json!(true)),
        ("/trajectory/0/trainable", json!(true)),
        ("/authorization/training_allowed", json!(false)),
        ("/verified_outcome/success", json!(false)),
    ] {
        let mut record: Value = serde_json::from_slice(OPAQUE).unwrap();
        *record.pointer_mut(pointer).unwrap() = replacement;
        let raw = serde_json::to_vec(&record).unwrap();
        assert!(
            identify_original_paired_records_v1(
                fresh(FAILURE, &raw),
                &request(FAILURE, &raw),
                opaque_pins(&raw),
            )
            .is_err(),
            "{pointer}"
        );
    }
}

#[test]
fn opaque_history_and_native_features_are_not_accepted_as_observation_fields() {
    for field in ["messages", "features", "target", "n_classes", "observation"] {
        let mut record: Value = serde_json::from_slice(OPAQUE).unwrap();
        match field {
            "messages" => {
                record["task"][field] = json!([
                    {"role":"user", "content": record["task"]["input"]},
                    {"role":"assistant", "content":"1"},
                    {"role":"user", "content":"Repeat the answer."}
                ])
            }
            "observation" => record["trajectory"].as_array_mut().unwrap().push(json!({
                "index": 1, "actor":"environment", "kind":"observation",
                "content":"1", "executed":false, "receipt_sha256":null
            })),
            _ => record[field] = json!([1]),
        }
        let raw = serde_json::to_vec(&record).unwrap();
        assert!(
            identify_original_paired_records_v1(
                fresh(FAILURE, &raw),
                &request(FAILURE, &raw),
                opaque_pins(&raw)
            )
            .is_err(),
            "{field}"
        );
    }
}

#[test]
fn opaque_is_only_a_fresh_correction_and_never_a_failure_or_replayed_result() {
    assert_refused(
        identify_original_paired_records_v1(
            fresh(OPAQUE, CORRECTION),
            &request(OPAQUE, CORRECTION),
            PairedRecordPinsV1 {
                failure_record_digest: canonical_digest(OPAQUE),
                ..pins()
            },
        ),
        "attempt role",
    );
    for result in [
        PairedTrainingReadResult::Unknown {
            original_delivery: Digest32::of_bytes(b"fixture-delivery"),
        },
        PairedTrainingReadResult::RetainedReadOnly {
            original_delivery: Digest32::of_bytes(b"fixture-delivery"),
        },
    ] {
        assert_refused(
            identify_original_paired_records_v1(
                result,
                &request(FAILURE, OPAQUE),
                opaque_pins(OPAQUE),
            ),
            "fresh owned",
        );
    }
    assert_refused(
        identify_original_paired_records_v1(
            fresh(FAILURE, OPAQUE),
            &request(FAILURE, CORRECTION),
            opaque_pins(OPAQUE),
        ),
        "raw material",
    );
}

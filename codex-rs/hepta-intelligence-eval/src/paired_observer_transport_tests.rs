use super::*;
use crate::freeze_paired_supervised_plan_v1;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use pretty_assertions::assert_eq;

#[test]
fn transport_preserves_original_signed_preimage_and_missing_observations() {
    let fixture = SigningFixture::new(false);
    let plan = freeze_paired_supervised_plan_v1(inputs(8)).unwrap();
    let mut original = fixture.cut(&plan);
    original.cut.rows[0].candidate.outcome = PairedClassObservationV1::Abstain;
    original.cut.rows[0].baseline.outcome = PairedClassObservationV1::Censored {
        reason: id("actual-timeout"),
    };
    original.cut.rows[0].baseline.original_elapsed_micros = None;
    original.cut.rows[0].observed_metrics[0].candidate = None;
    let payload = paired_observation_cut_signing_payload_v1(&original.cut).unwrap();
    original.observer_evidence = fixture.sign(1, &payload, 22);
    let encoded = encode_signed_paired_observation_transport_v1(&original).unwrap();
    let decoded = decode_transport(&encoded).unwrap();
    assert_eq!(decoded, original);
    assert_eq!(
        paired_observation_cut_signing_payload_v1(&decoded.cut).unwrap(),
        payload
    );
    fixture
        .verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &decoded.observer_evidence,
            &payload,
            30,
        )
        .unwrap();
}

#[test]
fn cut_truncation_extra_bytes_and_unknown_or_duplicate_fields_are_rejected() {
    let fixture = SigningFixture::new(false);
    let plan = freeze_paired_supervised_plan_v1(inputs(8)).unwrap();
    let original = fixture.cut(&plan);
    let payload = paired_observation_cut_signing_payload_v1(&original.cut).unwrap();
    for boundary in 0..payload.len() {
        assert!(decode_payload(&payload[..boundary]).is_err());
    }
    let mut extended = payload;
    extended.push(0);
    assert!(decode_payload(&extended).is_err());
    let bytes = encode_signed_paired_observation_transport_v1(&original).unwrap();
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    value["asserted_success"] = serde_json::Value::Bool(true);
    assert!(decode_transport(&serde_json::to_vec(&value).unwrap()).is_err());
    let duplicate = format!(
        "{{\"schema\":\"duplicate\",{}",
        std::str::from_utf8(&bytes).unwrap().trim_start_matches('{')
    );
    assert!(decode_transport(duplicate.as_bytes()).is_err());
}

#[test]
fn transport_is_not_a_signature_or_caller_metric_authority() {
    let fixture = SigningFixture::new(false);
    let plan = freeze_paired_supervised_plan_v1(inputs(8)).unwrap();
    let mut original = fixture.cut(&plan);
    original.cut.rows[0].candidate.original_elapsed_micros = Some(1);
    let bytes = encode_signed_paired_observation_transport_v1(&original).unwrap();
    assert!(decode_transport(&bytes).is_err());
    original.observer_evidence.payload_digest =
        Digest32::of_bytes(&paired_observation_cut_signing_payload_v1(&original.cut).unwrap());
    let decoded =
        decode_transport(&encode_signed_paired_observation_transport_v1(&original).unwrap())
            .unwrap();
    assert!(
        fixture
            .verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                &decoded.observer_evidence,
                &paired_observation_cut_signing_payload_v1(&decoded.cut).unwrap(),
                30
            )
            .is_err()
    );
}

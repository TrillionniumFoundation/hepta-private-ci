use super::*;

fn candidate() -> DynamicGateCandidateV3 {
    DynamicGateCandidateV3 {
        cell_identity: "cell.a".into(),
        encoder_digest: "a".repeat(64),
        input_width: 2,
        output_width: 1,
        rank: 1,
        groups: 2,
        down_q24: vec![Q24, 0],
        up_q24: vec![Q24, Q24],
        gate_bias_q24: vec![0, 0],
        cell_state_q24: vec![0, 0],
        drive_weights_q24: vec![Q24, Q24],
        prediction_weights_q24: vec![Q24, 0],
        drive_bias_q24: vec![0],
        prediction_bias_q24: vec![0],
    }
}

#[test]
fn gate_changes_with_input_and_is_not_absorbable_into_a_fixed_linear_head() {
    let head = DynamicGateArtifactV3::new(candidate()).expect("valid dynamic head");
    assert_eq!(
        head.digest(),
        "31d23d4d80f039d5fbe63b8dfde0f37e36b7f6b044e11b50f4d0b166f3a3ed22"
    );
    let (drive_1, pred_1) = head
        .compute(&"a".repeat(64), "cell.a", &[Q24, Q24], 1)
        .expect("inference");
    let (drive_2, pred_2) = head
        .compute(&"a".repeat(64), "cell.a", &[2 * Q24, Q24], 1)
        .expect("inference");
    assert_eq!(drive_1, vec![3 * Q24 / 2]);
    assert_eq!(pred_1, vec![3 * Q24 / 4]);
    assert_eq!(drive_2, vec![3 * Q24]);
    assert_eq!(pred_2, vec![2 * Q24]);
    assert_ne!(pred_2[0], pred_1[0] * 2);
}

#[test]
fn exact_fractional_q24_input_is_admitted_but_out_of_domain_is_denied() {
    let head = DynamicGateArtifactV3::new(candidate()).expect("valid test head");
    // Decimal 1 + 2^-24 is genuinely representable in Q24. The cross-language
    // Python oracle must not reject it as a non-integral input.
    let (drive, prediction) = head
        .compute(&"a".repeat(64), "cell.a", &[Q24 + 1, Q24], 1)
        .expect("valid fractional Q24 feature");
    assert_eq!(drive.len(), 1);
    assert_eq!(prediction.len(), 1);
    // Actual Q24 absolute limit is 8*Q24, with both endpoints inclusive.
    assert!(head.compute(&"a".repeat(64), "cell.a", &[8 * Q24 + 1, Q24], 1).is_err());
    assert!(head.compute(&"a".repeat(64), "cell.a", &[-8 * Q24 - 1, Q24], 1).is_err());
}

#[test]
fn cell_state_is_private_and_all_model_bytes_change_digest() {
    let first = DynamicGateArtifactV3::new(candidate()).expect("valid");
    let mut other = candidate();
    other.cell_identity = "cell.b".into();
    other.cell_state_q24[0] = -Q24;
    let second = DynamicGateArtifactV3::new(other).expect("valid");
    assert_ne!(first.digest(), second.digest());
    assert_ne!(
        first.compute(&"a".repeat(64), "cell.b", &[Q24, Q24], 1),
        second.compute(&"a".repeat(64), "cell.b", &[Q24, Q24], 1)
    );
    assert!(
        second
            .compute(&"a".repeat(64), "cell.a", &[Q24, Q24], 1)
            .is_err()
    );
}

#[test]
fn bounds_digest_and_dimensions_fail_closed() {
    let mut wrong = candidate();
    wrong.down_q24.pop();
    assert!(DynamicGateArtifactV3::new(wrong).is_err());
    let mut wrong = candidate();
    wrong.rank = 0;
    assert!(DynamicGateArtifactV3::new(wrong).is_err());
    let head = DynamicGateArtifactV3::new(candidate()).expect("valid");
    assert!(
        head.compute(&"b".repeat(64), "cell.a", &[Q24, Q24], 1)
            .is_err()
    );
    assert!(head.compute(&"a".repeat(64), "cell.a", &[Q24], 1).is_err());
    assert!(
        head.compute(&"a".repeat(64), "cell.a", &[9 * Q24, 0], 1)
            .is_err()
    );
    assert_eq!(head.parameter_count(), 14);
    assert_eq!(head.tensor_bytes().expect("bytes"), 112);
}

#[test]
fn impossible_intermediate_q24_value_is_rejected_not_saturated() {
    let mut large = candidate();
    large.down_q24[0] = 8 * Q24;
    let head = DynamicGateArtifactV3::new(large).expect("bounded static weights");
    assert!(
        head.compute(&"a".repeat(64), "cell.a", &[8 * Q24, Q24], 1)
            .is_err()
    );
}

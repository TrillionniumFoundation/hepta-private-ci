use super::*;

use pretty_assertions::assert_eq;

use crate::SparseConfig;
use crate::SparseTick;
use crate::sparse_tick;

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn profile() -> NeuronCalibrationProfileV1 {
    NeuronCalibrationProfileV1 {
        calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
        ood_artifact_digest: Digest32::of_bytes(b"ood"),
        generation: checked(Generation::new(1)),
        valid_from_sequence: 1,
        expires_after_sequence: 10,
        zero_confidence_error_q24: 16 * Q24,
        maximum_in_domain_error_q24: 8 * Q24,
        minimum_confidence_ppm: 500_000,
        maximum_ood_ppm: 500_000,
        minimum_active_ppm: 0,
        maximum_active_ppm: 200_000,
        maximum_projection_count: 100,
        measured_ece_ppm: 0,
        maximum_ece_ppm: 100,
        measured_false_acceptance_ppm: 0,
        maximum_false_acceptance_ppm: 100,
    }
}

fn receipt_for_error(error_q24: i64) -> SparseSignalReceipt {
    let drive = error_q24.min(H_Q24);
    let receipt = receipt_for_prediction(/*width*/ 5, drive, drive - error_q24);
    assert_eq!(receipt.prediction_error_q24, error_q24);
    receipt
}

fn receipt_for_prediction(width: usize, drive: i64, prediction: i64) -> SparseSignalReceipt {
    let config = SparseConfig {
        model_digest: Digest32::of_bytes(b"head"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(1)),
        width,
        top_k: 1,
        temporal_decay_q24: 0,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        activity_decay_q24: 0,
        target_activity_q24: 0,
        threshold_rate_q24: 0,
        threshold_min_q24: 0,
        threshold_max_q24: Q24,
        eligibility_decay_q24: 0,
    };
    let mut drive_q24 = vec![0; width];
    drive_q24[0] = drive;
    let mut prediction_q24 = vec![0; width];
    prediction_q24[0] = prediction;
    let input = SparseTick {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(b"features"),
        sequence: 1,
        monotonic_micros: 1,
        drive_q24,
        prediction_q24,
    };
    let (_, receipt) = checked(sparse_tick(&config, &input, /*previous*/ None));
    receipt
}

#[test]
fn confidence_gate_rejects_error_one_q24_unit_beyond_exact_boundary() {
    let mut profile = profile();
    profile.maximum_ood_ppm = 1_000_000;
    checked(profile.validate(profile.generation));
    assert_eq!(
        checked(calibrate(
            &profile,
            &receipt_for_error(8 * Q24),
            /*sequence*/ 1
        )),
        (500_000, 1_000_000, false)
    );
    assert_eq!(
        checked(calibrate(
            &profile,
            &receipt_for_error(8 * Q24 + 1),
            /*sequence*/ 1
        )),
        (499_999, 1_000_000, true)
    );
}

#[test]
fn ood_gate_rejects_error_one_q24_unit_beyond_exact_boundary() {
    let profile = profile();
    checked(profile.validate(profile.generation));
    assert_eq!(
        checked(calibrate(
            &profile,
            &receipt_for_error(4 * Q24),
            /*sequence*/ 1
        )),
        (750_000, 500_000, false)
    );
    assert_eq!(
        checked(calibrate(
            &profile,
            &receipt_for_error(4 * Q24 + 1),
            /*sequence*/ 1
        )),
        (749_999, 500_001, true)
    );
}

#[test]
fn calibration_zero_and_full_scale_endpoints_are_exact_and_bounded() {
    let profile = profile();
    checked(profile.validate(profile.generation));
    assert_eq!(
        checked(calibrate(
            &profile,
            &receipt_for_error(0),
            /*sequence*/ 1
        )),
        (1_000_000, 0, false)
    );
    assert_eq!(
        checked(calibrate(
            &profile,
            &receipt_for_error(16 * Q24),
            /*sequence*/ 1
        )),
        (0, 1_000_000, true)
    );
}

#[test]
fn active_ceiling_uses_exact_fraction_before_ppm_rounding() {
    let receipt = receipt_for_prediction(/*width*/ 6, Q24, Q24);
    assert_eq!(receipt.active_fraction_ppm, 166_666);
    let mut profile = profile();
    profile.maximum_active_ppm = 166_666;
    checked(profile.validate(profile.generation));
    assert_eq!(
        checked(calibrate(&profile, &receipt, /*sequence*/ 1)),
        (1_000_000, 0, true)
    );
    profile.maximum_active_ppm = 166_667;
    checked(profile.validate(profile.generation));
    assert_eq!(
        checked(calibrate(&profile, &receipt, /*sequence*/ 1)),
        (1_000_000, 0, false)
    );
}

#[test]
fn active_ceiling_accepts_exact_and_zero_activity() {
    let profile = profile();
    checked(profile.validate(profile.generation));
    for receipt in [
        receipt_for_prediction(/*width*/ 5, Q24, Q24),
        receipt_for_prediction(/*width*/ 6, /*drive*/ 0, /*prediction*/ 0),
    ] {
        assert_eq!(
            checked(calibrate(&profile, &receipt, /*sequence*/ 1)),
            (1_000_000, 0, false)
        );
    }
}

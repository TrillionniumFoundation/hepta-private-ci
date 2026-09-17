use super::*;
use crate::model::FrozenModelManifestV1;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn must<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation() -> Generation {
    must(Generation::new(/*value*/ 7))
}

fn manifest() -> FrozenModelManifestV1 {
    FrozenModelManifestV1 {
        model_id: must(StableId::new("neuron:model:calibrated")),
        encoder_digest: digest(b"encoder"),
        head_digest: digest(b"head"),
        weights_digest: digest(b"weights"),
        tokenizer_digest: digest(b"tokenizer"),
        preprocessor_digest: digest(b"preprocessor"),
        quantization_digest: digest(b"quantization"),
        license_sbom_digest: digest(b"license-sbom"),
        runtime_digest: digest(b"runtime"),
        device_digest: digest(b"device"),
        input_width: 3,
        output_width: 5,
    }
}

fn profile() -> CalibrationProfileV1 {
    let manifest = manifest();
    CalibrationProfileV1 {
        calibration_artifact_digest: digest(b"calibration-artifact"),
        ood_artifact_digest: digest(b"ood-artifact"),
        encoder_digest: manifest.encoder_digest,
        head_digest: manifest.head_digest,
        detector_digest: digest(b"detector"),
        support_digest: digest(b"support"),
        generation: generation(),
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        measured_ece_ppm: 15_000,
        maximum_ece_ppm: 20_000,
        measured_ood_false_acceptance_ppm: 4_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        residual_full_confidence_q24: Q / 8,
        residual_abstain_q24: Q,
        maximum_in_domain_ood_q24: Q / 2,
        minimum_confidence_ppm: 300_000,
    }
}

#[test]
fn calibrated_profile_maps_residual_and_ood_deterministically() {
    let assessment = must(assess_calibration(
        &profile(),
        &manifest(),
        generation(),
        /*sequence*/ 10,
        Q / 8,
        Q / 4,
    ));
    assert_eq!(assessment.confidence_ppm, PPM);
    assert_eq!(assessment.ood_ppm, 250_000);
    assert!(!assessment.abstain);
    assert_eq!(assessment.authority, AuthorityPosture::DENY_ALL);
    assert!(!assessment.assessment_digest.is_zero());
}

#[test]
fn high_residual_or_ood_selects_abstention() {
    let residual = must(assess_calibration(
        &profile(),
        &manifest(),
        generation(),
        /*sequence*/ 10,
        Q,
        0,
    ));
    assert_eq!(residual.confidence_ppm, 0);
    assert!(residual.abstain);

    let ood = must(assess_calibration(
        &profile(),
        &manifest(),
        generation(),
        /*sequence*/ 10,
        Q / 8,
        3 * Q / 4,
    ));
    assert_eq!(ood.confidence_ppm, PPM);
    assert_eq!(ood.ood_ppm, 750_000);
    assert!(ood.abstain);
}

#[test]
fn stale_or_unqualified_profiles_fail_before_assessment() {
    let mut stale = profile();
    stale.expires_after_sequence = 9;
    assert_eq!(
        assess_calibration(
            &stale,
            &manifest(),
            generation(),
            /*sequence*/ 10,
            0,
            0,
        ),
        Err(CalibrationError::SequenceOutsideWindow)
    );

    let mut unqualified = profile();
    unqualified.measured_ece_ppm = unqualified.maximum_ece_ppm + 1;
    assert_eq!(unqualified.digest(), Err(CalibrationError::InvalidProfile));

    let mut mismatch = profile();
    mismatch.head_digest = digest(b"other-head");
    assert_eq!(
        assess_calibration(
            &mismatch,
            &manifest(),
            generation(),
            /*sequence*/ 1,
            0,
            0,
        ),
        Err(CalibrationError::ModelMismatch)
    );
}

#[test]
fn profile_digest_binds_external_quality_evidence() {
    let original = profile();
    let expected = must(original.digest());
    let mut changed = original;
    changed.measured_ood_false_acceptance_ppm += 1;
    assert_ne!(must(changed.digest()), expected);
}

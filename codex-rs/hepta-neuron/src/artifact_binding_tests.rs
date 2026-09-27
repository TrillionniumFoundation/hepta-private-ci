use super::*;
use pretty_assertions::assert_eq;

#[test]
fn artifact_profile_is_non_circular_but_binds_executable_parameters() {
    let native = native_config();
    let config = runtime_config(&native);
    let profile = checked(config.execution_profile_digest_v1());
    let mut changed = config.clone();
    changed.model_manifest_digest = Digest32::of_bytes(b"published-manifest");
    changed.calibration.calibration_artifact_digest = Digest32::of_bytes(b"published-calibration");
    changed.calibration.ood_artifact_digest = Digest32::of_bytes(b"published-ood");
    assert_eq!(checked(changed.execution_profile_digest_v1()), profile);
    assert_ne!(
        checked(changed.semantic_digest()),
        checked(config.semantic_digest())
    );
    changed.weights_digest = Digest32::of_bytes(b"different-trained-weights");
    assert_ne!(checked(changed.execution_profile_digest_v1()), profile);
}

#[test]
fn evidence_bytes_bind_model_and_measured_profile_without_self_reference() {
    let native = native_config();
    let config = runtime_config(&native);
    let calibration = checked(config.calibration_evidence_payload_v1());
    let ood = checked(config.ood_evidence_payload_v1());
    assert_ne!(calibration, ood);
    let mut bound = config.clone();
    bound.calibration.calibration_artifact_digest = Digest32::of_bytes(&calibration);
    bound.calibration.ood_artifact_digest = Digest32::of_bytes(&ood);
    assert_eq!(
        checked(bound.calibration_evidence_payload_v1()),
        calibration
    );
    assert_eq!(checked(bound.ood_evidence_payload_v1()), ood);
    bound.calibration.measured_ece_ppm += 1;
    assert_ne!(
        checked(bound.calibration_evidence_payload_v1()),
        calibration
    );
    bound = config;
    bound.tokenizer_digest = Digest32::of_bytes(b"different-tokenizer");
    assert_ne!(checked(bound.ood_evidence_payload_v1()), ood);
}

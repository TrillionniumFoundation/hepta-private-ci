//! Canonical binding of a readonly calibration cut, separate from qualification.
use codex_hepta_types::Digest32;
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibrationCutBindingV1 {
    pub observer_program_digest: Digest32,
    pub ledger_binding_digest: Digest32,
    pub ledger_file_digest: Digest32,
    pub acknowledged_sequence: u64,
    pub acknowledged_head: Digest32,
    pub candidate_manifest_digest: Digest32,
    pub baseline_manifest_digest: Digest32,
    pub candidate_weights_digest: Digest32,
    pub baseline_weights_digest: Digest32,
    pub audit_digest: Digest32,
    pub dataset_digest: Digest32,
    pub generator_payload_digest: Digest32,
    pub generator_authentication_digest: Digest32,
    pub freeze_payload_digest: Digest32,
    pub freeze_authentication_digest: Digest32,
}
pub fn calibration_cut_signing_payload_v1(value: &CalibrationCutBindingV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.authenticated-calibration-cut.v1".to_vec();
    bytes.extend_from_slice(&value.acknowledged_sequence.to_be_bytes());
    for digest in [
        value.observer_program_digest,
        value.ledger_binding_digest,
        value.ledger_file_digest,
        value.acknowledged_head,
        value.candidate_manifest_digest,
        value.baseline_manifest_digest,
        value.candidate_weights_digest,
        value.baseline_weights_digest,
        value.audit_digest,
        value.dataset_digest,
        value.generator_payload_digest,
        value.generator_authentication_digest,
        value.freeze_payload_digest,
        value.freeze_authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

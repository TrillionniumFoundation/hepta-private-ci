//! A bounded current calibration cycle over an intact acknowledged history.
//! Repeated original tasks remain repeated measurements, never independent n.
use crate::CalibrationCutBindingV1;
use crate::calibration_cut_signing_payload_v1;
use codex_hepta_types::Digest32;
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibrationCycleScopeV2 {
    pub first_sequence: u64,
    pub previous_acknowledged_head: Digest32,
    pub original_task_sources_digest: Digest32,
    pub run_snapshot_digests: Vec<[Digest32; 2]>,
    pub current_program_approval_digest: Digest32,
}
pub fn calibration_cycle_cut_signing_payload_v2(
    cut: &CalibrationCutBindingV1,
    cycle: &CalibrationCycleScopeV2,
) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.authenticated-calibration-cycle.v2".to_vec();
    bytes
        .extend_from_slice(Digest32::of_bytes(&calibration_cut_signing_payload_v1(cut)).as_array());
    bytes.extend_from_slice(&cycle.first_sequence.to_be_bytes());
    for digest in [
        cycle.previous_acknowledged_head,
        cycle.original_task_sources_digest,
        cycle.current_program_approval_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(cycle.run_snapshot_digests.len() as u64).to_be_bytes());
    for pair in &cycle.run_snapshot_digests {
        for snapshot in pair {
            bytes.extend_from_slice(snapshot.as_array());
        }
    }
    bytes
}

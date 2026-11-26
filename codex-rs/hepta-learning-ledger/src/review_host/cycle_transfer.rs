//! Explicit V2 transfer: intact full ledger plus a complete current cycle.
use super::files::ReviewResult;
use super::transfer::FixedCalibrationCutV1;
use super::transfer::FixedCalibrationPublicationV1;
use super::transfer::ReviewEvidenceWireV1;
use super::transfer::ReviewTrustWireV1;
use crate::CalibrationCycleScopeV2;
use crate::calibration_cycle_cut_signing_payload_v2;
use serde::Deserialize;
use serde::Serialize;
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CalibrationCycleScopeWireV2 {
    pub first_sequence: u64,
    pub previous_acknowledged_head: String,
    pub original_task_sources_digest: String,
    pub run_snapshot_digests: Vec<[String; 2]>,
    pub current_program_approval_digest: String,
}
impl CalibrationCycleScopeWireV2 {
    pub fn from_native(value: &CalibrationCycleScopeV2) -> Self {
        Self {
            first_sequence: value.first_sequence,
            previous_acknowledged_head: value.previous_acknowledged_head.to_string(),
            original_task_sources_digest: value.original_task_sources_digest.to_string(),
            run_snapshot_digests: value
                .run_snapshot_digests
                .iter()
                .map(|p| [p[0].to_string(), p[1].to_string()])
                .collect(),
            current_program_approval_digest: value.current_program_approval_digest.to_string(),
        }
    }
    pub fn native(&self) -> ReviewResult<CalibrationCycleScopeV2> {
        if self.run_snapshot_digests.is_empty() || self.run_snapshot_digests.len() > 2048 {
            return Err("bounded complete calibration cycle".into());
        }
        Ok(CalibrationCycleScopeV2 {
            first_sequence: self.first_sequence,
            previous_acknowledged_head: self.previous_acknowledged_head.parse()?,
            original_task_sources_digest: self.original_task_sources_digest.parse()?,
            run_snapshot_digests: self
                .run_snapshot_digests
                .iter()
                .map(|p| Ok([p[0].parse()?, p[1].parse()?]))
                .collect::<ReviewResult<Vec<_>>>()?,
            current_program_approval_digest: self.current_program_approval_digest.parse()?,
        })
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedCalibrationPublicationV2 {
    pub schema: String,
    pub cut: FixedCalibrationCutV1,
    pub cycle: CalibrationCycleScopeWireV2,
    pub observer_evidence: ReviewEvidenceWireV1,
    pub trust: ReviewTrustWireV1,
}
impl FixedCalibrationPublicationV2 {
    pub fn signing_payload(&self) -> ReviewResult<Vec<u8>> {
        if self.schema != "hepta.signed-calibration-cycle-publication.v2" {
            return Err("calibration cycle publication schema".into());
        }
        Ok(calibration_cycle_cut_signing_payload_v2(
            &self.cut.binding()?,
            &self.cycle.native()?,
        ))
    }
    pub fn into_original_fields(self) -> FixedCalibrationPublicationV1 {
        FixedCalibrationPublicationV1 {
            cut: self.cut,
            observer_evidence: self.observer_evidence,
            trust: self.trust,
        }
    }
}

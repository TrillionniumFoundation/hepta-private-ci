//! Target-host durability qualification contract.
//!
//! Source tests can exercise process crashes and format corruption, but they
//! cannot truthfully manufacture physical power-loss evidence. This module
//! defines the closed fault matrix and validates independently retained target-
//! host observations. A qualification report is complete only when every
//! required boundary/fault pair is present, source/host/filesystem identities
//! are immutable, and no observation upgrades an unknown effect to success.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum DurabilityBoundaryV1 {
    Write,
    FileSync,
    ChildDirectorySync,
    ParentDirectorySync,
    CheckpointAppend,
    HeadPublication,
    Acknowledgement,
    RestartReopen,
}

impl DurabilityBoundaryV1 {
    pub const ALL: [Self; 8] = [
        Self::Write,
        Self::FileSync,
        Self::ChildDirectorySync,
        Self::ParentDirectorySync,
        Self::CheckpointAppend,
        Self::HeadPublication,
        Self::Acknowledgement,
        Self::RestartReopen,
    ];
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum DurabilityFaultV1 {
    ProcessTermination,
    ForcedUnmount,
    VmPowerCut,
    TruncatedWrite,
    DelayedWrite,
    OldDirectorySnapshotRestore,
    OldSingleFileRestore,
    ExactOperationRetry,
}

impl DurabilityFaultV1 {
    pub const ALL: [Self; 8] = [
        Self::ProcessTermination,
        Self::ForcedUnmount,
        Self::VmPowerCut,
        Self::TruncatedWrite,
        Self::DelayedWrite,
        Self::OldDirectorySnapshotRestore,
        Self::OldSingleFileRestore,
        Self::ExactOperationRetry,
    ];

    #[must_use]
    pub const fn requires_external_host_control(self) -> bool {
        matches!(
            self,
            Self::ForcedUnmount
                | Self::VmPowerCut
                | Self::DelayedWrite
                | Self::OldDirectorySnapshotRestore
                | Self::OldSingleFileRestore
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurabilityObservationV1 {
    RejectedBeforeEffect,
    ExactStateRecovered,
    ExactRetryReturnedOriginalReceipt,
    RecoveryRequired,
    CorruptionRejected,
    RollbackRejected,
    EffectIndeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurabilityEvidenceIdentityV1 {
    pub source_commit: Digest32,
    pub source_tree: Digest32,
    pub binary_digest: Digest32,
    pub runner_image_digest: Digest32,
    pub kernel_profile_digest: Digest32,
    pub filesystem_profile_digest: Digest32,
    pub block_device_profile_digest: Digest32,
    pub target_host_id: StableId,
}

impl DurabilityEvidenceIdentityV1 {
    fn validate(&self) -> Result<(), DurabilityQualificationErrorV1> {
        if self.source_commit.is_zero()
            || self.source_tree.is_zero()
            || self.binary_digest.is_zero()
            || self.runner_image_digest.is_zero()
            || self.kernel_profile_digest.is_zero()
            || self.filesystem_profile_digest.is_zero()
            || self.block_device_profile_digest.is_zero()
        {
            return Err(DurabilityQualificationErrorV1::InvalidIdentity);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurabilityCaseEvidenceV1 {
    pub boundary: DurabilityBoundaryV1,
    pub fault: DurabilityFaultV1,
    pub observation: DurabilityObservationV1,
    pub operation_digest: Digest32,
    pub pre_fault_state_digest: Digest32,
    pub post_restart_state_digest: Digest32,
    pub retained_log_digest: Digest32,
    pub acknowledgement_returned_before_fault: bool,
    pub independently_observed: bool,
}

impl DurabilityCaseEvidenceV1 {
    fn validate(&self) -> Result<(), DurabilityQualificationErrorV1> {
        if self.operation_digest.is_zero()
            || self.pre_fault_state_digest.is_zero()
            || self.post_restart_state_digest.is_zero()
            || self.retained_log_digest.is_zero()
        {
            return Err(DurabilityQualificationErrorV1::InvalidCaseIdentity);
        }
        if self.fault.requires_external_host_control() && !self.independently_observed {
            return Err(DurabilityQualificationErrorV1::ExternalObservationMissing);
        }
        if self.acknowledgement_returned_before_fault
            && matches!(
                self.observation,
                DurabilityObservationV1::RejectedBeforeEffect
                    | DurabilityObservationV1::RecoveryRequired
                    | DurabilityObservationV1::CorruptionRejected
                    | DurabilityObservationV1::EffectIndeterminate
            )
        {
            return Err(DurabilityQualificationErrorV1::AcknowledgementContradiction);
        }
        if !self.acknowledgement_returned_before_fault
            && self.observation == DurabilityObservationV1::ExactRetryReturnedOriginalReceipt
            && self.boundary < DurabilityBoundaryV1::Acknowledgement
        {
            return Err(DurabilityQualificationErrorV1::ReceiptContradiction);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurabilityQualificationReportV1 {
    pub identity: DurabilityEvidenceIdentityV1,
    pub attempt_id: StableId,
    pub started_at: u64,
    pub completed_at: u64,
    pub cases: Vec<DurabilityCaseEvidenceV1>,
    pub independent_operator_digest: Digest32,
}

impl DurabilityQualificationReportV1 {
    pub fn validate_complete(&self) -> Result<(), DurabilityQualificationErrorV1> {
        self.identity.validate()?;
        if self.started_at == 0
            || self.completed_at < self.started_at
            || self.independent_operator_digest.is_zero()
        {
            return Err(DurabilityQualificationErrorV1::InvalidReport);
        }
        let mut observed = BTreeMap::new();
        for case in &self.cases {
            case.validate()?;
            let key = (case.boundary, case.fault);
            if observed.insert(key, case.observation).is_some() {
                return Err(DurabilityQualificationErrorV1::DuplicateCase);
            }
        }
        for boundary in DurabilityBoundaryV1::ALL {
            for fault in DurabilityFaultV1::ALL {
                if !observed.contains_key(&(boundary, fault)) {
                    return Err(DurabilityQualificationErrorV1::MissingCase {
                        boundary,
                        fault,
                    });
                }
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn external_physical_durability_proved(&self) -> bool {
        self.validate_complete().is_ok()
            && self.cases.iter().filter(|case| case.fault.requires_external_host_control()).all(
                |case| {
                    case.independently_observed
                        && case.observation != DurabilityObservationV1::EffectIndeterminate
                },
            )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurabilityQualificationErrorV1 {
    InvalidIdentity,
    InvalidCaseIdentity,
    ExternalObservationMissing,
    AcknowledgementContradiction,
    ReceiptContradiction,
    InvalidReport,
    DuplicateCase,
    MissingCase {
        boundary: DurabilityBoundaryV1,
        fault: DurabilityFaultV1,
    },
}

impl fmt::Display for DurabilityQualificationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurabilityQualificationErrorV1 {}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }

    fn complete_report() -> DurabilityQualificationReportV1 {
        let cases = DurabilityBoundaryV1::ALL
            .into_iter()
            .flat_map(|boundary| {
                DurabilityFaultV1::ALL.into_iter().map(move |fault| {
                    DurabilityCaseEvidenceV1 {
                        boundary,
                        fault,
                        observation: if matches!(
                            fault,
                            DurabilityFaultV1::OldDirectorySnapshotRestore
                                | DurabilityFaultV1::OldSingleFileRestore
                        ) {
                            DurabilityObservationV1::RollbackRejected
                        } else if fault == DurabilityFaultV1::ExactOperationRetry {
                            DurabilityObservationV1::ExactStateRecovered
                        } else {
                            DurabilityObservationV1::RecoveryRequired
                        },
                        operation_digest: digest("operation"),
                        pre_fault_state_digest: digest("before"),
                        post_restart_state_digest: digest("after"),
                        retained_log_digest: digest("log"),
                        acknowledgement_returned_before_fault: false,
                        independently_observed: fault.requires_external_host_control(),
                    }
                })
            })
            .collect();
        DurabilityQualificationReportV1 {
            identity: DurabilityEvidenceIdentityV1 {
                source_commit: digest("commit"),
                source_tree: digest("tree"),
                binary_digest: digest("binary"),
                runner_image_digest: digest("runner"),
                kernel_profile_digest: digest("kernel"),
                filesystem_profile_digest: digest("filesystem"),
                block_device_profile_digest: digest("block"),
                target_host_id: StableId::new("qualification-host".to_owned())
                    .expect("target host id"),
            },
            attempt_id: StableId::new("qualification-attempt".to_owned())
                .expect("attempt id"),
            started_at: 10,
            completed_at: 20,
            cases,
            independent_operator_digest: digest("operator"),
        }
    }

    #[test]
    fn closed_matrix_requires_every_boundary_and_fault() {
        let report = complete_report();
        assert!(report.validate_complete().is_ok());
        assert!(report.external_physical_durability_proved());

        let mut incomplete = report;
        incomplete.cases.pop();
        assert!(matches!(
            incomplete.validate_complete(),
            Err(DurabilityQualificationErrorV1::MissingCase { .. })
        ));
        assert!(!incomplete.external_physical_durability_proved());
    }

    #[test]
    fn externally_controlled_faults_require_independent_observation() {
        let mut report = complete_report();
        let power_cut = report
            .cases
            .iter_mut()
            .find(|case| case.fault == DurabilityFaultV1::VmPowerCut)
            .expect("power-cut case");
        power_cut.independently_observed = false;
        assert_eq!(
            report.validate_complete(),
            Err(DurabilityQualificationErrorV1::ExternalObservationMissing)
        );
    }
}

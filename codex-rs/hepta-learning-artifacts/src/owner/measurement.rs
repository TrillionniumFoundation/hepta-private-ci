//! Bounded, authority-free measurements around the existing owner protocol.
//!
//! These wrappers do not change durable ordering, skip synchronization, or turn
//! measurements into admission evidence. They expose the actual method boundary
//! costs so target-host qualification can decide whether an index or cache is
//! justified without weakening identity, recovery, or directory durability.

use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistrySnapshotReceipt;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

const MAX_MEASUREMENT_SAMPLES: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactOwnerMeasuredStageV1 {
    OwnerOpen,
    StartupRegistryRecovery,
    PreparedCheckpoint,
    PayloadValidateHashWriteSyncCheckpoint,
    RegistryEncodeWriteSyncCheckpoint,
    CurrentHeadWitnessSwitchCheckpoint,
    AcknowledgementCheckpoint,
    RecoveryReconcile,
    PinnedCurrentViewAcquire,
}

impl ArtifactOwnerMeasuredStageV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::OwnerOpen => "owner_open",
            Self::StartupRegistryRecovery => "startup_registry_recovery",
            Self::PreparedCheckpoint => "prepared_checkpoint",
            Self::PayloadValidateHashWriteSyncCheckpoint => {
                "payload_validate_hash_write_sync_checkpoint"
            }
            Self::RegistryEncodeWriteSyncCheckpoint => {
                "registry_encode_write_sync_checkpoint"
            }
            Self::CurrentHeadWitnessSwitchCheckpoint => {
                "current_head_witness_switch_checkpoint"
            }
            Self::AcknowledgementCheckpoint => "acknowledgement_checkpoint",
            Self::RecoveryReconcile => "recovery_reconcile",
            Self::PinnedCurrentViewAcquire => "pinned_current_view_acquire",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerMeasuredOutcomeV1 {
    Success,
    Failure,
}

impl ArtifactOwnerMeasuredOutcomeV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Failure => "failure",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerStageSampleV1 {
    pub stage: ArtifactOwnerMeasuredStageV1,
    pub elapsed_micros: u64,
    pub input_bytes: u64,
    pub records: u64,
    pub outcome: ArtifactOwnerMeasuredOutcomeV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerStageReportV1 {
    pub samples: Vec<ArtifactOwnerStageSampleV1>,
    pub dropped_samples: u64,
    /// Pin and physical-erasure accounting belong to the consumer/retention
    /// owners. This recorder must not misreport unknown values as zero.
    pub resource_accounting_complete: bool,
}

impl ArtifactOwnerStageReportV1 {
    #[must_use]
    pub fn response_json(&self) -> String {
        let samples = self
            .samples
            .iter()
            .map(|sample| {
                format!(
                    concat!(
                        "{{\"stage\":\"{}\",\"elapsedMicros\":{},",
                        "\"inputBytes\":{},\"records\":{},\"outcome\":\"{}\"}}"
                    ),
                    sample.stage.as_str(),
                    sample.elapsed_micros,
                    sample.input_bytes,
                    sample.records,
                    sample.outcome.as_str(),
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        format!(
            concat!(
                "{{\"schema\":\"hepta.learning-artifacts.owner-stage-report.v1\",",
                "\"samples\":[{}],\"droppedSamples\":{},",
                "\"resourceAccountingComplete\":{},",
                "\"pinnedBytes\":null,\"pendingPhysicalEraseBytes\":null}}"
            ),
            samples, self.dropped_samples, self.resource_accounting_complete
        )
    }
}

#[derive(Debug, Default)]
pub struct ArtifactOwnerStageRecorderV1 {
    samples: Mutex<Vec<ArtifactOwnerStageSampleV1>>,
    dropped_samples: AtomicU64,
}

impl ArtifactOwnerStageRecorderV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn measure<T, E>(
        &self,
        stage: ArtifactOwnerMeasuredStageV1,
        input_bytes: u64,
        records: u64,
        operation: impl FnOnce() -> Result<T, E>,
    ) -> Result<T, E> {
        let started = Instant::now();
        let result = operation();
        let elapsed_micros =
            u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let sample = ArtifactOwnerStageSampleV1 {
            stage,
            elapsed_micros,
            input_bytes,
            records,
            outcome: if result.is_ok() {
                ArtifactOwnerMeasuredOutcomeV1::Success
            } else {
                ArtifactOwnerMeasuredOutcomeV1::Failure
            },
        };
        match self.samples.lock() {
            Ok(mut samples) if samples.len() < MAX_MEASUREMENT_SAMPLES => samples.push(sample),
            Ok(_) | Err(_) => {
                self.dropped_samples.fetch_add(1, Ordering::Relaxed);
            }
        }
        result
    }

    #[must_use]
    pub fn report(&self) -> ArtifactOwnerStageReportV1 {
        let samples = self
            .samples
            .lock()
            .map_or_else(|_| Vec::new(), |samples| samples.clone());
        ArtifactOwnerStageReportV1 {
            samples,
            dropped_samples: self.dropped_samples.load(Ordering::Relaxed),
            resource_accounting_complete: false,
        }
    }
}

/// Measurement-only wrapper over the existing authoritative owner. The wrapped
/// methods execute exactly the same implementation and return the same errors.
pub struct MeasuredLearningArtifactOwnerHostV1 {
    host: LearningArtifactOwnerHost,
    recorder: Arc<ArtifactOwnerStageRecorderV1>,
}

impl MeasuredLearningArtifactOwnerHostV1 {
    pub fn open(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        lease: SignedArtifactWriterLeaseV1,
        now: u64,
        recorder: Arc<ArtifactOwnerStageRecorderV1>,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let root = root.as_ref().to_path_buf();
        let host = recorder.measure(
            ArtifactOwnerMeasuredStageV1::OwnerOpen,
            0,
            0,
            || LearningArtifactOwnerHost::open(root, trust, lease, now),
        )?;
        Ok(Self { host, recorder })
    }

    pub fn open_with_required_current_head(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        lease: SignedArtifactWriterLeaseV1,
        required_current_head: SignedCurrentArtifactHeadV1,
        now: u64,
        recorder: Arc<ArtifactOwnerStageRecorderV1>,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let root = root.as_ref().to_path_buf();
        let host = recorder.measure(
            ArtifactOwnerMeasuredStageV1::OwnerOpen,
            0,
            0,
            || {
                LearningArtifactOwnerHost::open_with_required_current_head(
                    root,
                    trust,
                    lease,
                    required_current_head,
                    now,
                )
            },
        )?;
        Ok(Self { host, recorder })
    }

    #[must_use]
    pub fn recorder(&self) -> Arc<ArtifactOwnerStageRecorderV1> {
        Arc::clone(&self.recorder)
    }

    #[must_use]
    pub fn host(&self) -> &LearningArtifactOwnerHost {
        &self.host
    }

    pub fn recover_current_registry(
        &self,
        now: u64,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::StartupRegistryRecovery,
            0,
            0,
            || self.host.recover_current_registry(now),
        )
    }

    pub fn begin_publication(
        &self,
        operation_id: StableId,
        admission: WithdrawalBoundArtifactAdmissionV3,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        registry: &ArtifactRegistry,
        expected_registry_predecessor_head: Digest32,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::PreparedCheckpoint,
            0,
            u64::try_from(registry.records().len()).unwrap_or(u64::MAX),
            || {
                self.host.begin_publication(
                    operation_id,
                    admission,
                    withdrawal_registry,
                    registry,
                    expected_registry_predecessor_head,
                    now,
                )
            },
        )
    }

    pub fn ensure_payload_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        staged_registry: &ArtifactRegistry,
        bytes: &[u8],
        now: u64,
    ) -> Result<PathBuf, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::PayloadValidateHashWriteSyncCheckpoint,
            u64::try_from(bytes.len()).unwrap_or(u64::MAX),
            u64::try_from(staged_registry.records().len()).unwrap_or(u64::MAX),
            || {
                self.host.ensure_payload_durable(
                    transaction,
                    staged_registry,
                    bytes,
                    now,
                )
            },
        )
    }

    pub fn ensure_registry_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        registry: &ArtifactRegistry,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        binding: Digest32,
        now: u64,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::RegistryEncodeWriteSyncCheckpoint,
            0,
            u64::try_from(registry.records().len()).unwrap_or(u64::MAX),
            || {
                self.host.ensure_registry_durable(
                    transaction,
                    registry,
                    withdrawal_registry,
                    binding,
                    now,
                )
            },
        )
    }

    pub fn ensure_witness_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        signed: &SignedCurrentArtifactHeadV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<RegistryHeadWitnessReceipt, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::CurrentHeadWitnessSwitchCheckpoint,
            0,
            0,
            || {
                self.host.ensure_witness_durable(
                    transaction,
                    signed,
                    withdrawal_registry,
                    now,
                )
            },
        )
    }

    pub fn acknowledge(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<ArtifactPublicationReceiptV1, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::AcknowledgementCheckpoint,
            0,
            0,
            || self.host.acknowledge(transaction, withdrawal_registry, now),
        )
    }

    pub fn recover_publication(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<crate::ArtifactOwnerRecoveryV1>, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::RecoveryReconcile,
            0,
            0,
            || self.host.recover_publication(operation_id),
        )
    }

    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        self.recorder.measure(
            ArtifactOwnerMeasuredStageV1::PinnedCurrentViewAcquire,
            0,
            0,
            || self.host.current_registry_view(now),
        )
    }

    #[must_use]
    pub fn into_inner(self) -> LearningArtifactOwnerHost {
        self.host
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recorder_retains_success_and_failure_without_fabricating_resource_counts() {
        let recorder = ArtifactOwnerStageRecorderV1::new();
        let success: Result<u8, ()> = recorder.measure(
            ArtifactOwnerMeasuredStageV1::PreparedCheckpoint,
            7,
            1,
            || Ok(1),
        );
        assert_eq!(success, Ok(1));
        let failure: Result<(), &str> = recorder.measure(
            ArtifactOwnerMeasuredStageV1::RecoveryReconcile,
            0,
            0,
            || Err("failed"),
        );
        assert_eq!(failure, Err("failed"));
        let report = recorder.report();
        assert_eq!(report.samples.len(), 2);
        assert_eq!(
            report.samples[0].outcome,
            ArtifactOwnerMeasuredOutcomeV1::Success
        );
        assert_eq!(
            report.samples[1].outcome,
            ArtifactOwnerMeasuredOutcomeV1::Failure
        );
        assert!(!report.resource_accounting_complete);
        let json = report.response_json();
        assert!(json.contains("\"pinnedBytes\":null"));
        assert!(json.contains("\"pendingPhysicalEraseBytes\":null"));
    }
}

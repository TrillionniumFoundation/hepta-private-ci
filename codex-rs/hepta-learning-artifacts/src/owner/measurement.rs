//! Bounded stage measurements for the learning-artifact owner.
//!
//! Measurements are observations only. They never relax durability, identity,
//! withdrawal, recovery, selection, activation or release checks.

use std::fs::File;
use std::path::Path;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactRegistry;
use crate::ArtifactStorageError;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactOwnerServiceError;
use crate::LoadedPinnedCandidate;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistryHeadWitnessV1;
use crate::RegistrySnapshotReceipt;
use crate::load_pinned_candidate;
use crate::write_candidate_payload_beneath;
use crate::write_registry_head_witness_beneath;
use crate::write_registry_snapshot_beneath;

const LATENCY_BUCKET_UPPER_MICROS: [u64; 7] = [100, 500, 1_000, 5_000, 10_000, 50_000, 250_000];

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactOwnerStageV1 {
    PayloadEncodeHash,
    PayloadWriteSync,
    RegistryWriteSync,
    CurrentHeadSwitch,
    CheckpointSync,
    StartupRecoveryScan,
    PinnedLoad,
    RequestTotal,
    PublicationTotal,
    RecoveryTotal,
    WithdrawalInstallTotal,
    BackupTotal,
    ShutdownTotal,
}

impl ArtifactOwnerStageV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::PayloadEncodeHash => "payload_encode_hash",
            Self::PayloadWriteSync => "payload_write_sync",
            Self::RegistryWriteSync => "registry_write_sync",
            Self::CurrentHeadSwitch => "current_head_switch",
            Self::CheckpointSync => "checkpoint_sync",
            Self::StartupRecoveryScan => "startup_recovery_scan",
            Self::PinnedLoad => "pinned_load",
            Self::RequestTotal => "request_total",
            Self::PublicationTotal => "publication_total",
            Self::RecoveryTotal => "recovery_total",
            Self::WithdrawalInstallTotal => "withdrawal_install_total",
            Self::BackupTotal => "backup_total",
            Self::ShutdownTotal => "shutdown_total",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerStageSampleV1 {
    pub stage: ArtifactOwnerStageV1,
    pub elapsed_micros: u64,
    pub bytes: u64,
    pub records: u64,
    pub success: bool,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactOwnerStageSummaryV1 {
    pub samples: u64,
    pub failures: u64,
    pub total_micros: u64,
    pub maximum_micros: u64,
    pub buckets: [u64; 8],
}

impl ArtifactOwnerStageSummaryV1 {
    pub fn observe(&mut self, sample: ArtifactOwnerStageSampleV1) {
        self.samples = self.samples.saturating_add(1);
        if !sample.success {
            self.failures = self.failures.saturating_add(1);
        }
        self.total_micros = self.total_micros.saturating_add(sample.elapsed_micros);
        self.maximum_micros = self.maximum_micros.max(sample.elapsed_micros);
        let bucket = LATENCY_BUCKET_UPPER_MICROS
            .iter()
            .position(|upper| sample.elapsed_micros <= *upper)
            .unwrap_or(LATENCY_BUCKET_UPPER_MICROS.len());
        self.buckets[bucket] = self.buckets[bucket].saturating_add(1);
    }

    #[must_use]
    pub fn response_json(self) -> String {
        format!(
            concat!(
                "{{\"samples\":{},\"failures\":{},\"totalMicros\":{},",
                "\"maximumMicros\":{},\"buckets\":[{},{},{},{},{},{},{},{}]}}"
            ),
            self.samples,
            self.failures,
            self.total_micros,
            self.maximum_micros,
            self.buckets[0],
            self.buckets[1],
            self.buckets[2],
            self.buckets[3],
            self.buckets[4],
            self.buckets[5],
            self.buckets[6],
            self.buckets[7],
        )
    }
}

pub fn measure_stage<T, E>(
    stage: ArtifactOwnerStageV1,
    bytes: u64,
    records: u64,
    operation: impl FnOnce() -> Result<T, E>,
) -> (Result<T, E>, ArtifactOwnerStageSampleV1) {
    let started = Instant::now();
    let result = operation();
    let sample = ArtifactOwnerStageSampleV1 {
        stage,
        elapsed_micros: elapsed_micros(started),
        bytes,
        records,
        success: result.is_ok(),
    };
    (result, sample)
}

#[must_use]
pub fn measure_payload_encode_hash(bytes: &[u8]) -> (Digest32, ArtifactOwnerStageSampleV1) {
    let started = Instant::now();
    let digest = Digest32::of_bytes(bytes);
    (
        digest,
        ArtifactOwnerStageSampleV1 {
            stage: ArtifactOwnerStageV1::PayloadEncodeHash,
            elapsed_micros: elapsed_micros(started),
            bytes: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
            records: 0,
            success: true,
        },
    )
}

pub fn measure_candidate_payload_write(
    root: &Path,
    relative: &Path,
    registry: &ArtifactRegistry,
    artifact_id: &StableId,
    bytes: &[u8],
) -> (Result<Digest32, ArtifactStorageError>, ArtifactOwnerStageSampleV1) {
    measure_stage(
        ArtifactOwnerStageV1::PayloadWriteSync,
        u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        u64::try_from(registry.records().len()).unwrap_or(u64::MAX),
        || write_candidate_payload_beneath(root, relative, registry, artifact_id, bytes),
    )
}

pub fn measure_registry_snapshot_write(
    root: &Path,
    relative: &Path,
    registry: &ArtifactRegistry,
    binding: Digest32,
) -> (
    Result<RegistrySnapshotReceipt, ArtifactStorageError>,
    ArtifactOwnerStageSampleV1,
) {
    measure_stage(
        ArtifactOwnerStageV1::RegistryWriteSync,
        0,
        u64::try_from(registry.records().len()).unwrap_or(u64::MAX),
        || write_registry_snapshot_beneath(root, relative, registry, binding),
    )
}

pub fn measure_registry_head_witness_write(
    root: &Path,
    relative: &Path,
    witness: &RegistryHeadWitnessV1,
    requirement: &RegistryHeadRequirementV1,
    binding: Digest32,
) -> (
    Result<RegistryHeadWitnessReceipt, ArtifactStorageError>,
    ArtifactOwnerStageSampleV1,
) {
    measure_stage(
        ArtifactOwnerStageV1::CurrentHeadSwitch,
        0,
        1,
        || write_registry_head_witness_beneath(root, relative, witness, requirement, binding),
    )
}

pub fn measure_owner_open(
    config: LearningArtifactOwnerServiceConfigV1,
) -> (
    Result<LearningArtifactOwnerService, LearningArtifactOwnerServiceError>,
    ArtifactOwnerStageSampleV1,
) {
    measure_stage(
        ArtifactOwnerStageV1::StartupRecoveryScan,
        0,
        0,
        || LearningArtifactOwnerService::open(config),
    )
}

pub fn measure_pinned_load(
    snapshot_file: File,
    payload_file: File,
    expected: PinnedCandidateSpec,
) -> (
    Result<LoadedPinnedCandidate, PinnedCandidateLoadError>,
    ArtifactOwnerStageSampleV1,
) {
    let bytes = expected.manifest.encoded_size_bytes;
    measure_stage(
        ArtifactOwnerStageV1::PinnedLoad,
        bytes,
        u64::try_from(expected.registry_receipt.records).unwrap_or(u64::MAX),
        || load_pinned_candidate(snapshot_file, payload_file, expected),
    )
}

pub fn measure_checkpoint<T>(
    bytes: u64,
    operation: impl FnOnce() -> Result<T, ArtifactOwnerHostError>,
) -> (Result<T, ArtifactOwnerHostError>, ArtifactOwnerStageSampleV1) {
    measure_stage(ArtifactOwnerStageV1::CheckpointSync, bytes, 1, operation)
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stage_summary_separates_failure_and_overflow_bucket() {
        let mut summary = ArtifactOwnerStageSummaryV1::default();
        summary.observe(ArtifactOwnerStageSampleV1 {
            stage: ArtifactOwnerStageV1::RequestTotal,
            elapsed_micros: 251_000,
            bytes: 0,
            records: 0,
            success: false,
        });
        assert_eq!(summary.samples, 1);
        assert_eq!(summary.failures, 1);
        assert_eq!(summary.buckets[7], 1);
    }

    #[test]
    fn measured_failure_is_not_relabelled_success() {
        let (result, sample) = measure_stage(
            ArtifactOwnerStageV1::CheckpointSync,
            3,
            1,
            || -> Result<(), &'static str> { Err("cut") },
        );
        assert_eq!(result, Err("cut"));
        assert!(!sample.success);
        assert_eq!(sample.bytes, 3);
    }
}

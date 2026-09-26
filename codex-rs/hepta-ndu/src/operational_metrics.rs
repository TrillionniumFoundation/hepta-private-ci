//! Bounded operational observations and backup/restore evidence for utility.ndu.
//!
//! These types carry metrics and drill evidence only. They grant no mutation,
//! activation, promotion, release or external-effect authority. An off-host
//! destination, encryption profile and object version must be supplied and
//! independently controlled by the deployment environment.

use std::error::Error as StdError;
use std::fmt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const UNSET_GAUGE: u64 = u64::MAX;
const MAX_RETENTION_COPIES: u16 = 1024;
const MAX_BACKUP_AGE_SECONDS: u64 = 366 * 24 * 60 * 60;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduOperationalMetricSnapshotV1 {
    pub evaluation_count: u64,
    pub evaluation_latency_micros_total: u64,
    pub evaluation_latency_micros_max: u64,
    pub convergence_runs: u64,
    pub convergence_iterations: u64,
    pub convergence_exhaustions: u64,
    pub candidate_rejections: u64,
    pub candidate_quarantines: u64,
    pub store_busy: u64,
    pub store_indeterminate: u64,
    pub reopen_failures: u64,
    pub restore_failures: u64,
    pub journal_bytes: Option<u64>,
    pub backup_age_seconds: Option<u64>,
}

#[derive(Debug)]
pub struct NduOperationalMetricsV1 {
    evaluation_count: AtomicU64,
    evaluation_latency_micros_total: AtomicU64,
    evaluation_latency_micros_max: AtomicU64,
    convergence_runs: AtomicU64,
    convergence_iterations: AtomicU64,
    convergence_exhaustions: AtomicU64,
    candidate_rejections: AtomicU64,
    candidate_quarantines: AtomicU64,
    store_busy: AtomicU64,
    store_indeterminate: AtomicU64,
    reopen_failures: AtomicU64,
    restore_failures: AtomicU64,
    journal_bytes: AtomicU64,
    backup_age_seconds: AtomicU64,
}

impl Default for NduOperationalMetricsV1 {
    fn default() -> Self {
        Self {
            evaluation_count: AtomicU64::new(0),
            evaluation_latency_micros_total: AtomicU64::new(0),
            evaluation_latency_micros_max: AtomicU64::new(0),
            convergence_runs: AtomicU64::new(0),
            convergence_iterations: AtomicU64::new(0),
            convergence_exhaustions: AtomicU64::new(0),
            candidate_rejections: AtomicU64::new(0),
            candidate_quarantines: AtomicU64::new(0),
            store_busy: AtomicU64::new(0),
            store_indeterminate: AtomicU64::new(0),
            reopen_failures: AtomicU64::new(0),
            restore_failures: AtomicU64::new(0),
            journal_bytes: AtomicU64::new(UNSET_GAUGE),
            backup_age_seconds: AtomicU64::new(UNSET_GAUGE),
        }
    }
}

impl NduOperationalMetricsV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn record_evaluation(&self, elapsed: Duration) {
        let micros = u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX);
        saturating_add(&self.evaluation_count, 1);
        saturating_add(&self.evaluation_latency_micros_total, micros);
        self.evaluation_latency_micros_max
            .fetch_max(micros, Ordering::Relaxed);
    }

    pub fn record_convergence(&self, iterations: u32) {
        saturating_add(&self.convergence_runs, 1);
        saturating_add(&self.convergence_iterations, u64::from(iterations));
    }

    pub fn record_convergence_exhaustion(&self) {
        saturating_add(&self.convergence_runs, 1);
        saturating_add(&self.convergence_exhaustions, 1);
    }

    pub fn record_candidate_rejections(&self, count: usize) {
        saturating_add(
            &self.candidate_rejections,
            u64::try_from(count).unwrap_or(u64::MAX),
        );
    }

    pub fn record_candidate_quarantines(&self, count: usize) {
        saturating_add(
            &self.candidate_quarantines,
            u64::try_from(count).unwrap_or(u64::MAX),
        );
    }

    pub fn record_store_busy(&self) {
        saturating_add(&self.store_busy, 1);
    }

    pub fn record_store_indeterminate(&self) {
        saturating_add(&self.store_indeterminate, 1);
    }

    pub fn record_reopen_failure(&self) {
        saturating_add(&self.reopen_failures, 1);
    }

    pub fn record_restore_failure(&self) {
        saturating_add(&self.restore_failures, 1);
    }

    pub fn set_journal_bytes(&self, bytes: u64) {
        self.journal_bytes.store(bytes, Ordering::Relaxed);
    }

    pub fn set_backup_age_seconds(&self, seconds: u64) {
        self.backup_age_seconds.store(seconds, Ordering::Relaxed);
    }

    #[must_use]
    pub fn snapshot(&self) -> NduOperationalMetricSnapshotV1 {
        NduOperationalMetricSnapshotV1 {
            evaluation_count: self.evaluation_count.load(Ordering::Relaxed),
            evaluation_latency_micros_total: self
                .evaluation_latency_micros_total
                .load(Ordering::Relaxed),
            evaluation_latency_micros_max: self
                .evaluation_latency_micros_max
                .load(Ordering::Relaxed),
            convergence_runs: self.convergence_runs.load(Ordering::Relaxed),
            convergence_iterations: self.convergence_iterations.load(Ordering::Relaxed),
            convergence_exhaustions: self.convergence_exhaustions.load(Ordering::Relaxed),
            candidate_rejections: self.candidate_rejections.load(Ordering::Relaxed),
            candidate_quarantines: self.candidate_quarantines.load(Ordering::Relaxed),
            store_busy: self.store_busy.load(Ordering::Relaxed),
            store_indeterminate: self.store_indeterminate.load(Ordering::Relaxed),
            reopen_failures: self.reopen_failures.load(Ordering::Relaxed),
            restore_failures: self.restore_failures.load(Ordering::Relaxed),
            journal_bytes: gauge(&self.journal_bytes),
            backup_age_seconds: gauge(&self.backup_age_seconds),
        }
    }
}

fn saturating_add(counter: &AtomicU64, value: u64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
        Some(current.saturating_add(value))
    });
}

fn gauge(value: &AtomicU64) -> Option<u64> {
    match value.load(Ordering::Relaxed) {
        UNSET_GAUGE => None,
        measured => Some(measured),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduBackupPolicyV1 {
    pub policy_id: StableId,
    pub revision: u64,
    pub minimum_copies: u16,
    pub retention_copies: u16,
    pub max_backup_age_seconds: u64,
    pub off_host_destination_digest: Digest32,
    pub encryption_profile_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduRestoreDrillReceiptV1 {
    pub policy_id: StableId,
    pub policy_revision: u64,
    pub source_journal_head_digest: Digest32,
    pub backup_digest: Digest32,
    pub off_host_object_version_digest: Digest32,
    pub restored_journal_head_digest: Digest32,
    pub operator_identity_digest: Digest32,
    pub target_host_digest: Digest32,
    pub backup_created_at_unix_seconds: u64,
    pub started_at_unix_seconds: u64,
    pub completed_at_unix_seconds: u64,
    pub backup_bytes: u64,
    pub restored_record_count: u32,
    pub passed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduOperationsError {
    InvalidPolicy(&'static str),
    InvalidReceipt(&'static str),
    BackupExpired,
    RestoreHeadMismatch,
    DrillFailed,
}

impl fmt::Display for NduOperationsError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduOperationsError {}

pub fn validate_backup_policy_v1(policy: &NduBackupPolicyV1) -> Result<(), NduOperationsError> {
    if policy.revision == 0 {
        return Err(NduOperationsError::InvalidPolicy("revision"));
    }
    if policy.minimum_copies < 2
        || policy.retention_copies < policy.minimum_copies
        || policy.retention_copies > MAX_RETENTION_COPIES
    {
        return Err(NduOperationsError::InvalidPolicy("retention"));
    }
    if policy.max_backup_age_seconds == 0
        || policy.max_backup_age_seconds > MAX_BACKUP_AGE_SECONDS
    {
        return Err(NduOperationsError::InvalidPolicy("maximum backup age"));
    }
    if policy.off_host_destination_digest.is_zero() {
        return Err(NduOperationsError::InvalidPolicy("off-host destination"));
    }
    if policy.encryption_profile_digest.is_zero() {
        return Err(NduOperationsError::InvalidPolicy("encryption profile"));
    }
    Ok(())
}

pub fn validate_restore_drill_receipt_v1(
    policy: &NduBackupPolicyV1,
    receipt: &NduRestoreDrillReceiptV1,
    now_unix_seconds: u64,
) -> Result<Digest32, NduOperationsError> {
    validate_backup_policy_v1(policy)?;
    if receipt.policy_id != policy.policy_id || receipt.policy_revision != policy.revision {
        return Err(NduOperationsError::InvalidReceipt("policy binding"));
    }
    for (name, digest) in [
        ("source journal head", receipt.source_journal_head_digest),
        ("backup", receipt.backup_digest),
        ("off-host object version", receipt.off_host_object_version_digest),
        ("restored journal head", receipt.restored_journal_head_digest),
        ("operator identity", receipt.operator_identity_digest),
        ("target host", receipt.target_host_digest),
    ] {
        if digest.is_zero() {
            return Err(NduOperationsError::InvalidReceipt(name));
        }
    }
    if receipt.backup_bytes == 0
        || receipt.backup_created_at_unix_seconds > receipt.started_at_unix_seconds
        || receipt.started_at_unix_seconds > receipt.completed_at_unix_seconds
        || receipt.completed_at_unix_seconds > now_unix_seconds
    {
        return Err(NduOperationsError::InvalidReceipt("time or size envelope"));
    }
    if now_unix_seconds.saturating_sub(receipt.backup_created_at_unix_seconds)
        > policy.max_backup_age_seconds
    {
        return Err(NduOperationsError::BackupExpired);
    }
    if receipt.source_journal_head_digest != receipt.restored_journal_head_digest {
        return Err(NduOperationsError::RestoreHeadMismatch);
    }
    if !receipt.passed {
        return Err(NduOperationsError::DrillFailed);
    }

    let policy_revision = receipt.policy_revision.to_be_bytes();
    let backup_created = receipt.backup_created_at_unix_seconds.to_be_bytes();
    let started = receipt.started_at_unix_seconds.to_be_bytes();
    let completed = receipt.completed_at_unix_seconds.to_be_bytes();
    let backup_bytes = receipt.backup_bytes.to_be_bytes();
    let restored_records = receipt.restored_record_count.to_be_bytes();
    Ok(Digest32::of_parts(&[
        b"hepta.ndu.restore-drill-receipt.v1\0",
        receipt.policy_id.as_str().as_bytes(),
        b"\0",
        &policy_revision,
        receipt.source_journal_head_digest.as_array(),
        receipt.backup_digest.as_array(),
        receipt.off_host_object_version_digest.as_array(),
        receipt.restored_journal_head_digest.as_array(),
        receipt.operator_identity_digest.as_array(),
        receipt.target_host_digest.as_array(),
        &backup_created,
        &started,
        &completed,
        &backup_bytes,
        &restored_records,
        &[u8::from(receipt.passed)],
    ]))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        match StableId::new(value) {
            Ok(value) => value,
            Err(error) => panic!("invalid test stable ID {value}: {error}"),
        }
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn operational_metrics_cover_required_signals() {
        let metrics = NduOperationalMetricsV1::new();
        metrics.record_evaluation(Duration::from_micros(17));
        metrics.record_evaluation(Duration::from_micros(29));
        metrics.record_convergence(7);
        metrics.record_convergence_exhaustion();
        metrics.record_candidate_rejections(3);
        metrics.record_candidate_quarantines(2);
        metrics.record_store_busy();
        metrics.record_store_indeterminate();
        metrics.record_reopen_failure();
        metrics.record_restore_failure();
        metrics.set_journal_bytes(4096);
        metrics.set_backup_age_seconds(60);

        assert_eq!(
            metrics.snapshot(),
            NduOperationalMetricSnapshotV1 {
                evaluation_count: 2,
                evaluation_latency_micros_total: 46,
                evaluation_latency_micros_max: 29,
                convergence_runs: 2,
                convergence_iterations: 7,
                convergence_exhaustions: 1,
                candidate_rejections: 3,
                candidate_quarantines: 2,
                store_busy: 1,
                store_indeterminate: 1,
                reopen_failures: 1,
                restore_failures: 1,
                journal_bytes: Some(4096),
                backup_age_seconds: Some(60),
            }
        );
    }

    #[test]
    fn backup_policy_and_restore_drill_are_bounded_and_fail_closed() {
        let policy = NduBackupPolicyV1 {
            policy_id: id("ndu-backup-policy-v1"),
            revision: 1,
            minimum_copies: 2,
            retention_copies: 7,
            max_backup_age_seconds: 3600,
            off_host_destination_digest: digest("off-host-destination"),
            encryption_profile_digest: digest("encryption-profile"),
        };
        let mut receipt = NduRestoreDrillReceiptV1 {
            policy_id: policy.policy_id.clone(),
            policy_revision: 1,
            source_journal_head_digest: digest("journal-head"),
            backup_digest: digest("backup"),
            off_host_object_version_digest: digest("object-version"),
            restored_journal_head_digest: digest("journal-head"),
            operator_identity_digest: digest("operator"),
            target_host_digest: digest("target-host"),
            backup_created_at_unix_seconds: 100,
            started_at_unix_seconds: 120,
            completed_at_unix_seconds: 130,
            backup_bytes: 4096,
            restored_record_count: 8,
            passed: true,
        };
        let receipt_digest = validate_restore_drill_receipt_v1(&policy, &receipt, 140)
            .unwrap_or_else(|error| panic!("valid restore drill rejected: {error}"));
        assert!(!receipt_digest.is_zero());

        receipt.restored_journal_head_digest = digest("different-head");
        assert_eq!(
            validate_restore_drill_receipt_v1(&policy, &receipt, 140),
            Err(NduOperationsError::RestoreHeadMismatch)
        );
        receipt.restored_journal_head_digest = receipt.source_journal_head_digest;
        assert_eq!(
            validate_restore_drill_receipt_v1(&policy, &receipt, 4000),
            Err(NduOperationsError::BackupExpired)
        );
    }
}

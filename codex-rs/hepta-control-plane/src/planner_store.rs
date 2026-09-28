//! Fail-closed lifecycle wrapper for the planner store.
//!
//! The frame codec, lock, checkpoint and backup implementation remains in
//! `planner_store_core.rs`. This owner wrapper turns every mutation with an
//! uncertain durability boundary into a permanently poisoned handle. Once
//! poisoned, no further write/checkpoint/compaction/backup operation is
//! accepted; the caller must drop and reopen from the verified log.

use std::fs;
use std::io::ErrorKind;
use std::path::Path;

use codex_hepta_types::Digest32;

#[path = "planner_store_core.rs"]
mod core;

pub use core::PlannerStoreCheckpointV1;
pub use core::PlannerStoreConfigV1;
pub use core::PlannerStoreError;
pub use core::PlannerStoreFailpointV1;
pub use core::PlannerStoreRecordKindV1;
pub use core::PlannerStoreRecordV1;

const LOG_NAME: &str = "planner-store.v1.log";
const FRAME_FIXED_BYTES: u64 = 8 + 2 + 1 + 8 + 32 + 32 + 4 + 32;
const MAX_TOTAL_STORE_BYTES: u64 = 256 * 1024 * 1024;
const RECOVERY_REQUIRED: &str = "planner store recovery required; drop and reopen";

pub struct PlannerStoreV1 {
    inner: core::PlannerStoreV1,
    recovery_required: bool,
}

impl PlannerStoreV1 {
    pub fn open(
        root: impl AsRef<Path>,
        config: PlannerStoreConfigV1,
    ) -> Result<Self, PlannerStoreError> {
        let root = root.as_ref();
        preflight_log_size(root)?;
        Ok(Self {
            inner: core::PlannerStoreV1::open(root, config)?,
            recovery_required: false,
        })
    }

    #[must_use]
    pub fn records(&self) -> &[PlannerStoreRecordV1] {
        self.inner.records()
    }

    #[must_use]
    pub const fn recovery_required(&self) -> bool {
        self.recovery_required
    }

    #[must_use]
    pub fn schema_version(&self) -> u16 {
        self.inner.schema_version()
    }

    pub fn set_failpoint(&mut self, failpoint: Option<PlannerStoreFailpointV1>) {
        self.inner.set_failpoint(failpoint);
    }

    pub fn append(
        &mut self,
        kind: PlannerStoreRecordKindV1,
        operation_identity_digest: Digest32,
        payload_digest: Digest32,
        envelope: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        self.ensure_healthy()?;
        let identity_exists = self
            .inner
            .records()
            .iter()
            .any(|record| record.operation_identity_digest == operation_identity_digest);
        if !identity_exists {
            let projected = current_store_bytes(self.inner.records())?
                .checked_add(FRAME_FIXED_BYTES)
                .and_then(|value| value.checked_add(u64::try_from(envelope.len()).ok()?))
                .ok_or(PlannerStoreError::RecordLimitExceeded)?;
            if projected > MAX_TOTAL_STORE_BYTES {
                return Err(PlannerStoreError::RecordLimitExceeded);
            }
        }
        let result = self
            .inner
            .append(kind, operation_identity_digest, payload_digest, envelope);
        self.finish_mutation(result, MutationBoundary::Append)
    }

    pub fn checkpoint(
        &mut self,
        external_anchor_digest: Digest32,
    ) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
        self.ensure_healthy()?;
        let result = self.inner.checkpoint(external_anchor_digest);
        self.finish_mutation(result, MutationBoundary::Checkpoint)
    }

    pub fn verify_checkpoint(
        &self,
        expected_anchor_digest: Digest32,
    ) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
        self.inner.verify_checkpoint(expected_anchor_digest)
    }

    pub fn compact(&mut self, retain_last: usize) -> Result<(), PlannerStoreError> {
        self.ensure_healthy()?;
        let result = self.inner.compact(retain_last);
        self.finish_mutation(result, MutationBoundary::Compaction)
    }

    pub fn backup_to(
        &mut self,
        destination: impl AsRef<Path>,
    ) -> Result<(), PlannerStoreError> {
        self.ensure_healthy()?;
        let result = self.inner.backup_to(destination);
        self.finish_mutation(result, MutationBoundary::Backup)
    }

    pub fn restore_from_backup(
        backup: impl AsRef<Path>,
        destination: impl AsRef<Path>,
        config: PlannerStoreConfigV1,
    ) -> Result<Self, PlannerStoreError> {
        let backup = backup.as_ref();
        preflight_log_size(backup)?;
        Ok(Self {
            inner: core::PlannerStoreV1::restore_from_backup(backup, destination, config)?,
            recovery_required: false,
        })
    }

    pub fn validate_migration(from: u16, to: u16) -> Result<(), PlannerStoreError> {
        core::PlannerStoreV1::validate_migration(from, to)
    }

    fn ensure_healthy(&self) -> Result<(), PlannerStoreError> {
        if self.recovery_required {
            return Err(PlannerStoreError::Io(RECOVERY_REQUIRED.to_string()));
        }
        Ok(())
    }

    fn finish_mutation<T>(
        &mut self,
        result: Result<T, PlannerStoreError>,
        boundary: MutationBoundary,
    ) -> Result<T, PlannerStoreError> {
        if let Err(error) = &result {
            if mutation_may_be_uncertain(error, boundary) {
                self.recovery_required = true;
            }
        }
        result
    }
}

fn preflight_log_size(root: &Path) -> Result<(), PlannerStoreError> {
    match fs::metadata(root.join(LOG_NAME)) {
        Ok(metadata) if metadata.len() > MAX_TOTAL_STORE_BYTES => {
            Err(PlannerStoreError::RecordLimitExceeded)
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn current_store_bytes(records: &[PlannerStoreRecordV1]) -> Result<u64, PlannerStoreError> {
    records.iter().try_fold(0_u64, |total, record| {
        let envelope = u64::try_from(record.envelope.len())
            .map_err(|_| PlannerStoreError::RecordLimitExceeded)?;
        total
            .checked_add(FRAME_FIXED_BYTES)
            .and_then(|value| value.checked_add(envelope))
            .ok_or(PlannerStoreError::RecordLimitExceeded)
    })
}

#[derive(Clone, Copy)]
enum MutationBoundary {
    Append,
    Checkpoint,
    Compaction,
    Backup,
}

fn mutation_may_be_uncertain(
    error: &PlannerStoreError,
    boundary: MutationBoundary,
) -> bool {
    match error {
        // An I/O error does not reliably reveal whether the kernel or device
        // accepted a prefix. Poisoning on all mutation I/O failures is stricter
        // than necessary, but never permits a potentially divergent handle to
        // continue.
        PlannerStoreError::Io(_) => true,
        PlannerStoreError::Failpoint(point) => match (boundary, point) {
            (
                MutationBoundary::Append,
                PlannerStoreFailpointV1::AfterFrameWriteBeforeSync
                | PlannerStoreFailpointV1::AfterLogSyncBeforePublish,
            )
            | (
                MutationBoundary::Checkpoint,
                PlannerStoreFailpointV1::AfterCheckpointRenameBeforeDirectorySync,
            )
            | (
                MutationBoundary::Compaction,
                PlannerStoreFailpointV1::AfterCompactionRenameBeforeDirectorySync,
            ) => true,
            _ => false,
        },
        _ => false,
    }
}

#[cfg(test)]
mod hardening_tests {
    use std::fs::File;

    use tempfile::tempdir;

    use super::*;

    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }

    #[test]
    fn uncertain_append_poison_is_enforced_by_the_handle() {
        let directory = tempdir().unwrap();
        let mut store = PlannerStoreV1::open(
            directory.path(),
            PlannerStoreConfigV1::default(),
        )
        .unwrap();
        store.set_failpoint(Some(
            PlannerStoreFailpointV1::AfterLogSyncBeforePublish,
        ));
        let first = store.append(
            PlannerStoreRecordKindV1::Decision,
            digest("operation-one"),
            digest("payload-one"),
            b"one",
        );
        assert!(matches!(first, Err(PlannerStoreError::Failpoint(_))));
        assert!(store.recovery_required());

        let second = store.append(
            PlannerStoreRecordKindV1::Decision,
            digest("operation-two"),
            digest("payload-two"),
            b"two",
        );
        assert!(matches!(second, Err(PlannerStoreError::Io(message)) if message.contains("recovery required")));
    }

    #[test]
    fn prewrite_validation_error_does_not_poison_the_handle() {
        let directory = tempdir().unwrap();
        let mut store = PlannerStoreV1::open(
            directory.path(),
            PlannerStoreConfigV1::default(),
        )
        .unwrap();
        let error = store.append(
            PlannerStoreRecordKindV1::Decision,
            Digest32::ZERO,
            digest("payload"),
            b"invalid",
        );
        assert!(matches!(error, Err(PlannerStoreError::EmptyDigest(_))));
        assert!(!store.recovery_required());
    }

    #[test]
    fn oversized_existing_log_is_rejected_before_read_to_end() {
        let directory = tempdir().unwrap();
        let log = File::create(directory.path().join(LOG_NAME)).unwrap();
        log.set_len(MAX_TOTAL_STORE_BYTES + 1).unwrap();
        drop(log);

        let result = PlannerStoreV1::open(
            directory.path(),
            PlannerStoreConfigV1::default(),
        );
        assert!(matches!(result, Err(PlannerStoreError::RecordLimitExceeded)));
    }
}

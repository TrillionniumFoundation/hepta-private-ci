//! Fail-closed lifecycle wrapper for the planner store.
//!
//! The frame codec, checkpoint and backup implementation remains in
//! `planner_store_core.rs`. This public owner wrapper adds an operating-system
//! file lock across open, backup and restore; rejects complete frame headers
//! with missing declared bodies; preserves semantic evidence during
//! compaction; and turns every mutation with an uncertain durability boundary
//! into a permanently poisoned handle. Once poisoned, no further authoritative
//! observation, write, checkpoint, compaction or backup operation is accepted;
//! the caller must drop and reopen from the verified log.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

#[path = "planner_store_core.rs"]
mod core;

pub use core::PlannerStoreCheckpointV1;
pub use core::PlannerStoreConfigV1;
pub use core::PlannerStoreError;
pub use core::PlannerStoreFailpointV1;
pub use core::PlannerStoreRecordKindV1;
pub use core::PlannerStoreRecordV1;

const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
const SCHEMA_VERSION: u16 = 1;
const LOG_NAME: &str = "planner-store.v1.log";
const OWNER_LOCK_NAME: &str = "planner-store.owner.lock";
const FRAME_PREFIX_BYTES: usize = 8 + 2 + 1 + 8 + 32 + 32 + 4;
const FRAME_DIGEST_BYTES: u64 = 32;
const FRAME_FIXED_BYTES: u64 = 8 + 2 + 1 + 8 + 32 + 32 + 4 + 32;
const MAX_TOTAL_STORE_BYTES: u64 = 256 * 1024 * 1024;
const RECOVERY_REQUIRED: &str = "planner store recovery required; drop and reopen";
const DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1: &[u8] =
    b"hepta.control.execution-dispatch-claim-envelope.v1";
const DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2: &[u8] =
    b"hepta.control.execution-dispatch-claim-envelope.v2";
const TERMINAL_ENVELOPE_DOMAIN_V1: &[u8] = b"hepta.control.execution-terminal-envelope.v1";

pub struct PlannerStoreV1 {
    root: PathBuf,
    _owner_lock: PlannerOwnerLockV1,
    inner: core::PlannerStoreV1,
    recovery_required: bool,
}

impl PlannerStoreV1 {
    pub fn open(
        root: impl AsRef<Path>,
        config: PlannerStoreConfigV1,
    ) -> Result<Self, PlannerStoreError> {
        let root = root.as_ref();
        fs::create_dir_all(root)?;
        let owner_lock = PlannerOwnerLockV1::acquire_exclusive(root)?;
        preflight_log(root, config)?;
        Ok(Self {
            root: root.to_path_buf(),
            _owner_lock: owner_lock,
            inner: core::PlannerStoreV1::open(root, config)?,
            recovery_required: false,
        })
    }

    /// Return the in-memory diagnostic projection.
    ///
    /// Callers that use records to authorize, dispatch or reconcile must first
    /// call `ensure_healthy`. A poisoned owner deliberately retains its last
    /// published projection for diagnosis, but that projection is not an
    /// authoritative statement about the durable tail.
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

    /// Append a generic planner record.
    ///
    /// Durable dispatch claims and execution observations are reserved for the
    /// typed execution state machine. Accepting those record kinds or canonical
    /// envelope domains through this generic entry would permit callers to
    /// bypass claim, grant and terminal-transition validation.
    pub fn append(
        &mut self,
        kind: PlannerStoreRecordKindV1,
        operation_identity_digest: Digest32,
        payload_digest: Digest32,
        envelope: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        if is_reserved_execution_record(kind, envelope) {
            return Err(PlannerStoreError::InvalidConfiguration);
        }
        self.append_owner_record(kind, operation_identity_digest, payload_digest, envelope)
    }

    /// Crate-local write port used only after the execution state machine has
    /// validated the durable claim or terminal transition.
    pub(crate) fn append_execution_record(
        &mut self,
        kind: PlannerStoreRecordKindV1,
        operation_identity_digest: Digest32,
        payload_digest: Digest32,
        envelope: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        if !is_reserved_execution_record(kind, envelope) {
            return Err(PlannerStoreError::InvalidConfiguration);
        }
        self.append_owner_record(kind, operation_identity_digest, payload_digest, envelope)
    }

    fn append_owner_record(
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
        self.ensure_healthy()?;
        self.inner.verify_checkpoint(expected_anchor_digest)
    }

    /// Compact only a prefix made exclusively of superseded snapshots.
    ///
    /// `planner_store_core` implements the byte rewrite. The public owner keeps
    /// every non-snapshot operation identity and also keeps the latest snapshot
    /// immediately preceding the first semantic record. Consequently a small
    /// `retain_last` request is a lower bound, never permission to discard a
    /// dispatch claim, decision, revocation or terminal observation.
    pub fn compact(&mut self, retain_last: usize) -> Result<(), PlannerStoreError> {
        self.ensure_healthy()?;
        let retain_last = semantic_retain_count(self.inner.records(), retain_last);
        let result = self.inner.compact(retain_last);
        self.finish_mutation(result, MutationBoundary::Compaction)
    }

    pub fn backup_to(&mut self, destination: impl AsRef<Path>) -> Result<(), PlannerStoreError> {
        self.ensure_healthy()?;
        let destination = destination.as_ref();
        fs::create_dir_all(destination)?;
        if same_directory(&self.root, destination)? {
            return Err(PlannerStoreError::InvalidConfiguration);
        }
        let _destination_lock = PlannerOwnerLockV1::acquire_exclusive(destination)?;
        let result = self.inner.backup_to(destination);
        self.finish_mutation(result, MutationBoundary::Backup)
    }

    pub fn restore_from_backup(
        backup: impl AsRef<Path>,
        destination: impl AsRef<Path>,
        config: PlannerStoreConfigV1,
    ) -> Result<Self, PlannerStoreError> {
        let backup = backup.as_ref();
        let destination = destination.as_ref();
        if same_directory_if_present(backup, destination)? {
            return Err(PlannerStoreError::InvalidConfiguration);
        }
        let _backup_lock = PlannerOwnerLockV1::acquire_shared(backup)?;
        preflight_log(backup, config)?;
        fs::create_dir_all(destination)?;
        let owner_lock = PlannerOwnerLockV1::acquire_exclusive(destination)?;
        let inner = core::PlannerStoreV1::restore_from_backup(backup, destination, config)?;
        Ok(Self {
            root: destination.to_path_buf(),
            _owner_lock: owner_lock,
            inner,
            recovery_required: false,
        })
    }

    pub fn validate_migration(from: u16, to: u16) -> Result<(), PlannerStoreError> {
        core::PlannerStoreV1::validate_migration(from, to)
    }

    pub(crate) fn ensure_healthy(&self) -> Result<(), PlannerStoreError> {
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

struct PlannerOwnerLockV1 {
    _file: File,
}

impl PlannerOwnerLockV1 {
    fn acquire_exclusive(root: &Path) -> Result<Self, PlannerStoreError> {
        Self::acquire(root, true)
    }

    fn acquire_shared(root: &Path) -> Result<Self, PlannerStoreError> {
        Self::acquire(root, false)
    }

    fn acquire(root: &Path, exclusive: bool) -> Result<Self, PlannerStoreError> {
        fs::create_dir_all(root)?;
        let path = root.join(OWNER_LOCK_NAME);
        let mut file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .truncate(false)
            .open(path)?;
        let locked = if exclusive {
            file.try_lock()
        } else {
            file.try_lock_shared()
        };
        match locked {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(PlannerStoreError::Locked),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }
        if exclusive {
            file.set_len(0)?;
            file.seek(SeekFrom::Start(0))?;
            writeln!(file, "pid={}", std::process::id())?;
            file.sync_data()?;
        }
        Ok(Self { _file: file })
    }
}

fn preflight_log(root: &Path, config: PlannerStoreConfigV1) -> Result<(), PlannerStoreError> {
    if config.maximum_records == 0 || config.maximum_envelope_bytes == 0 {
        return Err(PlannerStoreError::InvalidConfiguration);
    }
    let path = root.join(LOG_NAME);
    let metadata = match fs::metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    if metadata.len() > MAX_TOTAL_STORE_BYTES {
        return Err(PlannerStoreError::RecordLimitExceeded);
    }

    let mut log = File::open(path)?;
    let mut offset = 0_u64;
    let mut frames = 0_usize;
    while offset < metadata.len() {
        let remaining = metadata.len() - offset;
        if remaining < u64::try_from(FRAME_PREFIX_BYTES).unwrap_or(u64::MAX) {
            // An incomplete fixed prefix cannot encode a trusted length. The
            // core may truncate this final fragment to the last verified frame.
            return Ok(());
        }

        let mut prefix = [0_u8; FRAME_PREFIX_BYTES];
        log.read_exact(&mut prefix)?;
        if &prefix[..8] != STORE_MAGIC {
            return Err(PlannerStoreError::CorruptHeader);
        }
        let version = u16::from_be_bytes([prefix[8], prefix[9]]);
        if version != SCHEMA_VERSION {
            return Err(PlannerStoreError::UnsupportedSchemaVersion(version));
        }
        let envelope_length = u64::from(u32::from_be_bytes(
            prefix[FRAME_PREFIX_BYTES - 4..]
                .try_into()
                .map_err(|_| PlannerStoreError::Truncated)?,
        ));
        if envelope_length > u64::try_from(config.maximum_envelope_bytes).unwrap_or(u64::MAX) {
            return Err(PlannerStoreError::EnvelopeTooLarge {
                actual: usize::try_from(envelope_length).unwrap_or(usize::MAX),
                maximum: config.maximum_envelope_bytes,
            });
        }
        let frame_length = u64::try_from(FRAME_PREFIX_BYTES)
            .unwrap_or(u64::MAX)
            .checked_add(envelope_length)
            .and_then(|value| value.checked_add(FRAME_DIGEST_BYTES))
            .ok_or(PlannerStoreError::Truncated)?;
        if remaining < frame_length {
            // Once the complete prefix and declared length are durable, silently
            // treating a missing body as a crash tail would also hide length-field
            // corruption. Fail closed and require explicit recovery evidence.
            return Err(PlannerStoreError::Truncated);
        }
        let skip = i64::try_from(envelope_length + FRAME_DIGEST_BYTES)
            .map_err(|_| PlannerStoreError::RecordLimitExceeded)?;
        log.seek(SeekFrom::Current(skip))?;
        offset = offset
            .checked_add(frame_length)
            .ok_or(PlannerStoreError::RecordLimitExceeded)?;
        frames = frames
            .checked_add(1)
            .ok_or(PlannerStoreError::RecordLimitExceeded)?;
        if frames > config.maximum_records {
            return Err(PlannerStoreError::RecordLimitExceeded);
        }
    }
    Ok(())
}

fn is_reserved_execution_record(kind: PlannerStoreRecordKindV1, envelope: &[u8]) -> bool {
    matches!(
        kind,
        PlannerStoreRecordKindV1::TerminalReceipt | PlannerStoreRecordKindV1::Reconciliation
    ) || envelope.starts_with(DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1)
        || envelope.starts_with(DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2)
        || envelope.starts_with(TERMINAL_ENVELOPE_DOMAIN_V1)
}

fn semantic_retain_count(records: &[PlannerStoreRecordV1], requested: usize) -> usize {
    if requested == 0 || records.is_empty() || requested >= records.len() {
        return requested;
    }
    let requested_start = records.len().saturating_sub(requested);
    let protected_start = records
        .iter()
        .position(|record| record.kind != PlannerStoreRecordKindV1::Snapshot)
        .map(|first_semantic| {
            records[..=first_semantic]
                .iter()
                .rposition(|record| record.kind == PlannerStoreRecordKindV1::Snapshot)
                .unwrap_or(first_semantic)
        });
    let start = protected_start.map_or(requested_start, |protected| requested_start.min(protected));
    records.len() - start
}

fn same_directory(left: &Path, right: &Path) -> Result<bool, PlannerStoreError> {
    Ok(fs::canonicalize(left)? == fs::canonicalize(right)?)
}

fn same_directory_if_present(left: &Path, right: &Path) -> Result<bool, PlannerStoreError> {
    let left = match fs::canonicalize(left) {
        Ok(path) => path,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    let right = match fs::canonicalize(right) {
        Ok(path) => path,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    Ok(left == right)
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

fn mutation_may_be_uncertain(error: &PlannerStoreError, boundary: MutationBoundary) -> bool {
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
    use tempfile::tempdir;

    use super::*;

    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }

    #[test]
    fn uncertain_append_poison_is_enforced_by_the_handle() {
        let directory = tempdir().unwrap();
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()).unwrap();
        store.set_failpoint(Some(PlannerStoreFailpointV1::AfterLogSyncBeforePublish));
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
        assert!(matches!(
            second,
            Err(PlannerStoreError::Io(message)) if message.contains("recovery required")
        ));
    }

    #[test]
    fn poisoned_handle_cannot_verify_a_stale_checkpoint_projection() {
        let directory = tempdir().unwrap();
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()).unwrap();
        store
            .append(
                PlannerStoreRecordKindV1::Snapshot,
                digest("snapshot-operation"),
                digest("snapshot-payload"),
                b"snapshot",
            )
            .unwrap();
        let anchor = digest("external-anchor");
        store.checkpoint(anchor).unwrap();

        store.set_failpoint(Some(PlannerStoreFailpointV1::AfterLogSyncBeforePublish));
        let failure = store.append(
            PlannerStoreRecordKindV1::Decision,
            digest("decision-operation"),
            digest("decision-payload"),
            b"decision",
        );
        assert!(matches!(failure, Err(PlannerStoreError::Failpoint(_))));
        assert!(store.recovery_required());
        assert!(matches!(
            store.verify_checkpoint(anchor),
            Err(PlannerStoreError::Io(message)) if message.contains("recovery required")
        ));
    }

    #[test]
    fn prewrite_validation_error_does_not_poison_the_handle() {
        let directory = tempdir().unwrap();
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()).unwrap();
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
    fn generic_append_rejects_reserved_execution_records_without_poisoning() {
        let directory = tempdir().unwrap();
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()).unwrap();

        let terminal = store.append(
            PlannerStoreRecordKindV1::TerminalReceipt,
            digest("terminal-operation"),
            digest("terminal-payload"),
            TERMINAL_ENVELOPE_DOMAIN_V1,
        );
        assert!(matches!(
            terminal,
            Err(PlannerStoreError::InvalidConfiguration)
        ));

        let claim = store.append(
            PlannerStoreRecordKindV1::Selection,
            digest("claim-operation"),
            digest("claim-payload"),
            DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2,
        );
        assert!(matches!(
            claim,
            Err(PlannerStoreError::InvalidConfiguration)
        ));
        assert!(store.records().is_empty());
        assert!(!store.recovery_required());
    }

    #[test]
    fn oversized_existing_log_is_rejected_before_read_to_end() {
        let directory = tempdir().unwrap();
        let log = File::create(directory.path().join(LOG_NAME)).unwrap();
        log.set_len(MAX_TOTAL_STORE_BYTES + 1).unwrap();
        drop(log);

        let result = PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default());
        assert!(matches!(
            result,
            Err(PlannerStoreError::RecordLimitExceeded)
        ));
    }

    #[test]
    fn public_owner_lock_excludes_a_second_open() {
        let directory = tempdir().unwrap();
        let first =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()).unwrap();
        let second = PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default());
        assert!(matches!(second, Err(PlannerStoreError::Locked)));
        drop(first);
        PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()).unwrap();
    }

    #[test]
    fn complete_frame_prefix_with_missing_body_fails_closed() {
        let directory = tempdir().unwrap();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(STORE_MAGIC);
        bytes.extend_from_slice(&SCHEMA_VERSION.to_be_bytes());
        bytes.push(1);
        bytes.extend_from_slice(&1_u64.to_be_bytes());
        bytes.extend_from_slice(digest("operation").as_array());
        bytes.extend_from_slice(digest("payload").as_array());
        bytes.extend_from_slice(&64_u32.to_be_bytes());
        fs::write(directory.path().join(LOG_NAME), bytes).unwrap();

        let result = PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default());
        assert!(matches!(result, Err(PlannerStoreError::Truncated)));
    }

    #[test]
    fn semantic_compaction_preserves_non_snapshot_identity_history() {
        let directory = tempdir().unwrap();
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()).unwrap();
        store
            .append(
                PlannerStoreRecordKindV1::Snapshot,
                digest("snapshot-old"),
                digest("snapshot-old-payload"),
                b"old snapshot",
            )
            .unwrap();
        store
            .append(
                PlannerStoreRecordKindV1::Snapshot,
                digest("snapshot-current"),
                digest("snapshot-current-payload"),
                b"current snapshot",
            )
            .unwrap();
        store
            .append(
                PlannerStoreRecordKindV1::Selection,
                digest("selection"),
                digest("selection-payload"),
                b"generic selection",
            )
            .unwrap();
        store
            .append(
                PlannerStoreRecordKindV1::Revocation,
                digest("revocation"),
                digest("revocation-payload"),
                b"revocation",
            )
            .unwrap();

        store.compact(1).unwrap();
        assert_eq!(store.records().len(), 3);
        assert_eq!(store.records()[0].kind, PlannerStoreRecordKindV1::Snapshot);
        assert_eq!(store.records()[1].kind, PlannerStoreRecordKindV1::Selection);
        assert_eq!(
            store.records()[2].kind,
            PlannerStoreRecordKindV1::Revocation
        );
    }
}

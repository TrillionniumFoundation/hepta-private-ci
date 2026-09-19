//! Durable single-writer owner for NDU projection state.
//!
//! The in-memory `NduProjectionJournalV1` remains the semantic reducer. This
//! wrapper adds a crash-released OS file lock, append+fsync durability, bounded
//! retention, external anti-rollback acknowledgement, authenticated migration,
//! and checkpoint/restore. It deliberately does not implement an anchor store:
//! the caller must supply an independently durable/trusted witness.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;
use crate::projection_journal::MAX_RECORDS;
use crate::projection_journal::RECORD_BYTES;

const DURABLE_MAGIC: &[u8; 8] = b"HNDUDJ02";
const REFERENCE_MAGIC: &[u8; 8] = b"HNDUPJ01";
const DURABLE_HEADER_BYTES: usize = 8 + 32 + 32;

/// Independently retained minimum acknowledged NDU projection history.
///
/// Sequence zero is the empty store and must carry a zero entry digest.
/// Non-zero anchors bind an exact hash-chain head.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduProjectionDurableAnchorV1 {
    pub sequence: u64,
    pub entry_digest: Digest32,
}

/// External anti-rollback witness. Implementations are expected to persist this
/// outside the projection journal's rollback domain.
///
/// `compare_and_set` may fail ambiguously. The durable writer treats every
/// failure as indeterminate and requires recovery before another mutation.
pub trait NduProjectionAnchorStoreV1: Send + Sync {
    fn current_anchor(&self) -> Result<Option<NduProjectionDurableAnchorV1>, String>;

    fn compare_and_set(
        &self,
        expected: Option<NduProjectionDurableAnchorV1>,
        next: NduProjectionDurableAnchorV1,
    ) -> Result<(), String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionDurableReceiptV1 {
    pub entry: NduProjectionEntryV1,
    pub acknowledged_anchor: NduProjectionDurableAnchorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionCheckpointV1 {
    pub binding_digest: Digest32,
    pub anchor: NduProjectionDurableAnchorV1,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduProjectionDurableError {
    InvalidBinding,
    InvalidLimit,
    InvalidAnchor,
    Busy,
    NotRegular,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    HeaderDigestMismatch,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    StaleExternalAnchor,
    Capacity,
    Corrupt,
    Poisoned,
    AnchorStore(String),
    AnchorUpdateIndeterminate(String),
    Io(io::ErrorKind),
    Semantic(NduProjectionJournalError),
}

impl fmt::Display for NduProjectionDurableError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduProjectionDurableError {}

impl From<io::Error> for NduProjectionDurableError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl From<NduProjectionJournalError> for NduProjectionDurableError {
    fn from(error: NduProjectionJournalError) -> Self {
        Self::Semantic(error)
    }
}

/// Append-only durable owner. The supplied file is the storage engine; path
/// creation and containing-directory durability remain the embedding host's
/// responsibility. Every semantic mutation is fsynced before the independent
/// anchor CAS and is published in memory only after that CAS succeeds.
pub struct NduProjectionDurableJournalV1 {
    file: File,
    core: NduProjectionJournalV1,
    binding_digest: Digest32,
    max_records: usize,
    durable_length: u64,
    acknowledged_anchor: NduProjectionDurableAnchorV1,
    poisoned: bool,
}

impl NduProjectionDurableJournalV1 {
    /// Initialize an empty durable owner. The target file must be empty and the
    /// external anchor store must be uninitialized.
    pub fn create(
        file: File,
        binding_digest: Digest32,
        max_records: usize,
        anchor_store: &impl NduProjectionAnchorStoreV1,
    ) -> Result<Self, NduProjectionDurableError> {
        validate_configuration(binding_digest, max_records)?;
        let mut file = lock_regular(file)?;
        if file.metadata()?.len() != 0 {
            return Err(NduProjectionDurableError::AlreadyInitialized);
        }
        if anchor_store
            .current_anchor()
            .map_err(NduProjectionDurableError::AnchorStore)?
            .is_some()
        {
            return Err(NduProjectionDurableError::StaleExternalAnchor);
        }

        let header = durable_header(binding_digest);
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)?;
        if let Err(error) = file.sync_all() {
            let _ = file.set_len(0);
            let _ = file.sync_all();
            return Err(NduProjectionDurableError::Io(error.kind()));
        }

        let empty_anchor = empty_anchor();
        if let Err(error) = anchor_store.compare_and_set(None, empty_anchor) {
            match anchor_store
                .current_anchor()
                .map_err(NduProjectionDurableError::AnchorStore)?
            {
                Some(current) if current == empty_anchor => {}
                None => {
                    let _ = file.set_len(0);
                    let _ = file.sync_all();
                    return Err(NduProjectionDurableError::AnchorUpdateIndeterminate(
                        error,
                    ));
                }
                Some(_) => {
                    return Err(NduProjectionDurableError::AnchorUpdateIndeterminate(
                        error,
                    ));
                }
            }
        }

        Ok(Self {
            file,
            core: NduProjectionJournalV1::new(),
            binding_digest,
            max_records,
            durable_length: DURABLE_HEADER_BYTES as u64,
            acknowledged_anchor: empty_anchor,
            poisoned: false,
        })
    }

    /// Recover exactly the externally acknowledged prefix. Any complete or
    /// partial local tail beyond that witness is uncommitted and truncated.
    pub fn recover(
        mut file: File,
        binding_digest: Digest32,
        max_records: usize,
        anchor_store: &impl NduProjectionAnchorStoreV1,
    ) -> Result<Self, NduProjectionDurableError> {
        validate_configuration(binding_digest, max_records)?;
        file = lock_regular(file)?;
        let anchor = anchor_store
            .current_anchor()
            .map_err(NduProjectionDurableError::AnchorStore)?
            .ok_or(NduProjectionDurableError::InvalidAnchor)?;

        let mut bytes = Vec::new();
        file.seek(SeekFrom::Start(0))?;
        file.read_to_end(&mut bytes)?;
        let (core, committed_length) =
            parse_acknowledged_prefix(&bytes, binding_digest, max_records, anchor)?;

        let length = u64::try_from(committed_length)
            .map_err(|_| NduProjectionDurableError::Capacity)?;
        if file.metadata()?.len() != length {
            file.set_len(length)
                .and_then(|()| file.sync_all())
                .map_err(|_| NduProjectionDurableError::Corrupt)?;
        }
        file.seek(SeekFrom::Start(length))?;

        Ok(Self {
            file,
            core,
            binding_digest,
            max_records,
            durable_length: length,
            acknowledged_anchor: anchor,
            poisoned: false,
        })
    }

    /// Restore a previously fsynced checkpoint into an empty replacement file.
    /// The independently retained anchor must still match the checkpoint; this
    /// prevents a stale local backup from rolling the owner state backward.
    pub fn restore_checkpoint(
        file: File,
        checkpoint: &NduProjectionCheckpointV1,
        max_records: usize,
        anchor_store: &impl NduProjectionAnchorStoreV1,
    ) -> Result<Self, NduProjectionDurableError> {
        validate_configuration(checkpoint.binding_digest, max_records)?;
        let mut file = lock_regular(file)?;
        if file.metadata()?.len() != 0 {
            return Err(NduProjectionDurableError::AlreadyInitialized);
        }
        let external = anchor_store
            .current_anchor()
            .map_err(NduProjectionDurableError::AnchorStore)?;
        if external != Some(checkpoint.anchor) {
            return Err(NduProjectionDurableError::StaleExternalAnchor);
        }
        let (core, committed_length) = parse_acknowledged_prefix(
            &checkpoint.bytes,
            checkpoint.binding_digest,
            max_records,
            checkpoint.anchor,
        )?;
        if committed_length != checkpoint.bytes.len() {
            return Err(NduProjectionDurableError::Corrupt);
        }

        file.seek(SeekFrom::Start(0))?;
        file.write_all(&checkpoint.bytes)?;
        file.sync_all()
            .map_err(|_| NduProjectionDurableError::Corrupt)?;
        let length = u64::try_from(committed_length)
            .map_err(|_| NduProjectionDurableError::Capacity)?;

        Ok(Self {
            file,
            core,
            binding_digest: checkpoint.binding_digest,
            max_records,
            durable_length: length,
            acknowledged_anchor: checkpoint.anchor,
            poisoned: false,
        })
    }

    /// Migrate a legacy reference snapshot only after an external authority has
    /// already anchored its exact chain head. The local snapshot can never
    /// authenticate itself into production state.
    pub fn migrate_authenticated_reference_snapshot(
        file: File,
        binding_digest: Digest32,
        reference_snapshot: &[u8],
        max_records: usize,
        anchor_store: &impl NduProjectionAnchorStoreV1,
    ) -> Result<Self, NduProjectionDurableError> {
        validate_configuration(binding_digest, max_records)?;
        let journal = NduProjectionJournalV1::reopen(reference_snapshot)?;
        if journal.entries().len() > max_records {
            return Err(NduProjectionDurableError::Capacity);
        }
        let anchor = anchor_for_journal(&journal)?;
        let external = anchor_store
            .current_anchor()
            .map_err(NduProjectionDurableError::AnchorStore)?;
        if external != Some(anchor) {
            return Err(NduProjectionDurableError::StaleExternalAnchor);
        }
        if reference_snapshot.len() < 12 || &reference_snapshot[..8] != REFERENCE_MAGIC {
            return Err(NduProjectionDurableError::Corrupt);
        }

        let mut bytes = durable_header(binding_digest);
        bytes.extend_from_slice(&reference_snapshot[12..]);
        let checkpoint = NduProjectionCheckpointV1 {
            binding_digest,
            anchor,
            bytes,
        };
        Self::restore_checkpoint(file, &checkpoint, max_records, anchor_store)
    }

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
        anchor_store: &impl NduProjectionAnchorStoreV1,
    ) -> Result<NduProjectionDurableReceiptV1, NduProjectionDurableError> {
        self.commit(anchor_store, |journal| {
            journal.append_projection(
                kind,
                identity_digest,
                objective_digest,
                subject_digest,
                payload_digest,
            )
        })
    }

    pub fn select_projection(
        &mut self,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
        anchor_store: &impl NduProjectionAnchorStoreV1,
    ) -> Result<NduProjectionDurableReceiptV1, NduProjectionDurableError> {
        self.commit(anchor_store, |journal| {
            journal.select_projection(
                operation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    pub fn revoke_projection(
        &mut self,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
        anchor_store: &impl NduProjectionAnchorStoreV1,
    ) -> Result<NduProjectionDurableReceiptV1, NduProjectionDurableError> {
        self.commit(anchor_store, |journal| {
            journal.revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    pub fn entries(&self) -> Result<&[NduProjectionEntryV1], NduProjectionDurableError> {
        self.ensure_healthy()?;
        Ok(self.core.entries())
    }

    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<Option<Digest32>, NduProjectionDurableError> {
        self.ensure_healthy()?;
        Ok(self
            .core
            .selected_projection_digest(objective_digest, subject_digest))
    }

    pub fn acknowledged_anchor(
        &self,
    ) -> Result<NduProjectionDurableAnchorV1, NduProjectionDurableError> {
        self.ensure_healthy()?;
        Ok(self.acknowledged_anchor)
    }

    /// Produce a byte-exact backup plus its independently verifiable anchor.
    pub fn checkpoint(
        &mut self,
    ) -> Result<NduProjectionCheckpointV1, NduProjectionDurableError> {
        self.ensure_healthy()?;
        self.file
            .sync_all()
            .map_err(|_| NduProjectionDurableError::Corrupt)?;
        let length = usize::try_from(self.durable_length)
            .map_err(|_| NduProjectionDurableError::Capacity)?;
        let mut bytes = vec![0_u8; length];
        self.file.seek(SeekFrom::Start(0))?;
        self.file.read_exact(&mut bytes)?;
        self.file.seek(SeekFrom::Start(self.durable_length))?;
        Ok(NduProjectionCheckpointV1 {
            binding_digest: self.binding_digest,
            anchor: self.acknowledged_anchor,
            bytes,
        })
    }

    fn commit<F>(
        &mut self,
        anchor_store: &impl NduProjectionAnchorStoreV1,
        prepare: F,
    ) -> Result<NduProjectionDurableReceiptV1, NduProjectionDurableError>
    where
        F: FnOnce(
            &mut NduProjectionJournalV1,
        ) -> Result<NduProjectionEntryV1, NduProjectionJournalError>,
    {
        self.ensure_healthy()?;
        let external = anchor_store
            .current_anchor()
            .map_err(NduProjectionDurableError::AnchorStore)?;
        if external != Some(self.acknowledged_anchor) {
            return Err(NduProjectionDurableError::StaleExternalAnchor);
        }

        let old_len = self.core.entries().len();
        let mut candidate = self.core.clone();
        let entry = prepare(&mut candidate)?;
        let new_len = candidate.entries().len();

        if new_len == old_len {
            return Ok(NduProjectionDurableReceiptV1 {
                entry,
                acknowledged_anchor: self.acknowledged_anchor,
            });
        }
        if new_len != old_len + 1 || new_len > self.max_records {
            return Err(NduProjectionDurableError::Capacity);
        }

        let snapshot = candidate.export_bytes();
        let record_start = 12_usize
            .checked_add(
                old_len
                    .checked_mul(RECORD_BYTES)
                    .ok_or(NduProjectionDurableError::Capacity)?,
            )
            .ok_or(NduProjectionDurableError::Capacity)?;
        let record = snapshot
            .get(record_start..)
            .ok_or(NduProjectionDurableError::Corrupt)?;
        if record.len() != RECORD_BYTES {
            return Err(NduProjectionDurableError::Corrupt);
        }

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(NduProjectionDurableError::Corrupt);
        }
        self.file
            .write_all(record)
            .and_then(|()| self.file.sync_all())
            .map_err(|error| NduProjectionDurableError::Io(error.kind()))?;

        let next_anchor = NduProjectionDurableAnchorV1 {
            sequence: entry.sequence,
            entry_digest: entry.entry_digest,
        };
        if let Err(error) =
            anchor_store.compare_and_set(Some(self.acknowledged_anchor), next_anchor)
        {
            return Err(NduProjectionDurableError::AnchorUpdateIndeterminate(
                error,
            ));
        }

        self.core = candidate;
        self.durable_length = self
            .durable_length
            .checked_add(
                u64::try_from(RECORD_BYTES)
                    .map_err(|_| NduProjectionDurableError::Capacity)?,
            )
            .ok_or(NduProjectionDurableError::Capacity)?;
        self.acknowledged_anchor = next_anchor;
        self.poisoned = false;
        Ok(NduProjectionDurableReceiptV1 {
            entry,
            acknowledged_anchor: next_anchor,
        })
    }

    fn ensure_healthy(&self) -> Result<(), NduProjectionDurableError> {
        if self.poisoned {
            Err(NduProjectionDurableError::Poisoned)
        } else {
            Ok(())
        }
    }
}

fn validate_configuration(
    binding_digest: Digest32,
    max_records: usize,
) -> Result<(), NduProjectionDurableError> {
    if binding_digest.is_zero() {
        return Err(NduProjectionDurableError::InvalidBinding);
    }
    if max_records == 0 || max_records > MAX_RECORDS {
        return Err(NduProjectionDurableError::InvalidLimit);
    }
    Ok(())
}

fn lock_regular(file: File) -> Result<File, NduProjectionDurableError> {
    if !file.metadata()?.is_file() {
        return Err(NduProjectionDurableError::NotRegular);
    }
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(TryLockError::WouldBlock) => Err(NduProjectionDurableError::Busy),
        Err(TryLockError::Error(error)) => Err(NduProjectionDurableError::Io(error.kind())),
    }
}

fn durable_header(binding_digest: Digest32) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(DURABLE_HEADER_BYTES);
    bytes.extend_from_slice(DURABLE_MAGIC);
    bytes.extend_from_slice(binding_digest.as_array());
    let digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(digest.as_array());
    bytes
}

fn empty_anchor() -> NduProjectionDurableAnchorV1 {
    NduProjectionDurableAnchorV1 {
        sequence: 0,
        entry_digest: Digest32::ZERO,
    }
}

fn validate_anchor(anchor: NduProjectionDurableAnchorV1) -> Result<(), NduProjectionDurableError> {
    if (anchor.sequence == 0) != anchor.entry_digest.is_zero() {
        return Err(NduProjectionDurableError::InvalidAnchor);
    }
    Ok(())
}

fn anchor_for_journal(
    journal: &NduProjectionJournalV1,
) -> Result<NduProjectionDurableAnchorV1, NduProjectionDurableError> {
    let Some(last) = journal.entries().last() else {
        return Ok(empty_anchor());
    };
    Ok(NduProjectionDurableAnchorV1 {
        sequence: last.sequence,
        entry_digest: last.entry_digest,
    })
}

fn parse_acknowledged_prefix(
    bytes: &[u8],
    binding_digest: Digest32,
    max_records: usize,
    anchor: NduProjectionDurableAnchorV1,
) -> Result<(NduProjectionJournalV1, usize), NduProjectionDurableError> {
    validate_anchor(anchor)?;
    if bytes.len() < DURABLE_HEADER_BYTES {
        return Err(NduProjectionDurableError::MissingHeader);
    }
    if &bytes[..8] != DURABLE_MAGIC {
        return Err(NduProjectionDurableError::MissingHeader);
    }
    if bytes[8..40] != *binding_digest.as_array() {
        return Err(NduProjectionDurableError::BindingMismatch);
    }
    let expected_header = durable_header(binding_digest);
    if bytes[..DURABLE_HEADER_BYTES] != expected_header {
        return Err(NduProjectionDurableError::HeaderDigestMismatch);
    }

    let acknowledged_count = usize::try_from(anchor.sequence)
        .map_err(|_| NduProjectionDurableError::InvalidAnchor)?;
    if acknowledged_count > max_records {
        return Err(NduProjectionDurableError::InvalidAnchor);
    }
    let available_complete = (bytes.len() - DURABLE_HEADER_BYTES) / RECORD_BYTES;
    if available_complete < acknowledged_count {
        return Err(NduProjectionDurableError::AcknowledgedHistoryMissing);
    }
    let record_bytes = acknowledged_count
        .checked_mul(RECORD_BYTES)
        .ok_or(NduProjectionDurableError::Capacity)?;
    let committed_length = DURABLE_HEADER_BYTES
        .checked_add(record_bytes)
        .ok_or(NduProjectionDurableError::Capacity)?;

    let count = u32::try_from(acknowledged_count)
        .map_err(|_| NduProjectionDurableError::Capacity)?;
    let mut reference = Vec::with_capacity(12 + record_bytes);
    reference.extend_from_slice(REFERENCE_MAGIC);
    reference.extend_from_slice(&count.to_be_bytes());
    reference.extend_from_slice(&bytes[DURABLE_HEADER_BYTES..committed_length]);
    let journal = NduProjectionJournalV1::reopen(&reference)?;

    if anchor_for_journal(&journal)? != anchor {
        return Err(NduProjectionDurableError::AnchorMismatch);
    }
    Ok((journal, committed_length))
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::sync::Mutex;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use super::*;

    static NEXT_FILE: AtomicU64 = AtomicU64::new(1);

    #[derive(Default)]
    struct TestAnchorStore {
        current: Mutex<Option<NduProjectionDurableAnchorV1>>,
        fail_next: Mutex<bool>,
    }

    impl TestAnchorStore {
        fn fail_next_update(&self) {
            *self.fail_next.lock().expect("anchor failure lock") = true;
        }

        fn force(&self, anchor: NduProjectionDurableAnchorV1) {
            *self.current.lock().expect("anchor lock") = Some(anchor);
        }
    }

    impl NduProjectionAnchorStoreV1 for TestAnchorStore {
        fn current_anchor(&self) -> Result<Option<NduProjectionDurableAnchorV1>, String> {
            Ok(*self.current.lock().map_err(|_| "poisoned".to_owned())?)
        }

        fn compare_and_set(
            &self,
            expected: Option<NduProjectionDurableAnchorV1>,
            next: NduProjectionDurableAnchorV1,
        ) -> Result<(), String> {
            if std::mem::take(
                &mut *self
                    .fail_next
                    .lock()
                    .map_err(|_| "poisoned".to_owned())?,
            ) {
                return Err("simulated ambiguous anchor failure".to_owned());
            }
            let mut current = self.current.lock().map_err(|_| "poisoned".to_owned())?;
            if *current != expected {
                return Err("compare-and-set mismatch".to_owned());
            }
            *current = Some(next);
            Ok(())
        }
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn temp_file(name: &str) -> (PathBuf, File) {
        let ordinal = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-ndu-{name}-{}-{ordinal}.bin",
            std::process::id()
        ));
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .expect("create temporary durable NDU file");
        (path, file)
    }

    #[test]
    fn acknowledged_projection_round_trips_through_recovery() {
        let (path, file) = temp_file("roundtrip");
        let anchors = TestAnchorStore::default();
        let binding = digest("owner-binding");
        let objective = digest("objective");
        let subject = digest("subject");
        let projection = digest("projection");

        let mut durable =
            NduProjectionDurableJournalV1::create(file, binding, 32, &anchors)
                .expect("create durable journal");
        durable
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("projection-operation"),
                objective,
                subject,
                projection,
                &anchors,
            )
            .expect("append projection");
        durable
            .select_projection(
                digest("selection-operation"),
                objective,
                subject,
                projection,
                &anchors,
            )
            .expect("select projection");
        drop(durable);

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("reopen");
        let recovered =
            NduProjectionDurableJournalV1::recover(file, binding, 32, &anchors)
                .expect("recover");
        assert_eq!(
            recovered
                .selected_projection_digest(objective, subject)
                .expect("healthy"),
            Some(projection)
        );
        assert_eq!(recovered.entries().expect("healthy").len(), 2);
        drop(recovered);
        fs::remove_file(path).expect("remove");
    }

    #[test]
    fn ambiguous_anchor_failure_requires_recovery_and_discards_unwitnessed_tail() {
        let (path, file) = temp_file("indeterminate");
        let anchors = TestAnchorStore::default();
        let binding = digest("owner-binding");
        let mut durable =
            NduProjectionDurableJournalV1::create(file, binding, 32, &anchors)
                .expect("create durable journal");

        anchors.fail_next_update();
        let error = durable
            .append_projection(
                NduProjectionKindV1::Utility,
                digest("operation"),
                digest("objective"),
                digest("subject"),
                digest("projection"),
                &anchors,
            )
            .expect_err("anchor failure must be indeterminate");
        assert!(matches!(
            error,
            NduProjectionDurableError::AnchorUpdateIndeterminate(_)
        ));
        assert_eq!(
            durable.entries().expect_err("poisoned writer"),
            NduProjectionDurableError::Poisoned
        );
        drop(durable);

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("reopen");
        let recovered =
            NduProjectionDurableJournalV1::recover(file, binding, 32, &anchors)
                .expect("reconcile from external anchor");
        assert!(recovered.entries().expect("healthy").is_empty());
        drop(recovered);
        fs::remove_file(path).expect("remove");
    }

    #[test]
    fn checkpoint_restore_requires_matching_external_anchor() {
        let (path, file) = temp_file("checkpoint-source");
        let anchors = TestAnchorStore::default();
        let binding = digest("owner-binding");
        let mut durable =
            NduProjectionDurableJournalV1::create(file, binding, 32, &anchors)
                .expect("create durable journal");
        durable
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("operation"),
                digest("objective"),
                digest("subject"),
                digest("projection"),
                &anchors,
            )
            .expect("append");
        let checkpoint = durable.checkpoint().expect("checkpoint");
        drop(durable);

        let (restore_path, restore_file) = temp_file("checkpoint-restore");
        let restored = NduProjectionDurableJournalV1::restore_checkpoint(
            restore_file,
            &checkpoint,
            32,
            &anchors,
        )
        .expect("restore");
        assert_eq!(restored.entries().expect("healthy").len(), 1);
        drop(restored);

        fs::remove_file(path).expect("remove source");
        fs::remove_file(restore_path).expect("remove restore");
    }

    #[test]
    fn authenticated_reference_snapshot_migrates_without_minting_trust() {
        let mut reference = NduProjectionJournalV1::new();
        reference
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("operation"),
                digest("objective"),
                digest("subject"),
                digest("projection"),
            )
            .expect("reference append");
        let reference_bytes = reference.export_bytes();
        let authenticated = anchor_for_journal(&reference).expect("anchor");

        let anchors = TestAnchorStore::default();
        anchors.force(authenticated);
        let (path, file) = temp_file("migration");
        let migrated =
            NduProjectionDurableJournalV1::migrate_authenticated_reference_snapshot(
                file,
                digest("owner-binding"),
                &reference_bytes,
                32,
                &anchors,
            )
            .expect("migrate");
        assert_eq!(migrated.entries().expect("healthy"), reference.entries());
        drop(migrated);
        fs::remove_file(path).expect("remove");
    }
}

//! Checkpointed segment rotation for durable run-start publications.
//!
//! The active segment remains the only mutable data file. Full segments are
//! renamed into an immutable ordered history and a successor segment continues
//! the same global sequence/hash chain from the predecessor anchor. An
//! independently retained checkpoint owner acknowledges every append. Recovery
//! rejects local history behind that frontier and reconciles a locally durable
//! extension when the acknowledgement response was lost.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::run_start::DurableRunStartJournal;
use crate::run_start::LockedRunStartFile;
use crate::run_start::RunStartAnchor;
use crate::run_start::RunStartAppendDisposition;
use crate::run_start::RunStartAppendReceipt;
use crate::run_start::RunStartAuthenticationV1;
use crate::run_start::RunStartConflictRecordV1;
use crate::run_start::RunStartIndexEntryV1;
use crate::run_start::RunStartIndexKindV1;
use crate::run_start::RunStartJournal;
use crate::run_start::RunStartObjectiveDispositionV1;
use crate::run_start::RunStartRecordV1;
use crate::run_start::RunStartRecovery;
use crate::run_start::RunStartStoreError;

const ACTIVE_FILE: &str = "active.bin";
const WRITER_FILE: &str = ".writer.lock";
const LEGACY_FILE: &str = "journal.bin";
const SEGMENT_DIRECTORY: &str = "segments";
const SEGMENT_PREFIX: &str = "segment-";
const SEGMENT_SUFFIX: &str = ".bin";
const COMPACTED_FILE: &str = "compacted-v1.bin";
const COMPACTED_MAGIC: &[u8; 8] = b"HEPTRSC1";
const MAX_COMPACTED_BYTES: u64 = 1024 * 1024 * 1024;
pub const MAX_RUN_START_SEGMENTS: usize = 1024;

#[path = "run_start_compaction.rs"]
mod compaction;
use compaction::compacted_semantic_digest;
use compaction::load_compacted_prefix;
use compaction::write_compacted_prefix;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RunStartCheckpointV1 {
    pub anchor: RunStartAnchor,
    pub compacted_prefix: RunStartAnchor,
    pub compacted_digest: Digest32,
}

impl RunStartCheckpointV1 {
    pub const ZERO: Self = Self {
        anchor: RunStartAnchor::ZERO,
        compacted_prefix: RunStartAnchor::ZERO,
        compacted_digest: Digest32::ZERO,
    };

    pub fn is_well_formed(self) -> bool {
        self.anchor.is_well_formed()
            && self.compacted_prefix.is_well_formed()
            && self.compacted_prefix.sequence <= self.anchor.sequence
            && ((self.compacted_prefix.sequence == 0) == self.compacted_digest.is_zero())
    }
}

/// Independently retained monotonic witness. Implementations must keep this
/// state outside the journal rollback domain and provide compare-and-swap
/// semantics. Exact acknowledgement replay is idempotent.
pub trait RunStartCheckpointOwnerV1: Send + Sync {
    fn current_checkpoint(&self) -> Result<RunStartCheckpointV1, RunStartStoreError>;

    fn compare_and_swap(
        &self,
        expected: RunStartCheckpointV1,
        next: RunStartCheckpointV1,
    ) -> Result<(), RunStartStoreError>;
}

#[derive(Clone, Debug)]
struct CompactedPrefix {
    prefix: RunStartAnchor,
    digest: Digest32,
    pending_previous: Option<(RunStartAnchor, Digest32)>,
    entries: Vec<RunStartIndexEntryV1>,
}

impl CompactedPrefix {
    fn empty() -> Self {
        Self {
            prefix: RunStartAnchor::ZERO,
            digest: Digest32::ZERO,
            pending_previous: None,
            entries: Vec::new(),
        }
    }
}

#[derive(Clone, Debug)]
struct SealedSegment {
    path: PathBuf,
    base_anchor: RunStartAnchor,
    head_anchor: RunStartAnchor,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct SegmentName {
    start_sequence: u64,
    end_sequence: u64,
    head_digest: Digest32,
}

/// Destination-owned run-start history with automatic bounded segment rotation.
/// All segment files are retained so exact historical retries and replay
/// frontiers survive restart. The selected host owns retention/archival policy;
/// removing a segment without an independently acknowledged replacement is
/// detected as rollback.
pub struct DurableRunStartStore {
    root: PathBuf,
    segments_root: PathBuf,
    binding: Digest32,
    max_records_per_segment: usize,
    checkpoint: Box<dyn RunStartCheckpointOwnerV1>,
    compacted: CompactedPrefix,
    active: Option<DurableRunStartJournal>,
    sealed: Vec<SealedSegment>,
    runs: BTreeMap<StableId, RunStartRecordV1>,
    conflicts: BTreeMap<StableId, RunStartConflictRecordV1>,
    index: BTreeMap<StableId, RunStartIndexEntryV1>,
    history: Vec<RunStartIndexEntryV1>,
    anchors: BTreeMap<u64, Digest32>,
    poisoned: bool,
    // Drop last: directory ownership must outlive active/checkpoint teardown.
    _writer: LockedRunStartFile,
}

impl DurableRunStartStore {
    /// Return true only when `root` contains no local run-start history and can
    /// therefore bootstrap a missing independent checkpoint. Unknown entries,
    /// mutable/immutable segment files, compacted state and legacy journals all
    /// make the layout non-pristine so recovery remains fail-closed.
    pub fn checkpoint_initialization_allowed(root: &Path) -> Result<bool, RunStartStoreError> {
        let metadata = match std::fs::symlink_metadata(root) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(true),
            Err(error) => return Err(error.into()),
        };
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(RunStartStoreError::NotRegular);
        }
        for entry in std::fs::read_dir(root)? {
            let entry = entry?;
            if entry.file_name() != std::ffi::OsStr::new(SEGMENT_DIRECTORY) {
                return Ok(false);
            }
            let path = entry.path();
            let metadata = std::fs::symlink_metadata(&path)?;
            if !metadata.is_dir() || metadata.file_type().is_symlink() {
                return Err(RunStartStoreError::NotRegular);
            }
            if std::fs::read_dir(path)?.next().transpose()?.is_some() {
                return Ok(false);
            }
        }
        Ok(true)
    }

    pub fn open(
        root: PathBuf,
        binding: Digest32,
        max_records_per_segment: usize,
        checkpoint: Box<dyn RunStartCheckpointOwnerV1>,
    ) -> Result<Self, RunStartStoreError> {
        prepare_directory(&root)?;
        // A segment lock alone leaves a takeover window during rotation and
        // cannot serialize compaction/recovery. Never rename or unlink this
        // stable lock file; its lease covers the complete directory lifecycle.
        let writer_path = root.join(WRITER_FILE);
        let writer_file = match create_private(&writer_path) {
            Ok(file) => {
                file.sync_all()?;
                sync_directory(&root)?;
                file
            }
            Err(RunStartStoreError::Io(std::io::ErrorKind::AlreadyExists)) => {
                open_regular(&writer_path)?
            }
            Err(error) => return Err(error),
        };
        let writer = LockedRunStartFile::acquire(writer_file)?;
        let segments_root = root.join(SEGMENT_DIRECTORY);
        prepare_directory(&segments_root)?;
        migrate_legacy_active(&root, &segments_root)?;
        let compacted = load_compacted_prefix(&root, binding)?;

        let mut sealed_names = list_sealed_segments(&segments_root)?;
        sealed_names.sort_by_key(|(name, _)| name.start_sequence);
        if sealed_names.len() >= MAX_RUN_START_SEGMENTS {
            return Err(RunStartStoreError::Capacity);
        }

        let mut prior = compacted.prefix;
        let mut sealed = Vec::new();
        let mut overlap_paths = Vec::new();
        let mut runs = BTreeMap::new();
        let mut conflicts = BTreeMap::new();
        let mut index = BTreeMap::new();
        let mut history = Vec::new();
        let mut anchors = BTreeMap::from([(0, Digest32::ZERO)]);
        ingest_compacted(&compacted, &mut index, &mut history, &mut anchors)?;

        for (name, path) in sealed_names {
            if name.end_sequence <= compacted.prefix.sequence {
                let base_sequence = name
                    .start_sequence
                    .checked_sub(1)
                    .ok_or(RunStartStoreError::SegmentMismatch)?;
                let base = RunStartAnchor {
                    sequence: base_sequence,
                    chain_digest: anchors
                        .get(&base_sequence)
                        .copied()
                        .ok_or(RunStartStoreError::SegmentMismatch)?,
                };
                let journal =
                    recover_named_segment(&path, binding, max_records_per_segment, name, base)?;
                validate_compacted_overlap(&journal, &index)?;
                overlap_paths.push(path);
                continue;
            }
            if name.start_sequence <= compacted.prefix.sequence
                || name.start_sequence
                    != prior
                        .sequence
                        .checked_add(1)
                        .ok_or(RunStartStoreError::Capacity)?
            {
                return Err(RunStartStoreError::SegmentMismatch);
            }
            let journal =
                recover_named_segment(&path, binding, max_records_per_segment, name, prior)?;
            let head = journal.head_anchor();
            ingest_journal(
                &journal,
                &mut runs,
                &mut conflicts,
                &mut index,
                &mut history,
                &mut anchors,
            )?;
            sealed.push(SealedSegment {
                path,
                base_anchor: prior,
                head_anchor: head,
            });
            prior = head;
        }

        let active_path = root.join(ACTIVE_FILE);
        let active = if active_path.exists() {
            let journal = DurableRunStartJournal::recover(
                open_regular(&active_path)?,
                binding,
                max_records_per_segment,
                RunStartRecovery::Unacknowledged,
            )?;
            if journal.base_anchor() != prior {
                return Err(RunStartStoreError::SegmentMismatch);
            }
            journal
        } else {
            let journal = DurableRunStartJournal::create_segment(
                create_private(&active_path)?,
                binding,
                max_records_per_segment,
                prior,
            )?;
            sync_directory(&root)?;
            journal
        };
        ingest_journal(
            &active,
            &mut runs,
            &mut conflicts,
            &mut index,
            &mut history,
            &mut anchors,
        )?;

        let mut store = Self {
            root,
            segments_root,
            binding,
            max_records_per_segment,
            checkpoint,
            compacted,
            active: Some(active),
            sealed,
            runs,
            conflicts,
            index,
            history,
            anchors,
            poisoned: false,
            _writer: writer,
        };
        store.reconcile_checkpoint()?;
        cleanup_paths(&overlap_paths)?;
        sync_directory(&store.segments_root)?;
        Ok(store)
    }

    pub fn reconcile_checkpoint(&mut self) -> Result<(), RunStartStoreError> {
        self.ready()?;
        let mut external = self.checkpoint.current_checkpoint()?;
        if !external.is_well_formed() {
            return Err(RunStartStoreError::InvalidAnchor);
        }
        let local = self.local_checkpoint();
        if external.anchor.sequence > local.anchor.sequence
            || self.anchors.get(&external.anchor.sequence).copied()
                != Some(external.anchor.chain_digest)
        {
            return Err(RunStartStoreError::RollbackDetected);
        }

        let external_compaction = (external.compacted_prefix, external.compacted_digest);
        let local_compaction = (local.compacted_prefix, local.compacted_digest);
        if external_compaction != local_compaction {
            let Some(previous) = self.compacted.pending_previous else {
                return Err(RunStartStoreError::RollbackDetected);
            };
            if external_compaction != previous || external.anchor != local.anchor {
                return Err(RunStartStoreError::RollbackDetected);
            }
            let next = RunStartCheckpointV1 {
                anchor: external.anchor,
                compacted_prefix: local.compacted_prefix,
                compacted_digest: local.compacted_digest,
            };
            self.checkpoint.compare_and_swap(external, next)?;
            external = next;
        }

        while external.anchor.sequence < local.anchor.sequence {
            let sequence = external
                .anchor
                .sequence
                .checked_add(1)
                .ok_or(RunStartStoreError::Capacity)?;
            let next = RunStartCheckpointV1 {
                anchor: RunStartAnchor {
                    sequence,
                    chain_digest: self
                        .anchors
                        .get(&sequence)
                        .copied()
                        .ok_or(RunStartStoreError::RollbackDetected)?,
                },
                compacted_prefix: local.compacted_prefix,
                compacted_digest: local.compacted_digest,
            };
            self.checkpoint.compare_and_swap(external, next)?;
            external = next;
        }

        if self.compacted.pending_previous.is_some() {
            let mut committed = self.compacted.clone();
            committed.pending_previous = None;
            write_compacted_prefix(&self.root, self.binding, &committed)?;
            self.compacted = committed;
        }
        Ok(())
    }

    #[must_use]
    pub fn local_checkpoint(&self) -> RunStartCheckpointV1 {
        RunStartCheckpointV1 {
            anchor: self.head_anchor(),
            compacted_prefix: self.compacted.prefix,
            compacted_digest: self.compacted.digest,
        }
    }

    #[must_use]
    pub fn head_anchor(&self) -> RunStartAnchor {
        self.active.as_ref().map_or_else(
            || {
                self.sealed
                    .last()
                    .map_or(RunStartAnchor::ZERO, |value| value.head_anchor)
            },
            DurableRunStartJournal::head_anchor,
        )
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.head_anchor().chain_digest
    }

    #[must_use]
    pub fn segment_count(&self) -> usize {
        self.sealed.len() + usize::from(self.active.is_some())
    }

    pub fn records(&self) -> Result<Vec<&RunStartRecordV1>, RunStartStoreError> {
        self.ready()?;
        Ok(self
            .history
            .iter()
            .filter_map(|entry| self.runs.get(&entry.run_id))
            .collect())
    }

    pub fn conflicts(&self) -> Result<Vec<&RunStartConflictRecordV1>, RunStartStoreError> {
        self.ready()?;
        Ok(self
            .history
            .iter()
            .filter_map(|entry| self.conflicts.get(&entry.run_id))
            .collect())
    }

    pub fn index_entries(&self) -> Result<Vec<&RunStartIndexEntryV1>, RunStartStoreError> {
        self.ready()?;
        Ok(self.history.iter().collect())
    }

    /// Resolve one retained replay identity without allocating or scanning the
    /// entire history. Entries remain available after payload compaction.
    pub fn index_entry(
        &self,
        run_id: &StableId,
    ) -> Result<Option<&RunStartIndexEntryV1>, RunStartStoreError> {
        self.ready()?;
        Ok(self.index.get(run_id))
    }

    pub fn authentication_records(
        &self,
    ) -> Result<Vec<(&RunStartAuthenticationV1, &StableId)>, RunStartStoreError> {
        self.ready()?;
        Ok(self
            .history
            .iter()
            .map(|value| (&value.authentication, &value.run_id))
            .collect())
    }

    #[must_use]
    pub fn sealed_segment_anchors(&self) -> Vec<(RunStartAnchor, RunStartAnchor)> {
        self.sealed
            .iter()
            .map(|segment| (segment.base_anchor, segment.head_anchor))
            .collect()
    }

    #[must_use]
    pub fn sealed_segment_paths(&self) -> Vec<&Path> {
        self.sealed
            .iter()
            .map(|segment| segment.path.as_path())
            .collect()
    }

    pub fn get(&self, run_id: &StableId) -> Result<Option<&RunStartRecordV1>, RunStartStoreError> {
        self.ready()?;
        Ok(self.runs.get(run_id))
    }

    pub fn get_conflict(
        &self,
        run_id: &StableId,
    ) -> Result<Option<&RunStartConflictRecordV1>, RunStartStoreError> {
        self.ready()?;
        Ok(self.conflicts.get(run_id))
    }

    fn append_run(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        self.ready()?;
        let digest = DurableRunStartJournal::run_record_digest(&record)?;
        let run_id = record.snapshot.run_id.clone();
        if let Some(existing) = self.index.get(&run_id) {
            return replay_or_conflict(existing, digest);
        }
        if expected_predecessor != self.head_digest() {
            return Err(RunStartStoreError::Conflict);
        }
        self.rotate_if_full()?;
        let expected_checkpoint = self.local_checkpoint();
        let receipt = match self
            .active_mut()?
            .append(expected_predecessor, record.clone())
        {
            Ok(receipt) => receipt,
            Err(RunStartStoreError::Capacity) => {
                self.rotate()?;
                self.active_mut()?
                    .append(expected_predecessor, record.clone())?
            }
            Err(error) => return Err(error),
        };
        let entry = self
            .active_mut()?
            .index_entries()?
            .into_iter()
            .last()
            .ok_or(RunStartStoreError::Indeterminate)?;
        if entry.run_id != run_id || entry.record_digest != receipt.record_digest {
            self.poisoned = true;
            return Err(RunStartStoreError::Indeterminate);
        }
        self.runs.insert(run_id.clone(), record);
        self.index.insert(run_id, entry.clone());
        self.history.push(entry.clone());
        self.anchors.insert(entry.sequence, entry.chain_digest);
        self.publish_checkpoint(expected_checkpoint, &receipt)?;
        Ok(receipt)
    }

    fn append_conflict_record(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartConflictRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        self.ready()?;
        let digest = DurableRunStartJournal::conflict_record_digest(&record)?;
        let run_id = record.run_id.clone();
        if let Some(existing) = self.index.get(&run_id) {
            return replay_or_conflict(existing, digest);
        }
        if expected_predecessor != self.head_digest() {
            return Err(RunStartStoreError::Conflict);
        }
        self.rotate_if_full()?;
        let expected_checkpoint = self.local_checkpoint();
        let receipt = match self
            .active_mut()?
            .append_conflict(expected_predecessor, record.clone())
        {
            Ok(receipt) => receipt,
            Err(RunStartStoreError::Capacity) => {
                self.rotate()?;
                self.active_mut()?
                    .append_conflict(expected_predecessor, record.clone())?
            }
            Err(error) => return Err(error),
        };
        let entry = self
            .active_mut()?
            .index_entries()?
            .into_iter()
            .last()
            .ok_or(RunStartStoreError::Indeterminate)?;
        if entry.run_id != run_id || entry.record_digest != receipt.record_digest {
            self.poisoned = true;
            return Err(RunStartStoreError::Indeterminate);
        }
        self.conflicts.insert(run_id.clone(), record);
        self.index.insert(run_id, entry.clone());
        self.history.push(entry.clone());
        self.anchors.insert(entry.sequence, entry.chain_digest);
        self.publish_checkpoint(expected_checkpoint, &receipt)?;
        Ok(receipt)
    }

    fn publish_checkpoint(
        &mut self,
        expected: RunStartCheckpointV1,
        receipt: &RunStartAppendReceipt,
    ) -> Result<(), RunStartStoreError> {
        let next = RunStartCheckpointV1 {
            anchor: RunStartAnchor {
                sequence: receipt.sequence,
                chain_digest: receipt.chain_digest,
            },
            compacted_prefix: expected.compacted_prefix,
            compacted_digest: expected.compacted_digest,
        };
        if let Err(error) = self.checkpoint.compare_and_swap(expected, next) {
            self.poisoned = true;
            return Err(error);
        }
        Ok(())
    }

    fn rotate_if_full(&mut self) -> Result<(), RunStartStoreError> {
        let active = self.active.as_ref().ok_or(RunStartStoreError::Poisoned)?;
        if active.record_count() >= self.max_records_per_segment {
            self.rotate()?;
        }
        Ok(())
    }

    fn rotate(&mut self) -> Result<(), RunStartStoreError> {
        self.ready()?;
        if self.sealed.len() + 1 >= MAX_RUN_START_SEGMENTS {
            return Err(RunStartStoreError::Capacity);
        }
        let active = self.active.as_ref().ok_or(RunStartStoreError::Poisoned)?;
        if active.record_count() == 0 {
            return Err(RunStartStoreError::Capacity);
        }
        let base = active.base_anchor();
        let head = active.head_anchor();
        let active = self.active.take().ok_or(RunStartStoreError::Poisoned)?;
        drop(active);
        let transition = (|| {
            let sealed_path = self.segments_root.join(segment_filename(base, head)?);
            if sealed_path.exists() {
                return Err(RunStartStoreError::SegmentMismatch);
            }
            std::fs::rename(self.root.join(ACTIVE_FILE), &sealed_path)?;
            sync_directory(&self.root)?;
            sync_directory(&self.segments_root)?;
            let successor = DurableRunStartJournal::create_segment(
                create_private(&self.root.join(ACTIVE_FILE))?,
                self.binding,
                self.max_records_per_segment,
                head,
            )?;
            sync_directory(&self.root)?;
            self.sealed.push(SealedSegment {
                path: sealed_path,
                base_anchor: base,
                head_anchor: head,
            });
            self.active = Some(successor);
            Ok(())
        })();
        if transition.is_err() {
            self.poisoned = true;
        }
        transition
    }

    /// Replace a complete expired sealed prefix with an authenticated compact
    /// replay index. The summary retains global run identities, authentication
    /// frontiers, record digests and chain receipts while dropping large native
    /// objective payloads that can no longer be admitted after their deadline.
    ///
    /// The summary is first written as a pending transition, then bound into the
    /// independent checkpoint by CAS, and finally marked committed before old
    /// segment files are removed. Every crash cut is recoverable without
    /// resurrecting an older frontier.
    pub fn compact_expired_prefix(
        &mut self,
        retire_before_unix_micros: u64,
    ) -> Result<usize, RunStartStoreError> {
        self.ready()?;
        if retire_before_unix_micros == 0 {
            return Err(RunStartStoreError::InvalidLimit);
        }
        self.reconcile_checkpoint()?;
        let mut eligible = 0_usize;
        let mut expected_base = self.compacted.prefix;
        for segment in &self.sealed {
            if segment.base_anchor != expected_base {
                return Err(RunStartStoreError::SegmentMismatch);
            }
            if segment_entries_expired(segment, &self.history, retire_before_unix_micros)? {
                eligible += 1;
                expected_base = segment.head_anchor;
            } else {
                break;
            }
        }
        if eligible == 0 {
            return Ok(0);
        }
        let new_prefix = self.sealed[eligible - 1].head_anchor;
        let entry_count =
            usize::try_from(new_prefix.sequence).map_err(|_| RunStartStoreError::Capacity)?;
        let entries = self
            .history
            .get(..entry_count)
            .ok_or(RunStartStoreError::SegmentMismatch)?
            .to_vec();
        let digest = compacted_semantic_digest(self.binding, new_prefix, &entries)?;
        let expected = self.local_checkpoint();
        let pending = CompactedPrefix {
            prefix: new_prefix,
            digest,
            pending_previous: Some((expected.compacted_prefix, expected.compacted_digest)),
            entries,
        };
        if let Err(error) = write_compacted_prefix(&self.root, self.binding, &pending) {
            self.poisoned = true;
            return Err(error);
        }
        let next = RunStartCheckpointV1 {
            anchor: expected.anchor,
            compacted_prefix: new_prefix,
            compacted_digest: digest,
        };
        if let Err(error) = self.checkpoint.compare_and_swap(expected, next) {
            self.poisoned = true;
            return Err(error);
        }
        let mut committed = pending;
        committed.pending_previous = None;
        if let Err(error) = write_compacted_prefix(&self.root, self.binding, &committed) {
            self.poisoned = true;
            return Err(error);
        }
        self.compacted = committed;

        let removed = self.sealed.drain(..eligible).collect::<Vec<_>>();
        self.runs.retain(|run_id, _| {
            self.index
                .get(run_id)
                .is_some_and(|entry| entry.sequence > new_prefix.sequence)
        });
        self.conflicts.retain(|run_id, _| {
            self.index
                .get(run_id)
                .is_some_and(|entry| entry.sequence > new_prefix.sequence)
        });
        let paths = removed
            .iter()
            .map(|segment| segment.path.clone())
            .collect::<Vec<_>>();
        cleanup_paths(&paths)?;
        sync_directory(&self.segments_root)?;
        Ok(eligible)
    }

    fn active_mut(&mut self) -> Result<&mut DurableRunStartJournal, RunStartStoreError> {
        self.active.as_mut().ok_or(RunStartStoreError::Poisoned)
    }

    fn ready(&self) -> Result<(), RunStartStoreError> {
        if self.poisoned {
            Err(RunStartStoreError::Poisoned)
        } else {
            Ok(())
        }
    }
}

fn segment_entries_expired(
    segment: &SealedSegment,
    history: &[RunStartIndexEntryV1],
    retire_before_unix_micros: u64,
) -> Result<bool, RunStartStoreError> {
    let start =
        usize::try_from(segment.base_anchor.sequence).map_err(|_| RunStartStoreError::Capacity)?;
    let end =
        usize::try_from(segment.head_anchor.sequence).map_err(|_| RunStartStoreError::Capacity)?;
    let entries = history
        .get(start..end)
        .ok_or(RunStartStoreError::SegmentMismatch)?;
    if entries.is_empty()
        || entries.first().map(|entry| entry.sequence) != Some(segment.base_anchor.sequence + 1)
        || entries.last().map(|entry| entry.sequence) != Some(segment.head_anchor.sequence)
    {
        return Err(RunStartStoreError::SegmentMismatch);
    }
    Ok(entries.iter().all(|entry| {
        let deadline = match entry.kind {
            RunStartIndexKindV1::Run {
                deadline_unix_micros,
                ..
            }
            | RunStartIndexKindV1::Conflict {
                deadline_unix_micros,
            } => deadline_unix_micros,
        };
        deadline <= retire_before_unix_micros
    }))
}

fn replay_or_conflict(
    existing: &RunStartIndexEntryV1,
    record_digest: Digest32,
) -> Result<RunStartAppendReceipt, RunStartStoreError> {
    if existing.record_digest != record_digest {
        return Err(RunStartStoreError::Conflict);
    }
    Ok(RunStartAppendReceipt {
        disposition: RunStartAppendDisposition::IdempotentReplay,
        sequence: existing.sequence,
        record_digest: existing.record_digest,
        chain_digest: existing.chain_digest,
    })
}

fn ingest_compacted(
    compacted: &CompactedPrefix,
    index: &mut BTreeMap<StableId, RunStartIndexEntryV1>,
    history: &mut Vec<RunStartIndexEntryV1>,
    anchors: &mut BTreeMap<u64, Digest32>,
) -> Result<(), RunStartStoreError> {
    for entry in &compacted.entries {
        if index.insert(entry.run_id.clone(), entry.clone()).is_some()
            || anchors.insert(entry.sequence, entry.chain_digest).is_some()
        {
            return Err(RunStartStoreError::SegmentMismatch);
        }
        history.push(entry.clone());
    }
    Ok(())
}

fn recover_named_segment(
    path: &Path,
    binding: Digest32,
    max_records_per_segment: usize,
    name: SegmentName,
    expected_base: RunStartAnchor,
) -> Result<DurableRunStartJournal, RunStartStoreError> {
    let journal = DurableRunStartJournal::recover(
        open_regular(path)?,
        binding,
        max_records_per_segment,
        RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: name.end_sequence,
            chain_digest: name.head_digest,
        }),
    )?;
    let head = journal.head_anchor();
    if journal.base_anchor() != expected_base
        || head.sequence != name.end_sequence
        || head.chain_digest != name.head_digest
        || journal.record_count() == 0
        || journal.record_count() as u64
            != name
                .end_sequence
                .checked_sub(name.start_sequence)
                .and_then(|value| value.checked_add(1))
                .ok_or(RunStartStoreError::SegmentMismatch)?
    {
        return Err(RunStartStoreError::SegmentMismatch);
    }
    Ok(journal)
}

fn validate_compacted_overlap(
    journal: &DurableRunStartJournal,
    compacted_index: &BTreeMap<StableId, RunStartIndexEntryV1>,
) -> Result<(), RunStartStoreError> {
    for entry in journal.index_entries()? {
        if compacted_index.get(&entry.run_id) != Some(&entry) {
            return Err(RunStartStoreError::SegmentMismatch);
        }
    }
    Ok(())
}

fn cleanup_paths(paths: &[PathBuf]) -> Result<(), RunStartStoreError> {
    for path in paths {
        match std::fs::remove_file(path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}

fn ingest_journal(
    journal: &DurableRunStartJournal,
    runs: &mut BTreeMap<StableId, RunStartRecordV1>,
    conflicts: &mut BTreeMap<StableId, RunStartConflictRecordV1>,
    index: &mut BTreeMap<StableId, RunStartIndexEntryV1>,
    history: &mut Vec<RunStartIndexEntryV1>,
    anchors: &mut BTreeMap<u64, Digest32>,
) -> Result<(), RunStartStoreError> {
    for entry in journal.index_entries()? {
        if index.contains_key(&entry.run_id)
            || anchors.insert(entry.sequence, entry.chain_digest).is_some()
        {
            return Err(RunStartStoreError::SegmentMismatch);
        }
        index.insert(entry.run_id.clone(), entry.clone());
        history.push(entry);
    }
    for record in journal.records()? {
        if runs
            .insert(record.snapshot.run_id.clone(), record.clone())
            .is_some()
        {
            return Err(RunStartStoreError::SegmentMismatch);
        }
    }
    for record in journal.conflicts()? {
        if conflicts
            .insert(record.run_id.clone(), record.clone())
            .is_some()
        {
            return Err(RunStartStoreError::SegmentMismatch);
        }
    }
    Ok(())
}

fn migrate_legacy_active(root: &Path, segments_root: &Path) -> Result<(), RunStartStoreError> {
    let legacy = root.join(LEGACY_FILE);
    if !legacy.exists() {
        return Ok(());
    }
    if root.join(ACTIVE_FILE).exists() || !list_sealed_segments(segments_root)?.is_empty() {
        return Err(RunStartStoreError::SegmentMismatch);
    }
    std::fs::rename(legacy, root.join(ACTIVE_FILE))?;
    sync_directory(root)
}

fn list_sealed_segments(root: &Path) -> Result<Vec<(SegmentName, PathBuf)>, RunStartStoreError> {
    let mut result = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let path = entry.path();
        let metadata = std::fs::symlink_metadata(&path)?;
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err(RunStartStoreError::NotRegular);
        }
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| RunStartStoreError::SegmentMismatch)?;
        result.push((parse_segment_name(&name)?, path));
    }
    if result.len() >= MAX_RUN_START_SEGMENTS {
        return Err(RunStartStoreError::Capacity);
    }
    Ok(result)
}

fn segment_filename(
    base: RunStartAnchor,
    head: RunStartAnchor,
) -> Result<String, RunStartStoreError> {
    let start = base
        .sequence
        .checked_add(1)
        .ok_or(RunStartStoreError::Capacity)?;
    if head.sequence < start || head.chain_digest.is_zero() {
        return Err(RunStartStoreError::InvalidAnchor);
    }
    Ok(format!(
        "{SEGMENT_PREFIX}{start:020}-{end:020}-{digest}{SEGMENT_SUFFIX}",
        end = head.sequence,
        digest = head.chain_digest
    ))
}

fn parse_segment_name(value: &str) -> Result<SegmentName, RunStartStoreError> {
    let value = value
        .strip_prefix(SEGMENT_PREFIX)
        .and_then(|value| value.strip_suffix(SEGMENT_SUFFIX))
        .ok_or(RunStartStoreError::SegmentMismatch)?;
    let mut fields = value.split('-');
    let start_sequence = fields
        .next()
        .ok_or(RunStartStoreError::SegmentMismatch)?
        .parse::<u64>()
        .map_err(|_| RunStartStoreError::SegmentMismatch)?;
    let end_sequence = fields
        .next()
        .ok_or(RunStartStoreError::SegmentMismatch)?
        .parse::<u64>()
        .map_err(|_| RunStartStoreError::SegmentMismatch)?;
    let head_digest = Digest32::from_str(fields.next().ok_or(RunStartStoreError::SegmentMismatch)?)
        .map_err(|_| RunStartStoreError::SegmentMismatch)?;
    if fields.next().is_some()
        || start_sequence == 0
        || end_sequence < start_sequence
        || head_digest.is_zero()
    {
        return Err(RunStartStoreError::SegmentMismatch);
    }
    Ok(SegmentName {
        start_sequence,
        end_sequence,
        head_digest,
    })
}

fn open_regular(path: &Path) -> Result<File, RunStartStoreError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(RunStartStoreError::NotRegular);
    }
    Ok(OpenOptions::new().read(true).write(true).open(path)?)
}

fn create_private(path: &Path) -> Result<File, RunStartStoreError> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    Ok(options.open(path)?)
}

fn prepare_directory(path: &Path) -> Result<(), RunStartStoreError> {
    std::fs::create_dir_all(path)?;
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(RunStartStoreError::NotRegular);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), RunStartStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), RunStartStoreError> {
    Ok(())
}

impl super::sealed::Journal for DurableRunStartStore {}

impl RunStartJournal for DurableRunStartStore {
    fn append_run_start(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        self.append_run(expected_predecessor, record)
    }

    fn append_objective_conflict(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartConflictRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        self.append_conflict_record(expected_predecessor, record)
    }
}

#[cfg(test)]
#[path = "run_start_store_tests.rs"]
mod tests;

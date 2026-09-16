//! Bounded segment rotation over the existing causal ledger and frame codec.
//!
//! The host supplies one stable owner-lock file and independently opened segment
//! files, keeps their names/directory entries durable, and authenticates durable
//! checkpoints. No ambient path, model, effect, or selection authority is used.
//! Sealed segment payloads are released from the live core after rotation; their
//! compact causal indexes remain available and can be durably checkpointed.

use std::fs::File;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::DurableLedgerError;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerArchiveRange;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerRecovery;
use crate::LedgerSnapshot;
use crate::LedgerStateCheckpoint;
use crate::checkpoint::read_state_checkpoint;
use crate::checkpoint::write_state_checkpoint;
use crate::durable_codec::encode_frame;
use crate::durable_lock::LockedFile;
use crate::segment_codec;

/// Independently retained minimum durable frontier. A record-only anchor cannot
/// detect removal of an acknowledged seal or an empty successor generation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LedgerSegmentCheckpoint {
    pub segment: usize,
    pub anchor: LedgerAnchor,
    pub sealed: bool,
}

/// Per-segment limits, bound into each header; not total-history resource claims.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LedgerSegmentLimits {
    pub records: usize,
    pub bytes: u64,
}

impl LedgerSegmentLimits {
    pub(crate) fn validate(self) -> Result<(), DurableLedgerError> {
        if !(1..=8192).contains(&self.records) || !(4096..=8 * 1024 * 1024).contains(&self.bytes) {
            return Err(DurableLedgerError::InvalidLimit);
        }
        Ok(())
    }
}

/// The only mutable history file is the current segment. Sealed payloads are
/// host-owned archive; the live core retains compact semantic indexes plus the
/// current segment tail. File creation and containing-directory fsync remain an
/// explicit host responsibility.
pub struct SegmentedLedger {
    _owner: LockedFile,
    active: LockedFile,
    core: LearningLedger,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    predecessor: LedgerAnchor,
    length: u64,
    sealed: bool,
    poisoned: bool,
    archives: Vec<LedgerArchiveRange>,
}

impl SegmentedLedger {
    pub fn create(
        owner_lock: File,
        first_segment: File,
        binding: Digest32,
        limits: LedgerSegmentLimits,
    ) -> Result<Self, DurableLedgerError> {
        validate(binding, limits)?;
        let owner = LockedFile::acquire(owner_lock)?;
        let mut active = LockedFile::acquire(first_segment)?;
        let predecessor = empty_anchor();
        segment_codec::initialize(&mut active, binding, limits, 0, predecessor)?;
        Ok(Self {
            _owner: owner,
            active,
            core: LearningLedger::new(),
            binding,
            limits,
            index: 0,
            predecessor,
            length: segment_codec::HEADER as u64,
            sealed: false,
            poisoned: false,
            archives: Vec::new(),
        })
    }

    /// Compatibility recovery for a complete ordered history. It still reads
    /// every supplied segment, but releases each sealed prefix payload as soon
    /// as its semantic indexes are rebuilt, so recovery no longer retains the
    /// full event history in memory. For restart cost bounded by the post-
    /// checkpoint tail, use `recover_from_state_checkpoint`.
    pub fn recover(
        owner_lock: File,
        segments: Vec<File>,
        binding: Digest32,
        limits: LedgerSegmentLimits,
        minimum: LedgerSegmentCheckpoint,
    ) -> Result<Self, DurableLedgerError> {
        validate(binding, limits)?;
        if segments.is_empty() {
            return Err(DurableLedgerError::InvalidLimit);
        }
        let owner = LockedFile::acquire(owner_lock)?;
        if minimum.segment >= segments.len() {
            return Err(DurableLedgerError::AcknowledgedHistoryMissing);
        }
        let mut core = LearningLedger::new();
        let mut archives = Vec::new();
        let count = segments.len();
        let mut final_file = None;
        for (index, file) in segments.into_iter().enumerate() {
            let mut file = LockedFile::acquire(file)?;
            let predecessor = current_anchor(&core);
            let parsed =
                segment_codec::replay(&mut file, binding, limits, index, predecessor, &mut core)?;
            let anchor = current_anchor(&core);
            validate_minimum_at_segment(minimum, index, predecessor, anchor, parsed.sealed)?;
            if index + 1 != count {
                if !parsed.sealed || parsed.cursor != parsed.length {
                    return Err(DurableLedgerError::IncompleteTail);
                }
                archives.push(LedgerArchiveRange {
                    segment: index,
                    predecessor,
                    anchor,
                });
                core.compact_retained_payloads();
            } else {
                final_file = Some((file, predecessor, parsed));
            }
        }
        validate_minimum_anchor(&core, minimum)?;
        let (mut active, predecessor, parsed) =
            final_file.ok_or(DurableLedgerError::MissingHeader)?;
        if parsed.cursor != parsed.length {
            active
                .set_len(parsed.cursor)
                .map_err(|_| DurableLedgerError::Indeterminate)?;
        }
        active
            .sync_all()
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        active.seek(SeekFrom::Start(parsed.cursor))?;
        Ok(Self {
            _owner: owner,
            active,
            core,
            binding,
            limits,
            index: count - 1,
            predecessor,
            length: parsed.cursor,
            sealed: parsed.sealed,
            poisoned: false,
            archives,
        })
    }

    /// Recover compact semantic indexes from an independently witnessed durable
    /// checkpoint and replay only successor segments. `tail_segments[0]` must be
    /// logical segment `witness.segment + 1`; callers keep older archive files
    /// outside the writer and open them only for explicit historical reads.
    pub fn recover_from_state_checkpoint(
        owner_lock: File,
        checkpoint_file: File,
        tail_segments: Vec<File>,
        binding: Digest32,
        limits: LedgerSegmentLimits,
        witness: LedgerStateCheckpoint,
        minimum: LedgerSegmentCheckpoint,
    ) -> Result<Self, DurableLedgerError> {
        validate(binding, limits)?;
        if tail_segments.is_empty() {
            return Err(DurableLedgerError::MissingHeader);
        }
        let owner = LockedFile::acquire(owner_lock)?;
        let (mut core, mut archives) = read_state_checkpoint(checkpoint_file, binding, witness)?;
        if archives.last().map(|range| (range.segment, range.anchor))
            != Some((witness.segment, witness.anchor))
        {
            return Err(DurableLedgerError::Corrupt);
        }
        validate_minimum_anchor(&core, minimum)?;
        if minimum.sealed && minimum.segment <= witness.segment {
            let range = archives
                .get(minimum.segment)
                .ok_or(DurableLedgerError::AcknowledgedHistoryMissing)?;
            if range.anchor != minimum.anchor {
                return Err(DurableLedgerError::AcknowledgedHistoryMissing);
            }
        }

        let count = tail_segments.len();
        let start_index = witness
            .segment
            .checked_add(1)
            .ok_or(DurableLedgerError::Capacity)?;
        let mut final_file = None;
        for (offset, file) in tail_segments.into_iter().enumerate() {
            let index = start_index
                .checked_add(offset)
                .ok_or(DurableLedgerError::Capacity)?;
            let mut file = LockedFile::acquire(file)?;
            let predecessor = current_anchor(&core);
            let parsed =
                segment_codec::replay(&mut file, binding, limits, index, predecessor, &mut core)?;
            let anchor = current_anchor(&core);
            validate_minimum_at_segment(minimum, index, predecessor, anchor, parsed.sealed)?;
            if offset + 1 != count {
                if !parsed.sealed || parsed.cursor != parsed.length {
                    return Err(DurableLedgerError::IncompleteTail);
                }
                archives.push(LedgerArchiveRange {
                    segment: index,
                    predecessor,
                    anchor,
                });
                core.compact_retained_payloads();
            } else {
                final_file = Some((file, index, predecessor, parsed));
            }
        }
        let (mut active, index, predecessor, parsed) =
            final_file.ok_or(DurableLedgerError::MissingHeader)?;
        if minimum.segment > index {
            return Err(DurableLedgerError::AcknowledgedHistoryMissing);
        }
        validate_minimum_anchor(&core, minimum)?;
        if parsed.cursor != parsed.length {
            active
                .set_len(parsed.cursor)
                .map_err(|_| DurableLedgerError::Indeterminate)?;
        }
        active
            .sync_all()
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        active.seek(SeekFrom::Start(parsed.cursor))?;
        Ok(Self {
            _owner: owner,
            active,
            core,
            binding,
            limits,
            index,
            predecessor,
            length: parsed.cursor,
            sealed: parsed.sealed,
            poisoned: false,
            archives,
        })
    }

    pub fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        self.ready()?;
        let prepared = self
            .core
            .prepare(event)
            .map_err(DurableLedgerError::Semantic)?;
        if prepared.record.predecessor_chain_digest != expected_predecessor {
            return Err(DurableLedgerError::Conflict);
        }
        // A historical identical retry is safe even when its full payload is in
        // archive. Compact identity metadata reconstructs the exact receipt.
        if prepared.disposition == AppendDisposition::IdempotentReplay {
            return self
                .core
                .apply(prepared)
                .map_err(DurableLedgerError::Semantic);
        }
        let frame = encode_frame(&prepared.record)?;
        if self.sealed
            || self.core.retained_records_since(self.predecessor.sequence)
                >= self.limits.records as u64
            || self.length + frame.len() as u64 + segment_codec::FOOTER as u64 > self.limits.bytes
        {
            return Err(DurableLedgerError::Capacity);
        }
        self.poisoned = true;
        if self.active.seek(SeekFrom::End(0))? != self.length {
            return Err(DurableLedgerError::Corrupt);
        }
        self.active
            .write_all(&frame)
            .and_then(|()| self.active.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        let receipt = self
            .core
            .apply(prepared)
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        self.length += frame.len() as u64;
        self.poisoned = false;
        Ok(receipt)
    }

    /// Seal before exposing a historical segment to an independent reader.
    pub fn seal(&mut self, expected: LedgerAnchor) -> Result<(), DurableLedgerError> {
        self.ready()?;
        if current_anchor(&self.core) != expected {
            return Err(DurableLedgerError::AnchorMismatch);
        }
        if self.sealed {
            return Ok(());
        }
        if expected.sequence == self.predecessor.sequence {
            return Err(DurableLedgerError::InvalidAnchor);
        }
        let footer = segment_codec::footer(self.binding, self.index, expected);
        self.poisoned = true;
        if self.active.seek(SeekFrom::End(0))? != self.length {
            return Err(DurableLedgerError::Corrupt);
        }
        self.active
            .write_all(&footer)
            .and_then(|()| self.active.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        self.length += footer.len() as u64;
        self.sealed = true;
        self.poisoned = false;
        Ok(())
    }

    /// Rotate without a semantic-state sidecar. Runtime payload memory remains
    /// bounded, while restart must use the compatibility full-history recovery.
    pub fn rotate(
        &mut self,
        next_segment: File,
        expected: LedgerAnchor,
    ) -> Result<(), DurableLedgerError> {
        let mut next = self.prepare_successor(next_segment, expected)?;
        let next_index = self
            .index
            .checked_add(1)
            .ok_or(DurableLedgerError::Capacity)?;
        self.seal(expected)?;
        self.poisoned = true;
        segment_codec::initialize(&mut next, self.binding, self.limits, next_index, expected)?;
        self.publish_successor(next, next_index, expected);
        Ok(())
    }

    /// Seal, write and fsync a compact semantic checkpoint, then initialize the
    /// successor. On success future recovery needs only this checkpoint plus
    /// successor/tail segments. Any uncertain I/O leaves the old writer sealed;
    /// callers must recover rather than retrying through another writer.
    pub fn rotate_with_state_checkpoint(
        &mut self,
        checkpoint_file: File,
        next_segment: File,
        expected: LedgerAnchor,
    ) -> Result<LedgerStateCheckpoint, DurableLedgerError> {
        let mut next = self.prepare_successor(next_segment, expected)?;
        let next_index = self
            .index
            .checked_add(1)
            .ok_or(DurableLedgerError::Capacity)?;
        self.seal(expected)?;
        let current_range = LedgerArchiveRange {
            segment: self.index,
            predecessor: self.predecessor,
            anchor: expected,
        };
        let mut checkpoint_ranges = self.archives.clone();
        checkpoint_ranges.push(current_range);
        let witness = write_state_checkpoint(
            checkpoint_file,
            self.binding,
            self.index,
            expected,
            &checkpoint_ranges,
            &self.core,
        )?;
        self.poisoned = true;
        segment_codec::initialize(&mut next, self.binding, self.limits, next_index, expected)?;
        self.publish_successor(next, next_index, expected);
        Ok(witness)
    }

    /// Persist state for an already sealed current segment. A successor is not
    /// created by this method; it is intended for hosts that durably stage the
    /// checkpoint and segment creation as separate operations.
    pub fn state_checkpoint(
        &self,
        checkpoint_file: File,
    ) -> Result<LedgerStateCheckpoint, DurableLedgerError> {
        self.ready()?;
        if !self.sealed {
            return Err(DurableLedgerError::InvalidAnchor);
        }
        let anchor = current_anchor(&self.core);
        let current_range = LedgerArchiveRange {
            segment: self.index,
            predecessor: self.predecessor,
            anchor,
        };
        let mut checkpoint_ranges = self.archives.clone();
        checkpoint_ranges.push(current_range);
        write_state_checkpoint(
            checkpoint_file,
            self.binding,
            self.index,
            anchor,
            &checkpoint_ranges,
            &self.core,
        )
    }

    pub fn checkpoint(&self) -> Result<LedgerSegmentCheckpoint, DurableLedgerError> {
        self.ready()?;
        Ok(LedgerSegmentCheckpoint {
            segment: self.index,
            anchor: current_anchor(&self.core),
            sealed: self.sealed,
        })
    }

    pub fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        self.ready()?;
        Ok(current_anchor(&self.core))
    }

    /// A complete snapshot is available without archive I/O only before the
    /// first payload compaction. Once history is archived callers must supply
    /// the sealed archive files explicitly via `snapshot_with_archives`.
    pub fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        self.ready()?;
        if self.core.archived_through_sequence() != 0 {
            return Err(DurableLedgerError::AcknowledgedHistoryMissing);
        }
        Ok(self.core.snapshot())
    }

    /// Reconstruct an explicit full-history snapshot from host-opened sealed
    /// archives plus the resident current tail. This expensive audit operation
    /// does not change the bounded writer state.
    pub fn snapshot_with_archives(
        &self,
        archive_files: Vec<File>,
    ) -> Result<LedgerSnapshot, DurableLedgerError> {
        self.ready()?;
        if archive_files.len() != self.archives.len() {
            return Err(DurableLedgerError::AcknowledgedHistoryMissing);
        }
        let mut full = LearningLedger::new();
        for (range, file) in self.archives.iter().copied().zip(archive_files) {
            let mut guard = segment_codec::SharedSegment::acquire(file)?;
            if current_anchor(&full) != range.predecessor {
                return Err(DurableLedgerError::Corrupt);
            }
            let parsed = segment_codec::replay(
                &mut guard.0,
                self.binding,
                self.limits,
                range.segment,
                range.predecessor,
                &mut full,
            )?;
            if !parsed.sealed
                || parsed.cursor != parsed.length
                || current_anchor(&full) != range.anchor
            {
                return Err(DurableLedgerError::Corrupt);
            }
        }
        for expected in self.core.records() {
            let receipt = full
                .append(expected.event.clone())
                .map_err(DurableLedgerError::Semantic)?;
            let actual = full
                .records()
                .last()
                .ok_or(DurableLedgerError::Corrupt)?;
            if actual != expected || receipt.disposition != AppendDisposition::Appended {
                return Err(DurableLedgerError::Corrupt);
            }
        }
        if current_anchor(&full) != current_anchor(&self.core) {
            return Err(DurableLedgerError::Corrupt);
        }
        Ok(full.snapshot())
    }

    pub fn active_records(&self) -> Result<Vec<&LedgerRecord>, DurableLedgerError> {
        self.ready()?;
        if self.core.archived_through_sequence() != 0 {
            return Err(DurableLedgerError::AcknowledgedHistoryMissing);
        }
        Ok(self.core.active_records())
    }

    pub fn active_records_with_archives(
        &self,
        archive_files: Vec<File>,
    ) -> Result<Vec<LedgerRecord>, DurableLedgerError> {
        let snapshot = self.snapshot_with_archives(archive_files)?;
        let full = LearningLedger::from_snapshot(snapshot).map_err(DurableLedgerError::Semantic)?;
        Ok(full.active_records().into_iter().cloned().collect())
    }

    /// Return the immutable archive range containing a historical identity.
    /// Hosts use the segment number to open exactly one archive file.
    pub fn archive_range(
        &self,
        record_id: &StableId,
    ) -> Result<Option<LedgerArchiveRange>, DurableLedgerError> {
        self.ready()?;
        let Some(index) = self.core.historical_record_index(record_id) else {
            return Ok(None);
        };
        if self.core.record(record_id).is_some() {
            return Ok(None);
        }
        Ok(self
            .archives
            .iter()
            .copied()
            .find(|range| range.contains_sequence(index.sequence.get())))
    }

    /// Disk-backed lookup for one archived record. The caller opens the segment
    /// selected by `archive_range`; only that bounded segment is scanned and its
    /// complete seal is verified before the record is returned.
    pub fn archived_record(
        &self,
        archive_file: File,
        record_id: &StableId,
    ) -> Result<Option<LedgerRecord>, DurableLedgerError> {
        self.ready()?;
        if let Some(record) = self.core.record(record_id) {
            return Ok(Some(record.clone()));
        }
        let Some(index) = self.core.historical_record_index(record_id) else {
            return Ok(None);
        };
        let range = self
            .archives
            .iter()
            .copied()
            .find(|range| range.contains_sequence(index.sequence.get()))
            .ok_or(DurableLedgerError::AcknowledgedHistoryMissing)?;
        let mut guard = segment_codec::SharedSegment::acquire(archive_file)?;
        let record = segment_codec::read_record_at_sequence(
            &mut guard.0,
            self.binding,
            self.limits,
            range.segment,
            range.predecessor,
            index.sequence.get(),
        )?
        .ok_or(DurableLedgerError::AcknowledgedHistoryMissing)?;
        if record.event.record_id() != record_id
            || record.sequence != index.sequence
            || record.predecessor_chain_digest != index.predecessor_chain_digest
            || record.event_digest != index.event_digest
            || record.chain_digest != index.chain_digest
        {
            return Err(DurableLedgerError::Corrupt);
        }
        Ok(Some(record))
    }

    #[must_use]
    pub fn archive_ranges(&self) -> &[LedgerArchiveRange] {
        &self.archives
    }

    pub fn retained_record_count(&self) -> Result<usize, DurableLedgerError> {
        self.ready()?;
        Ok(self.core.retained_record_count())
    }

    pub fn is_sealed(&self) -> Result<bool, DurableLedgerError> {
        self.ready()?;
        Ok(self.sealed)
    }

    fn prepare_successor(
        &self,
        next_segment: File,
        expected: LedgerAnchor,
    ) -> Result<LockedFile, DurableLedgerError> {
        self.ready()?;
        if current_anchor(&self.core) != expected {
            return Err(DurableLedgerError::AnchorMismatch);
        }
        let next = LockedFile::acquire(next_segment)?;
        if next.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized);
        }
        Ok(next)
    }

    fn publish_successor(
        &mut self,
        next: LockedFile,
        next_index: usize,
        expected: LedgerAnchor,
    ) {
        let current_range = LedgerArchiveRange {
            segment: self.index,
            predecessor: self.predecessor,
            anchor: expected,
        };
        let _old = std::mem::replace(&mut self.active, next);
        self.archives.push(current_range);
        self.core.compact_retained_payloads();
        self.index = next_index;
        self.predecessor = expected;
        self.length = segment_codec::HEADER as u64;
        self.sealed = false;
        self.poisoned = false;
    }

    fn ready(&self) -> Result<(), DurableLedgerError> {
        if self.poisoned {
            Err(DurableLedgerError::Poisoned)
        } else {
            Ok(())
        }
    }
}

/// Inspect only fully sealed exact externally witnessed history without
/// acquiring the live writer's owner lock. This intentionally materializes the
/// requested audit history; it is not the normal long-running writer path.
pub fn inspect_ledger_segments(
    segments: Vec<File>,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    anchor: LedgerAnchor,
) -> Result<LedgerSnapshot, DurableLedgerError> {
    validate(binding, limits)?;
    if segments.is_empty() {
        return Err(DurableLedgerError::InvalidLimit);
    }
    let mut core = LearningLedger::new();
    for (index, file) in segments.into_iter().enumerate() {
        let mut guard = segment_codec::SharedSegment::acquire(file)?;
        let predecessor = current_anchor(&core);
        let parsed =
            segment_codec::replay(&mut guard.0, binding, limits, index, predecessor, &mut core)?;
        if !parsed.sealed || parsed.cursor != parsed.length {
            return Err(DurableLedgerError::IncompleteTail);
        }
    }
    segment_codec::validate_anchor(&core, LedgerRecovery::Acknowledged(anchor))?;
    if current_anchor(&core) != anchor {
        return Err(DurableLedgerError::UnwitnessedTail);
    }
    Ok(core.snapshot())
}

pub(crate) fn current_anchor(core: &LearningLedger) -> LedgerAnchor {
    core.head_sequence().map_or_else(empty_anchor, |sequence| LedgerAnchor {
        sequence: sequence.get(),
        chain_digest: core.head_digest(),
    })
}

fn empty_anchor() -> LedgerAnchor {
    LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    }
}

fn validate_minimum_at_segment(
    minimum: LedgerSegmentCheckpoint,
    index: usize,
    predecessor: LedgerAnchor,
    anchor: LedgerAnchor,
    sealed: bool,
) -> Result<(), DurableLedgerError> {
    if index != minimum.segment {
        return Ok(());
    }
    if minimum.anchor.sequence < predecessor.sequence
        || minimum.anchor.sequence > anchor.sequence
        || (minimum.sealed && (!sealed || minimum.anchor != anchor))
    {
        return Err(DurableLedgerError::AcknowledgedHistoryMissing);
    }
    Ok(())
}

fn validate_minimum_anchor(
    core: &LearningLedger,
    minimum: LedgerSegmentCheckpoint,
) -> Result<(), DurableLedgerError> {
    if minimum.anchor.sequence == 0 {
        if minimum.segment != 0 || minimum.sealed || !minimum.anchor.chain_digest.is_zero() {
            return Err(DurableLedgerError::InvalidAnchor);
        }
    } else {
        segment_codec::validate_anchor(core, LedgerRecovery::Acknowledged(minimum.anchor))?;
    }
    Ok(())
}

fn validate(binding: Digest32, limits: LedgerSegmentLimits) -> Result<(), DurableLedgerError> {
    if binding.is_zero() {
        return Err(DurableLedgerError::InvalidBinding);
    }
    limits.validate()
}

#[cfg(test)]
#[path = "segments_tests.rs"]
mod tests;
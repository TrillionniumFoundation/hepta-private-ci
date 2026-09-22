//! Bounded segment rotation over the existing causal ledger and frame codec.
//!
//! The host supplies one stable owner-lock file and independently opened segment
//! files, keeps their names/directory entries durable, and authenticates the
//! recovery anchor. No ambient path, model, effect, or selection authority is used.
//! The owner lock remains held across rotation. Sealing precedes successor
//! initialization; a failed initialization leaves a sealed predecessor, never an
//! appendable old generation. Recovery retains all cross-segment causal indexes.
//! This profile still retains the core's bounded history in memory.

use std::fs::File;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::DurableLedgerError;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerRecovery;
use crate::LedgerSnapshot;
use crate::durable_codec::encode_frame;
use crate::durable_lock::LockedFile;
use crate::segment_codec;

pub const MAX_LEDGER_SEGMENTS: usize = 1024;

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

/// The only mutable file is the current segment. The same schema owner, codec,
/// sequence, idempotency and causal indexes span the complete ordered history.
/// File creation and directory fsync remain an explicit host responsibility.
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
        })
    }

    /// Replay an explicitly ordered complete history under the stable owner lock.
    /// Only an incomplete final tail may be truncated, after the independently
    /// retained minimum acknowledgement is checked. Missing/reordered/sealed
    /// intermediate bytes are never repaired. A sealed last segment can only be
    /// rotated, not reopened for append.
    pub fn recover(
        owner_lock: File,
        segments: Vec<File>,
        binding: Digest32,
        limits: LedgerSegmentLimits,
        minimum: LedgerSegmentCheckpoint,
    ) -> Result<Self, DurableLedgerError> {
        validate(binding, limits)?;
        if segments.is_empty() || segments.len() > MAX_LEDGER_SEGMENTS {
            return Err(DurableLedgerError::InvalidLimit);
        }
        let owner = LockedFile::acquire(owner_lock)?;
        let count = segments.len();
        if minimum.segment >= count {
            return Err(DurableLedgerError::AcknowledgedHistoryMissing);
        }
        let mut core = LearningLedger::new();
        let mut final_file = None;
        for (index, file) in segments.into_iter().enumerate() {
            let mut file = LockedFile::acquire(file)?;
            let predecessor = current_anchor(&core);
            let parsed =
                segment_codec::replay(&mut file, binding, limits, index, predecessor, &mut core)?;
            if index == minimum.segment
                && (minimum.anchor.sequence < predecessor.sequence
                    || minimum.anchor.sequence > current_anchor(&core).sequence
                    || (minimum.sealed
                        && (!parsed.sealed || minimum.anchor != current_anchor(&core))))
            {
                return Err(DurableLedgerError::AcknowledgedHistoryMissing);
            }
            if index + 1 != count {
                if !parsed.sealed || parsed.cursor != parsed.length {
                    return Err(DurableLedgerError::IncompleteTail);
                }
            } else {
                final_file = Some((file, predecessor, parsed));
            }
        }
        if minimum.anchor.sequence == 0 {
            if minimum.segment != 0 || minimum.sealed || !minimum.anchor.chain_digest.is_zero() {
                return Err(DurableLedgerError::InvalidAnchor);
            }
        } else {
            segment_codec::validate_anchor(&core, LedgerRecovery::Acknowledged(minimum.anchor))?;
        }
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
        // A historical identical retry is safe even while the last segment is
        // sealed. It never creates a frame or silently changes record identity.
        if prepared.disposition == AppendDisposition::IdempotentReplay {
            return self
                .core
                .apply(prepared)
                .map_err(DurableLedgerError::Semantic);
        }
        let frame = encode_frame(&prepared.record)?;
        if self.sealed
            || self.core.records().len() as u64 - self.predecessor.sequence
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
    /// Empty segments cannot be sealed or rotated. The seal survives restart.
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

    /// Initialize a host-created, empty successor after durably sealing the old
    /// segment. This does not publish a filename or issue a new owner generation.
    /// On uncertain I/O, recover before further operations; never discard the
    /// external anchor or overwrite a nonempty candidate to retry.
    pub fn rotate(
        &mut self,
        next_segment: File,
        expected: LedgerAnchor,
    ) -> Result<(), DurableLedgerError> {
        self.ready()?;
        if self.index + 1 >= MAX_LEDGER_SEGMENTS {
            return Err(DurableLedgerError::Capacity);
        }
        let mut next = LockedFile::acquire(next_segment)?;
        if next.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized);
        }
        self.seal(expected)?;
        self.poisoned = true;
        segment_codec::initialize(
            &mut next,
            self.binding,
            self.limits,
            self.index + 1,
            expected,
        )?;
        self.active = next;
        self.index += 1;
        self.predecessor = expected;
        self.length = segment_codec::HEADER as u64;
        self.sealed = false;
        self.poisoned = false;
        Ok(())
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding
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

    pub fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        self.ready()?;
        Ok(self.core.snapshot())
    }

    pub fn active_records(&self) -> Result<Vec<&LedgerRecord>, DurableLedgerError> {
        self.ready()?;
        Ok(self.core.active_records())
    }

    pub fn is_sealed(&self) -> Result<bool, DurableLedgerError> {
        self.ready()?;
        Ok(self.sealed)
    }

    fn ready(&self) -> Result<(), DurableLedgerError> {
        if self.poisoned {
            Err(DurableLedgerError::Poisoned)
        } else {
            Ok(())
        }
    }
}

/// Inspect only a fully sealed, exact externally witnessed history without
/// acquiring the live writer's owner lock. A current anchor beyond this prefix
/// rejects the read; callers must still revalidate revocation at final use.
/// The profile is historical evidence, not physical erasure or runtime authority.
pub fn inspect_ledger_segments(
    segments: Vec<File>,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    anchor: LedgerAnchor,
) -> Result<LedgerSnapshot, DurableLedgerError> {
    validate(binding, limits)?;
    if segments.is_empty() || segments.len() > MAX_LEDGER_SEGMENTS {
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
    core.records()
        .last()
        .map_or_else(empty_anchor, |record| LedgerAnchor {
            sequence: record.sequence.get(),
            chain_digest: record.chain_digest,
        })
}

fn empty_anchor() -> LedgerAnchor {
    LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    }
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

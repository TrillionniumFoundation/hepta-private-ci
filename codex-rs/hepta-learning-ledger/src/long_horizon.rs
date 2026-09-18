//! Long-horizon segmented payload owner with disk-backed semantic history.
//!
//! This profile composes the existing V2 segment framing with
//! `PersistentIndexedLearningLedgerV1`. The active process keeps only one
//! bounded segment tail plus a bounded exact-key semantic cache. Sealed payloads
//! are immutable host-owned archive; record-to-segment and segment-range catalog
//! entries are persisted on disk instead of accumulated in a process-lifetime
//! vector.
//!
//! Commit order is semantic prepare -> payload frame sync -> semantic sidecar
//! publication. Therefore a sidecar can never authorize bytes that were not
//! first durable. If sidecar publication is interrupted, recovery replays only
//! the bounded active segment and idempotently reconciles its immutable index
//! rows. The independently retained checkpoint protects acknowledged active-tail
//! history from rollback; the sidecar is never treated as its own witness.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerSegmentLimits;
use crate::PersistentIndexErrorV1;
use crate::PersistentIndexedLearningLedgerV1;
use crate::PersistentIndexedLedgerErrorV1;
use crate::durable_codec::FRAME_OVERHEAD;
use crate::durable_codec::MAX_EVENT;
use crate::durable_codec::decode_event;
use crate::durable_codec::encode_frame;
use crate::durable_lock::LockedFile;
use crate::ledger::digest_chain;
use crate::ledger::digest_event;
use crate::segment_codec;

const PROFILE_FILE: &str = "long-horizon-profile.v1";
const PROFILE_MAGIC: &[u8; 8] = b"HEPTLH01";
const RECORD_LOCATION_DIR: &str = "archive-record";
const ARCHIVE_RANGE_DIR: &str = "archive-range";
const LOCATION_DOMAIN: &[u8] = b"hepta.learning-ledger.archive-location.v1";
const RANGE_DOMAIN: &[u8] = b"hepta.learning-ledger.archive-range.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct LongHorizonArchiveRangeV1 {
    segment: usize,
    predecessor: LedgerAnchor,
    anchor: LedgerAnchor,
}

impl LongHorizonArchiveRangeV1 {
    #[must_use]
    const fn contains_sequence(self, sequence: u64) -> bool {
        sequence > self.predecessor.sequence && sequence <= self.anchor.sequence
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LongHorizonLedgerCheckpointV1 {
    pub active_segment: usize,
    pub archived_anchor: LedgerAnchor,
    pub head_anchor: LedgerAnchor,
    pub sealed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LongHorizonLedgerMetricsV1 {
    pub active_segment: usize,
    pub active_segment_bytes: u64,
    pub retained_payload_records: usize,
    pub historical_cache_entries: usize,
    pub historical_cache_limit: usize,
    pub segment_record_limit: usize,
    pub segment_byte_limit: u64,
}

#[derive(Debug)]
pub enum LongHorizonLedgerErrorV1 {
    Durable(DurableLedgerError),
    Index(PersistentIndexedLedgerErrorV1),
    InvalidCheckpoint,
    CatalogCorrupt,
    Poisoned,
}

impl std::fmt::Display for LongHorizonLedgerErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LongHorizonLedgerErrorV1 {}

impl From<DurableLedgerError> for LongHorizonLedgerErrorV1 {
    fn from(error: DurableLedgerError) -> Self {
        Self::Durable(error)
    }
}

impl From<std::io::Error> for LongHorizonLedgerErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Durable(DurableLedgerError::from(error))
    }
}

impl From<PersistentIndexedLedgerErrorV1> for LongHorizonLedgerErrorV1 {
    fn from(error: PersistentIndexedLedgerErrorV1) -> Self {
        Self::Index(error)
    }
}

impl From<PersistentIndexErrorV1> for LongHorizonLedgerErrorV1 {
    fn from(error: PersistentIndexErrorV1) -> Self {
        Self::Index(PersistentIndexedLedgerErrorV1::Index(error))
    }
}

/// One stable owner lock, one bounded mutable segment, and disk-backed semantic
/// history. File creation, directory authorization, checkpoint authentication,
/// archive naming and independent witness retention remain host responsibilities.
pub struct LongHorizonSegmentedLedgerV1 {
    _owner: LockedFile,
    active: LockedFile,
    semantic: PersistentIndexedLearningLedgerV1,
    index_root: PathBuf,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    predecessor: LedgerAnchor,
    length: u64,
    sealed: bool,
    poisoned: bool,
}

impl LongHorizonSegmentedLedgerV1 {
    pub fn create(
        owner_lock: File,
        first_segment: File,
        index_root: impl Into<PathBuf>,
        binding: Digest32,
        limits: LedgerSegmentLimits,
        cache_limit: usize,
    ) -> Result<Self, LongHorizonLedgerErrorV1> {
        validate_profile(binding, limits)?;
        let owner = LockedFile::acquire(owner_lock)?;
        let mut active = LockedFile::acquire(first_segment)?;
        if active.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized.into());
        }
        let index_root = index_root.into();
        initialize_profile(&index_root, binding, limits)?;
        let predecessor = empty_anchor();
        segment_codec::initialize(&mut active, binding, limits, 0, predecessor)?;
        let semantic =
            PersistentIndexedLearningLedgerV1::open(&index_root, cache_limit, predecessor)?;
        Ok(Self {
            _owner: owner,
            active,
            semantic,
            index_root,
            binding,
            limits,
            index: 0,
            predecessor,
            length: segment_codec::HEADER as u64,
            sealed: false,
            poisoned: false,
        })
    }

    /// Recover only the bounded active segment. Historical semantic dependencies
    /// are exact-key reads from the persistent sidecar. Complete frames whose
    /// sidecar publication was interrupted are reconciled idempotently; only an
    /// incomplete final frame/footer is truncated.
    pub fn recover(
        owner_lock: File,
        active_segment: File,
        index_root: impl Into<PathBuf>,
        binding: Digest32,
        limits: LedgerSegmentLimits,
        cache_limit: usize,
        minimum: LongHorizonLedgerCheckpointV1,
    ) -> Result<Self, LongHorizonLedgerErrorV1> {
        validate_profile(binding, limits)?;
        validate_checkpoint_shape(minimum)?;
        let owner = LockedFile::acquire(owner_lock)?;
        let mut active = LockedFile::acquire(active_segment)?;
        let index_root = index_root.into();
        verify_profile(&index_root, binding, limits)?;
        let mut semantic = PersistentIndexedLearningLedgerV1::open(
            &index_root,
            cache_limit,
            minimum.archived_anchor,
        )?;
        let parsed = parse_active_segment(
            &mut active,
            binding,
            limits,
            minimum.active_segment,
            minimum.archived_anchor,
        )?;
        validate_minimum(&parsed.records, parsed.sealed, minimum)?;

        for record in &parsed.records {
            let receipt = semantic.reconcile_durable_record(record)?;
            if receipt.sequence != record.sequence
                || receipt.event_digest != record.event_digest
                || receipt.chain_digest != record.chain_digest
            {
                return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
            }
        }
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
            semantic,
            index_root,
            binding,
            limits,
            index: minimum.active_segment,
            predecessor: minimum.archived_anchor,
            length: parsed.cursor,
            sealed: parsed.sealed,
            poisoned: false,
        })
    }

    /// Validate first, sync the exact payload frame second, then publish semantic
    /// sidecar rows. Equal historical retries never append another payload frame.
    pub fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, LongHorizonLedgerErrorV1> {
        self.ready()?;
        let prepared = self.semantic.prepare_event(event)?;
        if prepared.record().predecessor_chain_digest != expected_predecessor {
            self.semantic.cancel_prepared(prepared);
            return Err(DurableLedgerError::Conflict.into());
        }
        if prepared.disposition() == AppendDisposition::IdempotentReplay {
            return self.semantic.commit_prepared(prepared).map_err(Into::into);
        }

        let record = prepared.record().clone();
        let frame = match encode_frame(&record) {
            Ok(frame) => frame,
            Err(error) => {
                self.semantic.cancel_prepared(prepared);
                return Err(error.into());
            }
        };
        if self.sealed
            || self.semantic.retained_record_count() >= self.limits.records
            || self.length + frame.len() as u64 + segment_codec::FOOTER as u64 > self.limits.bytes
        {
            self.semantic.cancel_prepared(prepared);
            return Err(DurableLedgerError::Capacity.into());
        }
        if self.active.seek(SeekFrom::End(0))? != self.length {
            self.semantic.cancel_prepared(prepared);
            return Err(DurableLedgerError::Corrupt.into());
        }

        self.poisoned = true;
        self.active
            .write_all(&frame)
            .and_then(|()| self.active.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        let receipt = self.semantic.commit_prepared(prepared)?;
        if receipt.sequence != record.sequence
            || receipt.event_digest != record.event_digest
            || receipt.chain_digest != record.chain_digest
        {
            return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
        }
        self.length += frame.len() as u64;
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn seal(&mut self, expected: LedgerAnchor) -> Result<(), LongHorizonLedgerErrorV1> {
        self.ready()?;
        if self.semantic.head_anchor() != expected {
            return Err(DurableLedgerError::AnchorMismatch.into());
        }
        if self.sealed {
            return Ok(());
        }
        if expected.sequence == self.predecessor.sequence {
            return Err(DurableLedgerError::InvalidAnchor.into());
        }
        let footer = segment_codec::footer(self.binding, self.index, expected);
        self.poisoned = true;
        if self.active.seek(SeekFrom::End(0))? != self.length {
            return Err(DurableLedgerError::Corrupt.into());
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

    /// Seal and catalog the current segment, initialize the successor, then
    /// release the sealed payload tail from process memory. The returned
    /// checkpoint must be retained independently by the host before the old
    /// segment can be considered an acknowledged archive frontier.
    pub fn rotate(
        &mut self,
        next_segment: File,
        expected: LedgerAnchor,
    ) -> Result<LongHorizonLedgerCheckpointV1, LongHorizonLedgerErrorV1> {
        self.ready()?;
        if self.semantic.head_anchor() != expected {
            return Err(DurableLedgerError::AnchorMismatch.into());
        }
        let mut next = LockedFile::acquire(next_segment)?;
        if next.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized.into());
        }
        let next_index = self
            .index
            .checked_add(1)
            .ok_or(DurableLedgerError::Capacity)?;

        self.seal(expected)?;
        self.poisoned = true;
        persist_archive_catalog(
            &self.index_root,
            self.binding,
            self.index,
            self.predecessor,
            expected,
            self.semantic.retained_records(),
        )?;
        segment_codec::initialize(&mut next, self.binding, self.limits, next_index, expected)?;
        self.semantic
            .confirm_payload_archive_and_compact(expected)?;

        let _old = std::mem::replace(&mut self.active, next);
        self.index = next_index;
        self.predecessor = expected;
        self.length = segment_codec::HEADER as u64;
        self.sealed = false;
        self.poisoned = false;
        self.checkpoint()
    }

    pub fn checkpoint(&self) -> Result<LongHorizonLedgerCheckpointV1, LongHorizonLedgerErrorV1> {
        self.ready()?;
        Ok(LongHorizonLedgerCheckpointV1 {
            active_segment: self.index,
            archived_anchor: self.predecessor,
            head_anchor: self.semantic.head_anchor(),
            sealed: self.sealed,
        })
    }

    #[must_use]
    pub fn head_anchor(&self) -> LedgerAnchor {
        self.semantic.head_anchor()
    }

    pub fn contains_anchor(&self, anchor: LedgerAnchor) -> Result<bool, LongHorizonLedgerErrorV1> {
        self.ready()?;
        self.semantic.contains_anchor(anchor).map_err(Into::into)
    }

    pub fn metrics(&self) -> Result<LongHorizonLedgerMetricsV1, LongHorizonLedgerErrorV1> {
        self.ready()?;
        Ok(LongHorizonLedgerMetricsV1 {
            active_segment: self.index,
            active_segment_bytes: self.length,
            retained_payload_records: self.semantic.retained_record_count(),
            historical_cache_entries: self.semantic.historical_cache_len(),
            historical_cache_limit: self.semantic.historical_cache_limit(),
            segment_record_limit: self.limits.records,
            segment_byte_limit: self.limits.bytes,
        })
    }

    /// Resolve an archived record directly from its persistent location key.
    /// `None` means the record is either unknown or still belongs to the active
    /// resident segment and therefore has not been catalogued as archive.
    pub fn archive_segment_for_record(
        &mut self,
        record_id: &StableId,
    ) -> Result<Option<usize>, LongHorizonLedgerErrorV1> {
        self.ready()?;
        let Some(index) = self.semantic.historical_record_index(record_id)? else {
            return Ok(None);
        };
        let Some(segment) = read_record_location(&self.index_root, self.binding, record_id)? else {
            return Ok(None);
        };
        let range = read_archive_range(&self.index_root, self.binding, segment)?
            .ok_or(LongHorizonLedgerErrorV1::CatalogCorrupt)?;
        if !range.contains_sequence(index.sequence.get()) {
            return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
        }
        Ok(Some(segment))
    }

    /// Validate and read one exact record from a host-opened immutable archive
    /// segment. No archive payload or range vector becomes resident in the writer.
    pub fn archived_record(
        &mut self,
        archive_file: File,
        record_id: &StableId,
    ) -> Result<Option<LedgerRecord>, LongHorizonLedgerErrorV1> {
        self.ready()?;
        let Some(index) = self.semantic.historical_record_index(record_id)? else {
            return Ok(None);
        };
        let Some(segment) = read_record_location(&self.index_root, self.binding, record_id)? else {
            return Ok(None);
        };
        let range = read_archive_range(&self.index_root, self.binding, segment)?
            .ok_or(LongHorizonLedgerErrorV1::CatalogCorrupt)?;
        if !range.contains_sequence(index.sequence.get()) {
            return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
        }
        let mut guard = segment_codec::SharedSegment::acquire(archive_file)?;
        let record = segment_codec::read_record_at_sequence(
            &mut guard.0,
            self.binding,
            self.limits,
            segment,
            range.predecessor,
            index.sequence.get(),
        )?
        .ok_or(LongHorizonLedgerErrorV1::CatalogCorrupt)?;
        if record.event.record_id() != record_id
            || record.sequence != index.sequence
            || record.predecessor_chain_digest != index.predecessor_chain_digest
            || record.event_digest != index.event_digest
            || record.chain_digest != index.chain_digest
        {
            return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
        }
        Ok(Some(record))
    }

    fn ready(&self) -> Result<(), LongHorizonLedgerErrorV1> {
        if self.poisoned {
            Err(LongHorizonLedgerErrorV1::Poisoned)
        } else {
            Ok(())
        }
    }
}

struct ParsedActiveSegment {
    length: u64,
    cursor: u64,
    sealed: bool,
    records: Vec<LedgerRecord>,
}

fn parse_active_segment(
    file: &mut File,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    prior: LedgerAnchor,
) -> Result<ParsedActiveSegment, DurableLedgerError> {
    let length = file.metadata()?.len();
    if length < segment_codec::HEADER as u64 {
        return Err(DurableLedgerError::MissingHeader);
    }
    if length > limits.bytes {
        return Err(DurableLedgerError::Capacity);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut stored = vec![0_u8; segment_codec::HEADER];
    file.read_exact(&mut stored)?;
    if stored != segment_header(binding, limits, index, prior) {
        return Err(DurableLedgerError::BindingMismatch);
    }

    let mut cursor = segment_codec::HEADER as u64;
    let mut current = prior;
    let mut sealed = false;
    let mut records = Vec::new();
    while cursor < length {
        if length - cursor < 8 {
            break;
        }
        let mut prefix = [0_u8; 8];
        file.read_exact(&mut prefix)?;
        let size = u32::from_be_bytes(
            prefix[..4]
                .try_into()
                .map_err(|_| DurableLedgerError::Corrupt)?,
        );
        let complement = u32::from_be_bytes(
            prefix[4..]
                .try_into()
                .map_err(|_| DurableLedgerError::Corrupt)?,
        );
        if size != !complement || size as usize > MAX_EVENT {
            return Err(DurableLedgerError::Corrupt);
        }
        if size == 0 {
            if length - cursor < segment_codec::FOOTER as u64 {
                break;
            }
            let mut bytes = vec![0_u8; segment_codec::FOOTER];
            bytes[..8].copy_from_slice(&prefix);
            file.read_exact(&mut bytes[8..])?;
            if current.sequence == prior.sequence
                || bytes != segment_codec::footer(binding, index, current)
                || cursor + segment_codec::FOOTER as u64 != length
            {
                return Err(DurableLedgerError::Corrupt);
            }
            cursor += segment_codec::FOOTER as u64;
            sealed = true;
            break;
        }

        if records.len() >= limits.records {
            return Err(DurableLedgerError::Capacity);
        }
        let total = size as usize + FRAME_OVERHEAD;
        if length - cursor < total as u64 {
            break;
        }
        if cursor + total as u64 + segment_codec::FOOTER as u64 > limits.bytes {
            return Err(DurableLedgerError::Capacity);
        }
        let mut frame = vec![0_u8; total];
        frame[..8].copy_from_slice(&prefix);
        file.read_exact(&mut frame[8..])?;
        if Digest32::of_bytes(&frame[..total - 32])
            .as_array()
            .as_slice()
            != &frame[total - 32..]
        {
            return Err(DurableLedgerError::Corrupt);
        }

        let sequence_value = u64::from_be_bytes(
            frame[8..16]
                .try_into()
                .map_err(|_| DurableLedgerError::Corrupt)?,
        );
        let predecessor_chain_digest = Digest32::from_array(
            frame[16..48]
                .try_into()
                .map_err(|_| DurableLedgerError::Corrupt)?,
        );
        let event = decode_event(&frame[48..48 + size as usize])?;
        let event_digest = digest_event(&event);
        let chain_start = 48 + size as usize;
        let chain_digest = Digest32::from_array(
            frame[chain_start..chain_start + 32]
                .try_into()
                .map_err(|_| DurableLedgerError::Corrupt)?,
        );
        let sequence =
            LogicalSequence::new(sequence_value).map_err(|_| DurableLedgerError::Corrupt)?;
        if sequence_value != current.sequence.saturating_add(1)
            || predecessor_chain_digest != current.chain_digest
            || chain_digest != digest_chain(current.chain_digest, sequence, event_digest)
        {
            return Err(DurableLedgerError::Corrupt);
        }
        let record = LedgerRecord {
            sequence,
            predecessor_chain_digest,
            event_digest,
            chain_digest,
            event,
        };
        if encode_frame(&record)? != frame {
            return Err(DurableLedgerError::Corrupt);
        }
        current = LedgerAnchor {
            sequence: sequence_value,
            chain_digest,
        };
        records.push(record);
        cursor += total as u64;
    }
    Ok(ParsedActiveSegment {
        length,
        cursor,
        sealed,
        records,
    })
}

fn segment_header(
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    prior: LedgerAnchor,
) -> Vec<u8> {
    let mut bytes = b"HEPTLS02".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&(index as u64).to_be_bytes());
    bytes.extend_from_slice(&prior.sequence.to_be_bytes());
    bytes.extend_from_slice(prior.chain_digest.as_array());
    bytes.extend_from_slice(&(limits.records as u64).to_be_bytes());
    bytes.extend_from_slice(&limits.bytes.to_be_bytes());
    let digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(digest.as_array());
    bytes
}

fn validate_minimum(
    records: &[LedgerRecord],
    sealed: bool,
    minimum: LongHorizonLedgerCheckpointV1,
) -> Result<(), LongHorizonLedgerErrorV1> {
    if minimum.head_anchor.sequence == minimum.archived_anchor.sequence {
        if minimum.head_anchor != minimum.archived_anchor {
            return Err(LongHorizonLedgerErrorV1::InvalidCheckpoint);
        }
    } else {
        let found = records
            .iter()
            .find(|record| record.sequence.get() == minimum.head_anchor.sequence)
            .ok_or(DurableLedgerError::AcknowledgedHistoryMissing)?;
        if found.chain_digest != minimum.head_anchor.chain_digest {
            return Err(DurableLedgerError::AnchorMismatch.into());
        }
    }
    if minimum.sealed {
        let final_anchor = records
            .last()
            .map_or(minimum.archived_anchor, |record| LedgerAnchor {
                sequence: record.sequence.get(),
                chain_digest: record.chain_digest,
            });
        if !sealed || final_anchor != minimum.head_anchor {
            return Err(DurableLedgerError::AcknowledgedHistoryMissing.into());
        }
    }
    Ok(())
}

fn validate_checkpoint_shape(
    checkpoint: LongHorizonLedgerCheckpointV1,
) -> Result<(), LongHorizonLedgerErrorV1> {
    if (checkpoint.archived_anchor.sequence == 0)
        != checkpoint.archived_anchor.chain_digest.is_zero()
        || (checkpoint.head_anchor.sequence == 0) != checkpoint.head_anchor.chain_digest.is_zero()
        || checkpoint.head_anchor.sequence < checkpoint.archived_anchor.sequence
    {
        return Err(LongHorizonLedgerErrorV1::InvalidCheckpoint);
    }
    Ok(())
}

fn validate_profile(
    binding: Digest32,
    limits: LedgerSegmentLimits,
) -> Result<(), LongHorizonLedgerErrorV1> {
    if binding.is_zero() {
        return Err(DurableLedgerError::InvalidBinding.into());
    }
    limits.validate()?;
    Ok(())
}

fn initialize_profile(
    root: &Path,
    binding: Digest32,
    limits: LedgerSegmentLimits,
) -> Result<(), LongHorizonLedgerErrorV1> {
    fs::create_dir_all(root).map_err(PersistentIndexErrorV1::from)?;
    fs::create_dir_all(root.join(RECORD_LOCATION_DIR)).map_err(PersistentIndexErrorV1::from)?;
    fs::create_dir_all(root.join(ARCHIVE_RANGE_DIR)).map_err(PersistentIndexErrorV1::from)?;
    let path = root.join(PROFILE_FILE);
    let bytes = profile_bytes(binding, limits);
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                PersistentIndexErrorV1::Corrupt
            } else {
                PersistentIndexErrorV1::from(error)
            }
        })?;
    file.write_all(&bytes)
        .map_err(PersistentIndexErrorV1::from)?;
    file.sync_all().map_err(PersistentIndexErrorV1::from)?;
    File::open(root)
        .and_then(|directory| directory.sync_all())
        .map_err(PersistentIndexErrorV1::from)?;
    Ok(())
}

fn verify_profile(
    root: &Path,
    binding: Digest32,
    limits: LedgerSegmentLimits,
) -> Result<(), LongHorizonLedgerErrorV1> {
    let bytes = fs::read(root.join(PROFILE_FILE)).map_err(PersistentIndexErrorV1::from)?;
    if bytes != profile_bytes(binding, limits) {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    for directory in [RECORD_LOCATION_DIR, ARCHIVE_RANGE_DIR] {
        let metadata = fs::metadata(root.join(directory)).map_err(PersistentIndexErrorV1::from)?;
        if !metadata.is_dir() {
            return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
        }
    }
    Ok(())
}

fn profile_bytes(binding: Digest32, limits: LedgerSegmentLimits) -> Vec<u8> {
    let mut bytes = PROFILE_MAGIC.to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&(limits.records as u64).to_be_bytes());
    bytes.extend_from_slice(&limits.bytes.to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    bytes
}

fn persist_archive_catalog(
    root: &Path,
    binding: Digest32,
    segment: usize,
    predecessor: LedgerAnchor,
    anchor: LedgerAnchor,
    records: &[LedgerRecord],
) -> Result<(), LongHorizonLedgerErrorV1> {
    if records.is_empty()
        || records
            .first()
            .is_none_or(|record| record.sequence.get() != predecessor.sequence.saturating_add(1))
        || records.last().is_none_or(|record| {
            record.sequence.get() != anchor.sequence || record.chain_digest != anchor.chain_digest
        })
    {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let location_dir = root.join(RECORD_LOCATION_DIR);
    let range_dir = root.join(ARCHIVE_RANGE_DIR);
    for record in records {
        let path = record_location_path(&location_dir, record.event.record_id());
        let bytes = record_location_bytes(binding, record.event.record_id(), segment)?;
        write_immutable(&path, &bytes)?;
    }
    let range = LongHorizonArchiveRangeV1 {
        segment,
        predecessor,
        anchor,
    };
    write_immutable(
        &archive_range_path(&range_dir, segment),
        &archive_range_bytes(binding, range)?,
    )?;
    File::open(&location_dir)
        .and_then(|directory| directory.sync_all())
        .map_err(PersistentIndexErrorV1::from)?;
    File::open(&range_dir)
        .and_then(|directory| directory.sync_all())
        .map_err(PersistentIndexErrorV1::from)?;
    Ok(())
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), LongHorizonLedgerErrorV1> {
    if path.exists() {
        if fs::read(path).map_err(PersistentIndexErrorV1::from)? == bytes {
            return Ok(());
        }
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let temp = path.with_extension("tmp");
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&temp)
        .map_err(PersistentIndexErrorV1::from)?;
    file.write_all(bytes)
        .map_err(PersistentIndexErrorV1::from)?;
    file.sync_all().map_err(PersistentIndexErrorV1::from)?;
    fs::rename(&temp, path).map_err(PersistentIndexErrorV1::from)?;
    Ok(())
}

fn record_location_path(directory: &Path, record_id: &StableId) -> PathBuf {
    directory.join(hex(
        Digest32::of_bytes(&record_location_key(record_id)).as_array()
    ))
}

fn record_location_key(record_id: &StableId) -> Vec<u8> {
    let mut key = LOCATION_DOMAIN.to_vec();
    key.push(0);
    key.extend_from_slice(record_id.as_str().as_bytes());
    key
}

fn record_location_bytes(
    binding: Digest32,
    record_id: &StableId,
    segment: usize,
) -> Result<Vec<u8>, LongHorizonLedgerErrorV1> {
    let id = record_id.as_str().as_bytes();
    let id_len = u16::try_from(id.len()).map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?;
    let segment = u64::try_from(segment).map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&id_len.to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(&segment.to_be_bytes());
    let mut digest_bytes = LOCATION_DOMAIN.to_vec();
    digest_bytes.extend_from_slice(binding.as_array());
    digest_bytes.extend_from_slice(&bytes);
    bytes.extend_from_slice(Digest32::of_bytes(&digest_bytes).as_array());
    Ok(bytes)
}

fn read_record_location(
    root: &Path,
    binding: Digest32,
    record_id: &StableId,
) -> Result<Option<usize>, LongHorizonLedgerErrorV1> {
    let path = record_location_path(&root.join(RECORD_LOCATION_DIR), record_id);
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(PersistentIndexErrorV1::from(error).into()),
    };
    if bytes.len() < 2 + 1 + 8 + 32 {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let id_len = u16::from_be_bytes(
        bytes[..2]
            .try_into()
            .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?,
    ) as usize;
    let id_end = 2_usize
        .checked_add(id_len)
        .ok_or(LongHorizonLedgerErrorV1::CatalogCorrupt)?;
    let segment_end = id_end
        .checked_add(8)
        .ok_or(LongHorizonLedgerErrorV1::CatalogCorrupt)?;
    if segment_end + 32 != bytes.len()
        || bytes.get(2..id_end) != Some(record_id.as_str().as_bytes())
    {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let mut digest_bytes = LOCATION_DOMAIN.to_vec();
    digest_bytes.extend_from_slice(binding.as_array());
    digest_bytes.extend_from_slice(&bytes[..segment_end]);
    if Digest32::of_bytes(&digest_bytes).as_array().as_slice() != &bytes[segment_end..] {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let segment = u64::from_be_bytes(
        bytes[id_end..segment_end]
            .try_into()
            .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?,
    );
    usize::try_from(segment)
        .map(Some)
        .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)
}

fn archive_range_path(directory: &Path, segment: usize) -> PathBuf {
    directory.join(format!("{segment:016x}"))
}

fn archive_range_bytes(
    binding: Digest32,
    range: LongHorizonArchiveRangeV1,
) -> Result<Vec<u8>, LongHorizonLedgerErrorV1> {
    let segment =
        u64::try_from(range.segment).map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&segment.to_be_bytes());
    bytes.extend_from_slice(&range.predecessor.sequence.to_be_bytes());
    bytes.extend_from_slice(range.predecessor.chain_digest.as_array());
    bytes.extend_from_slice(&range.anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(range.anchor.chain_digest.as_array());
    let mut digest_bytes = RANGE_DOMAIN.to_vec();
    digest_bytes.extend_from_slice(binding.as_array());
    digest_bytes.extend_from_slice(&bytes);
    bytes.extend_from_slice(Digest32::of_bytes(&digest_bytes).as_array());
    Ok(bytes)
}

fn read_archive_range(
    root: &Path,
    binding: Digest32,
    segment: usize,
) -> Result<Option<LongHorizonArchiveRangeV1>, LongHorizonLedgerErrorV1> {
    let path = archive_range_path(&root.join(ARCHIVE_RANGE_DIR), segment);
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(PersistentIndexErrorV1::from(error).into()),
    };
    if bytes.len() != 8 + 8 + 32 + 8 + 32 + 32 {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let content_end = bytes.len() - 32;
    let mut digest_bytes = RANGE_DOMAIN.to_vec();
    digest_bytes.extend_from_slice(binding.as_array());
    digest_bytes.extend_from_slice(&bytes[..content_end]);
    if Digest32::of_bytes(&digest_bytes).as_array().as_slice() != &bytes[content_end..] {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let stored_segment = u64::from_be_bytes(
        bytes[0..8]
            .try_into()
            .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?,
    );
    if usize::try_from(stored_segment).ok() != Some(segment) {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    let predecessor = LedgerAnchor {
        sequence: u64::from_be_bytes(
            bytes[8..16]
                .try_into()
                .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?,
        ),
        chain_digest: Digest32::from_array(
            bytes[16..48]
                .try_into()
                .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?,
        ),
    };
    let anchor = LedgerAnchor {
        sequence: u64::from_be_bytes(
            bytes[48..56]
                .try_into()
                .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?,
        ),
        chain_digest: Digest32::from_array(
            bytes[56..88]
                .try_into()
                .map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?,
        ),
    };
    if anchor.sequence <= predecessor.sequence {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    Ok(Some(LongHorizonArchiveRangeV1 {
        segment,
        predecessor,
        anchor,
    }))
}

fn empty_anchor() -> LedgerAnchor {
    LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    }
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(DIGITS[usize::from(byte >> 4)]));
        output.push(char::from(DIGITS[usize::from(byte & 0x0f)]));
    }
    output
}

#[cfg(test)]
#[path = "long_horizon_tests.rs"]
mod tests;

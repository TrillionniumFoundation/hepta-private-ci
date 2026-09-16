//! Durable semantic-state checkpoints for segmented learning history.
//!
//! A checkpoint is a host-authorized sidecar, not a replacement for archived
//! segment bytes. It persists the compact causal indexes required to continue
//! validation after immutable event payloads have been released from memory.
//! The independently retained witness binds the exact checkpoint digest so a
//! suspect sidecar cannot rewrite history and recompute its own checksum.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::DecisionIndex;
use crate::DurableLedgerError;
use crate::HistoricalRecordIndex;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::OutcomeFinality;
use crate::OutcomeIndex;
use crate::durable_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HEPTLC03";
const CHECKPOINT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.checkpoint.v3";
const CHECKPOINT_CHUNK_DOMAIN: &[u8] = b"hepta.learning-ledger.checkpoint-chunk.v3";

/// Immutable range metadata for one sealed archive segment. Hosts bind this
/// descriptor to their own archive naming/catalog layer; no ambient path is
/// persisted by the ledger.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LedgerArchiveRange {
    pub segment: usize,
    pub predecessor: LedgerAnchor,
    pub anchor: LedgerAnchor,
}

impl LedgerArchiveRange {
    #[must_use]
    pub const fn contains_sequence(self, sequence: u64) -> bool {
        sequence > self.predecessor.sequence && sequence <= self.anchor.sequence
    }
}

/// Separately retained witness for one fully synced state checkpoint.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LedgerStateCheckpoint {
    pub segment: usize,
    pub anchor: LedgerAnchor,
    pub state_digest: Digest32,
}

pub(crate) fn write_state_checkpoint(
    file: File,
    binding: Digest32,
    segment: usize,
    anchor: LedgerAnchor,
    archives: &[LedgerArchiveRange],
    core: &LearningLedger,
) -> Result<LedgerStateCheckpoint, DurableLedgerError> {
    if binding.is_zero() || anchor.sequence == 0 || anchor.chain_digest.is_zero() {
        return Err(DurableLedgerError::InvalidAnchor);
    }
    if core.head_sequence().map(LogicalSequence::get) != Some(anchor.sequence)
        || core.head_digest() != anchor.chain_digest
    {
        return Err(DurableLedgerError::AnchorMismatch);
    }
    validate_archive_ranges(archives, segment, anchor)?;

    let mut file = LockedFile::acquire(file)?;
    if file.metadata()?.len() != 0 {
        return Err(DurableLedgerError::AlreadyInitialized);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut writer = CheckpointWriter::new(&mut file);
    writer.bytes(MAGIC)?;
    writer.digest(binding)?;
    writer.u64(usize_to_u64(segment)?)?;
    writer.u64(anchor.sequence)?;
    writer.digest(anchor.chain_digest)?;

    writer.count(archives.len())?;
    for range in archives {
        writer.u64(usize_to_u64(range.segment)?)?;
        writer.anchor(range.predecessor)?;
        writer.anchor(range.anchor)?;
    }

    writer.count(core.record_index.len())?;
    for (record_id, index) in &core.record_index {
        writer.id(record_id)?;
        writer.u64(index.sequence.get())?;
        writer.digest(index.predecessor_chain_digest)?;
        writer.digest(index.event_digest)?;
        writer.digest(index.chain_digest)?;
        writer.byte(index.kind)?;
    }

    writer.count(core.decisions.len())?;
    for (episode_id, decision) in &core.decisions {
        writer.id(episode_id)?;
        writer.id(&decision.record_id)?;
        writer.id(&decision.policy_id)?;
    }

    writer.count(core.outcomes.len())?;
    for (outcome_id, outcome) in &core.outcomes {
        writer.id(outcome_id)?;
        writer.id(&outcome.record_id)?;
        writer.id(&outcome.episode_id)?;
        writer.byte(match outcome.finality {
            OutcomeFinality::Intermediate => 0,
            OutcomeFinality::Terminal => 1,
        })?;
    }

    writer.count(core.credit_ids.len())?;
    for credit_id in &core.credit_ids {
        writer.id(credit_id)?;
    }

    writer.count(core.credit_keys.len())?;
    for (episode_id, outcome_id, artifact_id) in &core.credit_keys {
        writer.id(episode_id)?;
        writer.id(outcome_id)?;
        writer.id(artifact_id)?;
    }

    writer.count(core.revoked.len())?;
    for record_id in &core.revoked {
        writer.id(record_id)?;
    }

    let state_digest = writer.state_digest();
    file.write_all(state_digest.as_array())
        .and_then(|()| file.sync_all())
        .map_err(|_| DurableLedgerError::Indeterminate)?;
    Ok(LedgerStateCheckpoint {
        segment,
        anchor,
        state_digest,
    })
}

pub(crate) fn read_state_checkpoint(
    file: File,
    binding: Digest32,
    witness: LedgerStateCheckpoint,
) -> Result<(LearningLedger, Vec<LedgerArchiveRange>), DurableLedgerError> {
    if binding.is_zero()
        || witness.anchor.sequence == 0
        || witness.anchor.chain_digest.is_zero()
        || witness.state_digest.is_zero()
    {
        return Err(DurableLedgerError::InvalidAnchor);
    }
    let mut file = LockedFile::acquire(file)?;
    file.seek(SeekFrom::Start(0))?;
    let mut reader = CheckpointReader::new(&mut file);
    if reader.array::<8>()? != *MAGIC {
        return Err(DurableLedgerError::Corrupt);
    }
    if reader.digest()? != binding {
        return Err(DurableLedgerError::BindingMismatch);
    }
    if reader.u64()? != usize_to_u64(witness.segment)?
        || reader.u64()? != witness.anchor.sequence
        || reader.digest()? != witness.anchor.chain_digest
    {
        return Err(DurableLedgerError::AnchorMismatch);
    }

    let archive_count = reader.count(witness.anchor.sequence)?;
    let mut archives = Vec::with_capacity(archive_count);
    for _ in 0..archive_count {
        archives.push(LedgerArchiveRange {
            segment: u64_to_usize(reader.u64()?)?,
            predecessor: reader.anchor()?,
            anchor: reader.anchor()?,
        });
    }
    validate_archive_ranges(&archives, witness.segment, witness.anchor)?;

    let record_count = reader.count(witness.anchor.sequence)?;
    if u64::try_from(record_count).map_err(|_| DurableLedgerError::InvalidLimit)?
        != witness.anchor.sequence
    {
        return Err(DurableLedgerError::Corrupt);
    }
    let mut record_index = BTreeMap::new();
    let mut sequence_digests = BTreeMap::new();
    for _ in 0..record_count {
        let record_id = reader.id()?;
        let sequence_value = reader.u64()?;
        let sequence =
            LogicalSequence::new(sequence_value).map_err(|_| DurableLedgerError::Corrupt)?;
        let index = HistoricalRecordIndex {
            sequence,
            predecessor_chain_digest: reader.digest()?,
            event_digest: reader.digest()?,
            chain_digest: reader.digest()?,
            kind: reader.byte()?,
        };
        if index.kind > 3
            || index.event_digest.is_zero()
            || index.chain_digest.is_zero()
            || sequence_value > witness.anchor.sequence
            || record_index.insert(record_id, index.clone()).is_some()
            || sequence_digests
                .insert(sequence_value, index.chain_digest)
                .is_some()
        {
            return Err(DurableLedgerError::Corrupt);
        }
    }
    if sequence_digests.len() != record_count
        || sequence_digests
            .get(&witness.anchor.sequence)
            .copied()
            != Some(witness.anchor.chain_digest)
    {
        return Err(DurableLedgerError::Corrupt);
    }

    let decision_count = reader.count(witness.anchor.sequence)?;
    let mut decisions = BTreeMap::new();
    for _ in 0..decision_count {
        let episode_id = reader.id()?;
        let decision = DecisionIndex {
            record_id: reader.id()?,
            policy_id: reader.id()?,
        };
        if decisions.insert(episode_id, decision).is_some() {
            return Err(DurableLedgerError::Corrupt);
        }
    }

    let outcome_count = reader.count(witness.anchor.sequence)?;
    let mut outcomes = BTreeMap::new();
    for _ in 0..outcome_count {
        let outcome_id = reader.id()?;
        let outcome = OutcomeIndex {
            record_id: reader.id()?,
            episode_id: reader.id()?,
            finality: match reader.byte()? {
                0 => OutcomeFinality::Intermediate,
                1 => OutcomeFinality::Terminal,
                _ => return Err(DurableLedgerError::Corrupt),
            },
        };
        if outcomes.insert(outcome_id, outcome).is_some() {
            return Err(DurableLedgerError::Corrupt);
        }
    }

    let credit_count = reader.count(witness.anchor.sequence)?;
    let mut credit_ids = BTreeSet::new();
    for _ in 0..credit_count {
        if !credit_ids.insert(reader.id()?) {
            return Err(DurableLedgerError::Corrupt);
        }
    }

    let credit_key_count = reader.count(witness.anchor.sequence)?;
    let mut credit_keys = BTreeSet::new();
    for _ in 0..credit_key_count {
        let key = (reader.id()?, reader.id()?, reader.id()?);
        if !credit_keys.insert(key) {
            return Err(DurableLedgerError::Corrupt);
        }
    }

    let revoked_count = reader.count(witness.anchor.sequence)?;
    let mut revoked = BTreeSet::new();
    for _ in 0..revoked_count {
        if !revoked.insert(reader.id()?) {
            return Err(DurableLedgerError::Corrupt);
        }
    }

    let stored_digest = reader.raw_digest()?;
    if stored_digest != reader.state_digest() || stored_digest != witness.state_digest {
        return Err(DurableLedgerError::Corrupt);
    }
    let mut trailing = [0; 1];
    if file.read(&mut trailing)? != 0 {
        return Err(DurableLedgerError::Corrupt);
    }

    Ok((
        LearningLedger {
            records: Vec::new(),
            record_positions: BTreeMap::new(),
            record_index,
            sequence_digests,
            decisions,
            outcomes,
            credit_ids,
            credit_keys,
            revoked,
            archived_through_sequence: witness.anchor.sequence,
            archived_through_digest: witness.anchor.chain_digest,
        },
        archives,
    ))
}

fn validate_archive_ranges(
    archives: &[LedgerArchiveRange],
    segment: usize,
    anchor: LedgerAnchor,
) -> Result<(), DurableLedgerError> {
    if archives.is_empty() || archives.last().map(|range| range.segment) != Some(segment) {
        return Err(DurableLedgerError::InvalidAnchor);
    }
    let mut prior = LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    };
    for (expected_segment, range) in archives.iter().enumerate() {
        if range.segment != expected_segment
            || range.predecessor != prior
            || range.anchor.sequence <= range.predecessor.sequence
            || range.anchor.chain_digest.is_zero()
        {
            return Err(DurableLedgerError::InvalidAnchor);
        }
        prior = range.anchor;
    }
    if prior != anchor {
        return Err(DurableLedgerError::AnchorMismatch);
    }
    Ok(())
}

fn usize_to_u64(value: usize) -> Result<u64, DurableLedgerError> {
    u64::try_from(value).map_err(|_| DurableLedgerError::InvalidLimit)
}

fn u64_to_usize(value: u64) -> Result<usize, DurableLedgerError> {
    usize::try_from(value).map_err(|_| DurableLedgerError::InvalidLimit)
}

fn advance_digest(previous: Digest32, bytes: &[u8]) -> Digest32 {
    let mut framed = Vec::with_capacity(CHECKPOINT_CHUNK_DOMAIN.len() + 32 + 8 + bytes.len());
    framed.extend_from_slice(CHECKPOINT_CHUNK_DOMAIN);
    framed.extend_from_slice(previous.as_array());
    framed.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    framed.extend_from_slice(bytes);
    Digest32::of_bytes(&framed)
}

struct CheckpointWriter<'a> {
    file: &'a mut File,
    digest: Digest32,
}

impl<'a> CheckpointWriter<'a> {
    fn new(file: &'a mut File) -> Self {
        Self {
            file,
            digest: Digest32::of_bytes(CHECKPOINT_DIGEST_DOMAIN),
        }
    }

    fn bytes(&mut self, bytes: &[u8]) -> Result<(), DurableLedgerError> {
        self.file.write_all(bytes)?;
        self.digest = advance_digest(self.digest, bytes);
        Ok(())
    }

    fn byte(&mut self, value: u8) -> Result<(), DurableLedgerError> {
        self.bytes(&[value])
    }

    fn u16(&mut self, value: u16) -> Result<(), DurableLedgerError> {
        self.bytes(&value.to_be_bytes())
    }

    fn u64(&mut self, value: u64) -> Result<(), DurableLedgerError> {
        self.bytes(&value.to_be_bytes())
    }

    fn count(&mut self, value: usize) -> Result<(), DurableLedgerError> {
        self.u64(usize_to_u64(value)?)
    }

    fn digest(&mut self, value: Digest32) -> Result<(), DurableLedgerError> {
        self.bytes(value.as_array())
    }

    fn anchor(&mut self, value: LedgerAnchor) -> Result<(), DurableLedgerError> {
        self.u64(value.sequence)?;
        self.digest(value.chain_digest)
    }

    fn id(&mut self, value: &StableId) -> Result<(), DurableLedgerError> {
        let bytes = value.as_str().as_bytes();
        let length = u16::try_from(bytes.len()).map_err(|_| DurableLedgerError::Corrupt)?;
        self.u16(length)?;
        self.bytes(bytes)
    }

    const fn state_digest(&self) -> Digest32 {
        self.digest
    }
}

struct CheckpointReader<'a> {
    file: &'a mut File,
    digest: Digest32,
}

impl<'a> CheckpointReader<'a> {
    fn new(file: &'a mut File) -> Self {
        Self {
            file,
            digest: Digest32::of_bytes(CHECKPOINT_DIGEST_DOMAIN),
        }
    }

    fn bytes(&mut self, length: usize) -> Result<Vec<u8>, DurableLedgerError> {
        let mut bytes = vec![0; length];
        self.file.read_exact(&mut bytes)?;
        self.digest = advance_digest(self.digest, &bytes);
        Ok(bytes)
    }

    fn array<const N: usize>(&mut self) -> Result<[u8; N], DurableLedgerError> {
        self.bytes(N)?
            .try_into()
            .map_err(|_| DurableLedgerError::Corrupt)
    }

    fn byte(&mut self) -> Result<u8, DurableLedgerError> {
        Ok(self.array::<1>()?[0])
    }

    fn u16(&mut self) -> Result<u16, DurableLedgerError> {
        Ok(u16::from_be_bytes(self.array()?))
    }

    fn u64(&mut self) -> Result<u64, DurableLedgerError> {
        Ok(u64::from_be_bytes(self.array()?))
    }

    fn count(&mut self, maximum: u64) -> Result<usize, DurableLedgerError> {
        let value = self.u64()?;
        if value > maximum {
            return Err(DurableLedgerError::Corrupt);
        }
        u64_to_usize(value)
    }

    fn digest(&mut self) -> Result<Digest32, DurableLedgerError> {
        Ok(Digest32::from_array(self.array()?))
    }

    fn raw_digest(&mut self) -> Result<Digest32, DurableLedgerError> {
        let mut value = [0; 32];
        self.file.read_exact(&mut value)?;
        Ok(Digest32::from_array(value))
    }

    fn anchor(&mut self) -> Result<LedgerAnchor, DurableLedgerError> {
        Ok(LedgerAnchor {
            sequence: self.u64()?,
            chain_digest: self.digest()?,
        })
    }

    fn id(&mut self) -> Result<StableId, DurableLedgerError> {
        let length = usize::from(self.u16()?);
        if !(1..=128).contains(&length) {
            return Err(DurableLedgerError::Corrupt);
        }
        let bytes = self.bytes(length)?;
        let value = std::str::from_utf8(&bytes).map_err(|_| DurableLedgerError::Corrupt)?;
        StableId::new(value).map_err(|_| DurableLedgerError::Corrupt)
    }

    const fn state_digest(&self) -> Digest32 {
        self.digest
    }
}

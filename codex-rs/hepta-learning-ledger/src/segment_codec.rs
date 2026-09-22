//! Private V2 segment framing; V1 journals and event identities stay unchanged.

use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;

use crate::AppendDisposition;
use crate::DurableLedgerError;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerRecord;
use crate::LedgerRecovery;
use crate::LedgerSegmentLimits;
use crate::durable_codec::FRAME_OVERHEAD;
use crate::durable_codec::MAX_EVENT;
use crate::durable_codec::decode_event;
use crate::durable_codec::encode_frame;
use crate::ledger::digest_chain;
use crate::ledger::digest_event;
use crate::segments::current_anchor;

pub(crate) const HEADER: usize = 136;
pub(crate) const FOOTER: usize = 80;
const MAGIC: &[u8; 8] = b"HEPTLS02";

pub(crate) struct Parsed {
    pub(crate) length: u64,
    pub(crate) cursor: u64,
    pub(crate) sealed: bool,
}

fn header(
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    prior: LedgerAnchor,
) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
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

pub(crate) fn initialize(
    file: &mut File,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    prior: LedgerAnchor,
) -> Result<(), DurableLedgerError> {
    if file.metadata()?.len() != 0 {
        return Err(DurableLedgerError::AlreadyInitialized);
    }
    let bytes = header(binding, limits, index, prior);
    file.seek(SeekFrom::Start(0))?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| DurableLedgerError::Indeterminate)
}

pub(crate) fn footer(binding: Digest32, index: usize, anchor: LedgerAnchor) -> Vec<u8> {
    let mut bytes = vec![0, 0, 0, 0, 255, 255, 255, 255];
    bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(anchor.chain_digest.as_array());
    let mut seal_bytes = b"hepta.learning-ledger.segment-seal.v2\0".to_vec();
    seal_bytes.extend_from_slice(binding.as_array());
    seal_bytes.extend_from_slice(&(index as u64).to_be_bytes());
    seal_bytes.extend_from_slice(&bytes);
    bytes.extend_from_slice(Digest32::of_bytes(&seal_bytes).as_array());
    bytes
}

pub(crate) fn replay(
    file: &mut File,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    prior: LedgerAnchor,
    core: &mut LearningLedger,
) -> Result<Parsed, DurableLedgerError> {
    let length = file.metadata()?.len();
    if length < HEADER as u64 {
        return Err(DurableLedgerError::MissingHeader);
    }
    if length > limits.bytes {
        return Err(DurableLedgerError::Capacity);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut stored = [0; HEADER];
    file.read_exact(&mut stored)?;
    if stored.as_slice() != header(binding, limits, index, prior) {
        return Err(DurableLedgerError::BindingMismatch);
    }
    let mut cursor = HEADER as u64;
    let mut sealed = false;
    while cursor < length {
        if length - cursor < 8 {
            break;
        }
        let mut prefix = [0; 8];
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
            if length - cursor < FOOTER as u64 {
                break;
            }
            let mut bytes = [0; FOOTER];
            bytes[..8].copy_from_slice(&prefix);
            file.read_exact(&mut bytes[8..])?;
            if current_anchor(core).sequence == prior.sequence
                || bytes.as_slice() != footer(binding, index, current_anchor(core))
                || cursor + FOOTER as u64 != length
            {
                return Err(DurableLedgerError::Corrupt);
            }
            cursor += FOOTER as u64;
            sealed = true;
            break;
        }
        let total = size as usize + FRAME_OVERHEAD;
        if length - cursor < total as u64 {
            break;
        }
        if core.records().len() as u64 - prior.sequence >= limits.records as u64
            || cursor + total as u64 + FOOTER as u64 > limits.bytes
        {
            return Err(DurableLedgerError::Capacity);
        }
        let mut frame = vec![0; total];
        frame[..8].copy_from_slice(&prefix);
        file.read_exact(&mut frame[8..])?;
        if Digest32::of_bytes(&frame[..total - 32])
            .as_array()
            .as_slice()
            != &frame[total - 32..]
        {
            return Err(DurableLedgerError::Corrupt);
        }
        let event = decode_event(&frame[48..48 + size as usize])?;
        let prepared = core
            .prepare(event)
            .map_err(|_| DurableLedgerError::Corrupt)?;
        if prepared.disposition != AppendDisposition::Appended
            || encode_frame(&prepared.record)? != frame
        {
            return Err(DurableLedgerError::Corrupt);
        }
        core.apply(prepared)
            .map_err(|_| DurableLedgerError::Corrupt)?;
        cursor += total as u64;
    }
    Ok(Parsed {
        length,
        cursor,
        sealed,
    })
}

pub(crate) fn read_record_at_sequence(
    file: &mut File,
    binding: Digest32,
    limits: LedgerSegmentLimits,
    index: usize,
    prior: LedgerAnchor,
    target_sequence: u64,
) -> Result<Option<LedgerRecord>, DurableLedgerError> {
    let length = file.metadata()?.len();
    if length < (HEADER + FOOTER) as u64 || length > limits.bytes {
        return Err(DurableLedgerError::Corrupt);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut stored_header = [0; HEADER];
    file.read_exact(&mut stored_header)?;
    if stored_header.as_slice() != header(binding, limits, index, prior) {
        return Err(DurableLedgerError::BindingMismatch);
    }

    let mut cursor = HEADER as u64;
    let mut current = prior;
    let mut record_count = 0usize;
    let mut found = None;
    while cursor < length {
        if length - cursor < 8 {
            return Err(DurableLedgerError::IncompleteTail);
        }
        let mut prefix = [0; 8];
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
            if length - cursor != FOOTER as u64 || current.sequence == prior.sequence {
                return Err(DurableLedgerError::Corrupt);
            }
            let mut bytes = [0; FOOTER];
            bytes[..8].copy_from_slice(&prefix);
            file.read_exact(&mut bytes[8..])?;
            if bytes.as_slice() != footer(binding, index, current) {
                return Err(DurableLedgerError::Corrupt);
            }
            return Ok(found);
        }

        record_count = record_count
            .checked_add(1)
            .ok_or(DurableLedgerError::Capacity)?;
        if record_count > limits.records {
            return Err(DurableLedgerError::Capacity);
        }
        let total = size as usize + FRAME_OVERHEAD;
        if length - cursor < total as u64 || cursor + total as u64 + FOOTER as u64 > limits.bytes {
            return Err(DurableLedgerError::IncompleteTail);
        }
        let mut frame = vec![0; total];
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
        if sequence_value == target_sequence {
            found = Some(record.clone());
        }
        current = LedgerAnchor {
            sequence: sequence_value,
            chain_digest,
        };
        cursor += total as u64;
    }
    Err(DurableLedgerError::IncompleteTail)
}

pub(crate) fn validate_anchor(
    core: &LearningLedger,
    recovery: LedgerRecovery,
) -> Result<(), DurableLedgerError> {
    if let LedgerRecovery::Acknowledged(anchor) = recovery {
        if anchor.sequence == 0 || anchor.sequence > 1_000_000 || anchor.chain_digest.is_zero() {
            return Err(DurableLedgerError::InvalidAnchor);
        }
        let record = core
            .records()
            .get((anchor.sequence - 1) as usize)
            .ok_or(DurableLedgerError::AcknowledgedHistoryMissing)?;
        if record.chain_digest != anchor.chain_digest {
            return Err(DurableLedgerError::AnchorMismatch);
        }
    }
    Ok(())
}

pub(crate) struct SharedSegment(pub(crate) File);
impl SharedSegment {
    pub(crate) fn acquire(file: File) -> Result<Self, DurableLedgerError> {
        if !file.metadata()?.is_file() {
            return Err(DurableLedgerError::NotRegular);
        }
        match file.try_lock_shared() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableLedgerError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
impl Drop for SharedSegment {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

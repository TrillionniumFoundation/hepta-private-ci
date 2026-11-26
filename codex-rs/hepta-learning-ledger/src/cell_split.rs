//! Durable learning-ledger owner for DecisionCell split lifecycle facts.
//!
//! The regular causal ledger owns decisions and outcomes.  Cell-split lifecycle
//! transitions are an owner-local automation fact, so they use a dedicated
//! append-only domain with the same fsync + independent-witness contract as the
//! production learning ledger.  The adapter is intentionally typed: callers
//! cannot append arbitrary bytes or rewrite an existing split transition.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerWitnessFrontier;
use crate::LedgerWitnessStore;
use crate::durable_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HEPTCSL1";
const HEADER: usize = 72;
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 4096;
const MAX_ROLE_QUALIFICATION_PAYLOAD_BYTES: usize = 16 * 1024;
const DOMAIN_EVENT: &[u8] = b"hepta.learning-ledger.cell-split.event.v1";
const DOMAIN_CHAIN: &[u8] = b"hepta.learning-ledger.cell-split.chain.v1";

/// One immutable lifecycle fact emitted by the cell-split automation owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitLifecycleRecordV1 {
    pub record_id: StableId,
    pub split_id: StableId,
    pub lifecycle_sequence: u64,
    pub from_state: u8,
    pub to_state: u8,
    pub evidence_digest: Digest32,
    pub state_digest: Digest32,
    pub taskflow_event_digest: Digest32,
    pub support_digest: Digest32,
    /// Canonical, typed role-qualification/evaluator evidence attached to the
    /// lifecycle transition.  The ledger does not interpret this payload; the
    /// higher-level role owner validates and replays it.  Keeping the bounded
    /// payload in the witnessed frame prevents a durable owner from reducing a
    /// role receipt to an unverifiable digest-only reference.
    pub role_qualification_payload: Vec<u8>,
}

impl CellSplitLifecycleRecordV1 {
    fn validate(&self) -> Result<(), DurableLedgerError> {
        if self.record_id.as_str().is_empty() || self.split_id.as_str().is_empty() {
            return Err(DurableLedgerError::InvalidBinding);
        }
        if self.record_id.as_str().len() > MAX_ID_BYTES
            || self.split_id.as_str().len() > MAX_ID_BYTES
        {
            return Err(DurableLedgerError::Capacity);
        }
        if self.from_state > 7 || self.to_state > 7 {
            return Err(DurableLedgerError::Corrupt);
        }
        for digest in [
            self.evidence_digest,
            self.state_digest,
            self.taskflow_event_digest,
            self.support_digest,
        ] {
            if digest.is_zero() {
                return Err(DurableLedgerError::InvalidBinding);
            }
        }
        if self.role_qualification_payload.len() > MAX_ROLE_QUALIFICATION_PAYLOAD_BYTES {
            return Err(DurableLedgerError::Capacity);
        }
        Ok(())
    }

    fn canonical_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(256);
        bytes.extend_from_slice(DOMAIN_EVENT);
        push_id(&mut bytes, &self.record_id);
        push_id(&mut bytes, &self.split_id);
        bytes.extend_from_slice(&self.lifecycle_sequence.to_be_bytes());
        bytes.push(self.from_state);
        bytes.push(self.to_state);
        bytes.extend_from_slice(self.evidence_digest.as_array());
        bytes.extend_from_slice(self.state_digest.as_array());
        bytes.extend_from_slice(self.taskflow_event_digest.as_array());
        bytes.extend_from_slice(self.support_digest.as_array());
        bytes.extend_from_slice(
            &u32::try_from(self.role_qualification_payload.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&self.role_qualification_payload);
        bytes
    }

    fn legacy_canonical_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(256);
        bytes.extend_from_slice(DOMAIN_EVENT);
        push_id(&mut bytes, &self.record_id);
        push_id(&mut bytes, &self.split_id);
        bytes.extend_from_slice(&self.lifecycle_sequence.to_be_bytes());
        bytes.push(self.from_state);
        bytes.push(self.to_state);
        bytes.extend_from_slice(self.evidence_digest.as_array());
        bytes.extend_from_slice(self.state_digest.as_array());
        bytes.extend_from_slice(self.taskflow_event_digest.as_array());
        bytes.extend_from_slice(self.support_digest.as_array());
        bytes
    }
}

/// Result of one witnessed append.  `IdempotentReplay` means the exact record
/// was already committed and witnessed; no new frame was written.
pub type CellSplitLifecycleAppendReceiptV1 = AppendReceipt;

/// Durable, single-writer cell-split lifecycle ledger.
pub struct CellSplitLearningLedgerV1 {
    file: LockedFile,
    witness: LedgerWitnessStore,
    binding: Digest32,
    records: Vec<StoredRecord>,
    durable_length: u64,
    max_records: usize,
    poisoned: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct StoredRecord {
    sequence: u64,
    predecessor_chain_digest: Digest32,
    event_digest: Digest32,
    chain_digest: Digest32,
    event: CellSplitLifecycleRecordV1,
}

impl CellSplitLearningLedgerV1 {
    /// Create empty paired ledger and witness files.  The host owns file and
    /// directory authorization; this owner fsyncs both before acknowledgement.
    pub fn create(
        file: File,
        witness_file: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, DurableLedgerError> {
        validate_domain(binding, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized);
        }
        write_header(&mut file, binding)?;
        let witness = LedgerWitnessStore::create(witness_file, binding)?;
        Ok(Self {
            file,
            witness,
            binding,
            records: Vec::new(),
            durable_length: HEADER as u64,
            max_records,
            poisoned: false,
        })
    }

    /// Recover both sides and require the independent witness to equal the
    /// durable lifecycle head.  A ledger-ahead/witness-behind split is rejected
    /// for reconciliation instead of being silently acknowledged.
    pub fn recover(
        file: File,
        witness_file: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, DurableLedgerError> {
        validate_domain(binding, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        let (records, cursor) = replay_frames(&mut file, binding, max_records)?;
        let witness = LedgerWitnessStore::recover(witness_file, binding)?;
        let expected = anchor_for_records(&records);
        let actual = witness.frontier()?.anchor;
        if expected != actual {
            return Err(DurableLedgerError::UnwitnessedTail);
        }
        if cursor != file.metadata()?.len() {
            file.set_len(cursor)
                .and_then(|()| file.sync_all())
                .map_err(|_| DurableLedgerError::Indeterminate)?;
        }
        Ok(Self {
            file,
            witness,
            binding,
            records,
            durable_length: cursor,
            max_records,
            poisoned: false,
        })
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding
    }

    pub fn records(&self) -> Result<Vec<CellSplitLifecycleRecordV1>, DurableLedgerError> {
        if self.poisoned {
            return Err(DurableLedgerError::Poisoned);
        }
        Ok(self
            .records
            .iter()
            .map(|record| record.event.clone())
            .collect())
    }

    pub fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        if self.poisoned {
            return Err(DurableLedgerError::Poisoned);
        }
        Ok(anchor_for_records(&self.records))
    }

    pub fn witness_frontier(&self) -> Result<LedgerWitnessFrontier, DurableLedgerError> {
        self.witness.frontier()
    }

    /// Append one event after checking the exact predecessor and advancing the
    /// independent witness.  Equal retries return an idempotent receipt.
    pub fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: CellSplitLifecycleRecordV1,
    ) -> Result<CellSplitLifecycleAppendReceiptV1, DurableLedgerError> {
        if self.poisoned {
            return Err(DurableLedgerError::Poisoned);
        }
        event.validate()?;
        let event_digest = Digest32::of_bytes(&event.canonical_bytes());
        if let Some(existing) = self
            .records
            .iter()
            .find(|record| record.event.record_id == event.record_id)
        {
            if existing.event_digest != event_digest {
                return Err(DurableLedgerError::Conflict);
            }
            return Ok(AppendReceipt {
                disposition: AppendDisposition::IdempotentReplay,
                sequence: LogicalSequence::new(existing.sequence)
                    .map_err(|_| DurableLedgerError::Capacity)?,
                event_digest,
                chain_digest: existing.chain_digest,
            });
        }
        if self.records.len() >= self.max_records {
            return Err(DurableLedgerError::Capacity);
        }
        let predecessor = self
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        if predecessor != expected_predecessor {
            return Err(DurableLedgerError::Conflict);
        }
        let sequence = u64::try_from(self.records.len())
            .map_err(|_| DurableLedgerError::Capacity)?
            .checked_add(1)
            .ok_or(DurableLedgerError::Capacity)?;
        let chain_digest = digest_chain(predecessor, sequence, event_digest);
        let stored = StoredRecord {
            sequence,
            predecessor_chain_digest: predecessor,
            event_digest,
            chain_digest,
            event,
        };
        let frame = encode_frame(&stored)?;
        let next_length = self
            .durable_length
            .checked_add(u64::try_from(frame.len()).map_err(|_| DurableLedgerError::Capacity)?)
            .ok_or(DurableLedgerError::Capacity)?;
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(DurableLedgerError::Corrupt);
        }
        self.file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        let expected_frontier = self.witness.frontier()?;
        let next_frontier = LedgerWitnessFrontier {
            anchor: LedgerAnchor {
                sequence,
                chain_digest,
            },
            segment: expected_frontier.segment,
            sealed: expected_frontier.sealed,
        };
        self.witness.advance(expected_frontier, next_frontier)?;
        self.records.push(stored);
        self.durable_length = next_length;
        self.poisoned = false;
        Ok(AppendReceipt {
            disposition: AppendDisposition::Appended,
            sequence: LogicalSequence::new(sequence).map_err(|_| DurableLedgerError::Capacity)?,
            event_digest,
            chain_digest,
        })
    }
}

fn validate_domain(binding: Digest32, max_records: usize) -> Result<(), DurableLedgerError> {
    if binding.is_zero() {
        return Err(DurableLedgerError::InvalidBinding);
    }
    if max_records == 0 {
        return Err(DurableLedgerError::Capacity);
    }
    Ok(())
}

fn write_header(file: &mut LockedFile, binding: Digest32) -> Result<(), DurableLedgerError> {
    let mut header = MAGIC.to_vec();
    header.extend_from_slice(binding.as_array());
    header.extend_from_slice(Digest32::of_bytes(&header).as_array());
    file.write_all(&header)
        .and_then(|()| file.sync_all())
        .map_err(|_| DurableLedgerError::Indeterminate)
}

fn replay_frames(
    file: &mut LockedFile,
    binding: Digest32,
    max_records: usize,
) -> Result<(Vec<StoredRecord>, u64), DurableLedgerError> {
    let length = file.metadata()?.len();
    if length < HEADER as u64 {
        return Err(DurableLedgerError::MissingHeader);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut header = [0_u8; HEADER];
    file.read_exact(&mut header)?;
    if &header[..8] != MAGIC
        || &header[8..40] != binding.as_array()
        || Digest32::of_bytes(&header[..40]).as_array() != &header[40..]
    {
        return Err(DurableLedgerError::BindingMismatch);
    }
    let mut records = Vec::new();
    let mut cursor = HEADER as u64;
    while cursor < length {
        let frame_len = read_u32(file)? as usize;
        if !(64..=MAX_FRAME_BYTES).contains(&frame_len) || cursor + 4 + frame_len as u64 > length {
            return Err(DurableLedgerError::IncompleteTail);
        }
        let mut frame = vec![0_u8; frame_len];
        file.read_exact(&mut frame)?;
        let stored = decode_frame(&frame)?;
        if stored.sequence != records.len() as u64 + 1
            || stored.predecessor_chain_digest
                != records
                    .last()
                    .map_or(Digest32::ZERO, |row: &StoredRecord| row.chain_digest)
            || stored.chain_digest
                != digest_chain(
                    stored.predecessor_chain_digest,
                    stored.sequence,
                    stored.event_digest,
                )
            || !event_digest_matches_replay_format(&stored.event, stored.event_digest)
        {
            return Err(DurableLedgerError::Corrupt);
        }
        if records
            .iter()
            .any(|row: &StoredRecord| row.event.record_id == stored.event.record_id)
        {
            return Err(DurableLedgerError::Corrupt);
        }
        if records.len() >= max_records {
            return Err(DurableLedgerError::Capacity);
        }
        records.push(stored);
        cursor += 4 + frame_len as u64;
    }
    Ok((records, cursor))
}

fn event_digest_matches_replay_format(
    event: &CellSplitLifecycleRecordV1,
    event_digest: Digest32,
) -> bool {
    if event_digest == Digest32::of_bytes(&event.canonical_bytes()) {
        return true;
    }
    // HEPTCSL1 frames written before the typed role payload extension omitted
    // the zero-length payload marker from the event digest.  Accept that exact
    // legacy digest only for an empty payload; all new payload-bearing frames
    // must use the extended canonical form above.
    event.role_qualification_payload.is_empty()
        && event_digest == Digest32::of_bytes(&event.legacy_canonical_bytes())
}

fn encode_frame(record: &StoredRecord) -> Result<Vec<u8>, DurableLedgerError> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&record.sequence.to_be_bytes());
    bytes.extend_from_slice(record.predecessor_chain_digest.as_array());
    bytes.extend_from_slice(record.event_digest.as_array());
    bytes.extend_from_slice(record.chain_digest.as_array());
    push_id(&mut bytes, &record.event.record_id);
    push_id(&mut bytes, &record.event.split_id);
    bytes.extend_from_slice(&record.event.lifecycle_sequence.to_be_bytes());
    bytes.push(record.event.from_state);
    bytes.push(record.event.to_state);
    bytes.extend_from_slice(record.event.evidence_digest.as_array());
    bytes.extend_from_slice(record.event.state_digest.as_array());
    bytes.extend_from_slice(record.event.taskflow_event_digest.as_array());
    bytes.extend_from_slice(record.event.support_digest.as_array());
    let payload_len = u32::try_from(record.event.role_qualification_payload.len())
        .map_err(|_| DurableLedgerError::Capacity)?;
    bytes.extend_from_slice(&payload_len.to_be_bytes());
    bytes.extend_from_slice(&record.event.role_qualification_payload);
    if bytes.len() > MAX_FRAME_BYTES - 32 {
        return Err(DurableLedgerError::Capacity);
    }
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    let length = u32::try_from(bytes.len()).map_err(|_| DurableLedgerError::Capacity)?;
    let mut frame = length.to_be_bytes().to_vec();
    frame.extend_from_slice(&bytes);
    Ok(frame)
}

fn decode_frame(input: &[u8]) -> Result<StoredRecord, DurableLedgerError> {
    if input.len() < 8 * 4 + 2 * 4 + 8 + 2 + 32 * 5 + 32 {
        return Err(DurableLedgerError::Corrupt);
    }
    let checksum_at = input.len() - 32;
    if Digest32::of_bytes(&input[..checksum_at]).as_array() != &input[checksum_at..] {
        return Err(DurableLedgerError::Corrupt);
    }
    let mut cursor = 0;
    let sequence = take_u64(input, &mut cursor)?;
    let predecessor_chain_digest = take_digest(input, &mut cursor)?;
    let event_digest = take_digest(input, &mut cursor)?;
    let chain_digest = take_digest(input, &mut cursor)?;
    let record_id = take_id(input, &mut cursor)?;
    let split_id = take_id(input, &mut cursor)?;
    let lifecycle_sequence = take_u64(input, &mut cursor)?;
    let from_state = take_byte(input, &mut cursor)?;
    let to_state = take_byte(input, &mut cursor)?;
    let evidence_digest = take_digest(input, &mut cursor)?;
    let state_digest = take_digest(input, &mut cursor)?;
    let taskflow_event_digest = take_digest(input, &mut cursor)?;
    let support_digest = take_digest(input, &mut cursor)?;
    let payload_len = if checksum_at == cursor {
        // Frames written before the typed role-qualification payload extension
        // remain readable and are treated as having no attached payload.
        0
    } else {
        take_u32(input, &mut cursor)? as usize
    };
    if payload_len > MAX_ROLE_QUALIFICATION_PAYLOAD_BYTES {
        return Err(DurableLedgerError::Capacity);
    }
    let payload_end = cursor
        .checked_add(payload_len)
        .ok_or(DurableLedgerError::Corrupt)?;
    let role_qualification_payload = input
        .get(cursor..payload_end)
        .ok_or(DurableLedgerError::Corrupt)?
        .to_vec();
    cursor = payload_end;
    if cursor != checksum_at {
        return Err(DurableLedgerError::Corrupt);
    }
    let event = CellSplitLifecycleRecordV1 {
        record_id,
        split_id,
        lifecycle_sequence,
        from_state,
        to_state,
        evidence_digest,
        state_digest,
        taskflow_event_digest,
        support_digest,
        role_qualification_payload,
    };
    event.validate()?;
    Ok(StoredRecord {
        sequence,
        predecessor_chain_digest,
        event_digest,
        chain_digest,
        event,
    })
}

fn anchor_for_records(records: &[StoredRecord]) -> LedgerAnchor {
    records.last().map_or(
        LedgerAnchor {
            sequence: 0,
            chain_digest: Digest32::ZERO,
        },
        |record| LedgerAnchor {
            sequence: record.sequence,
            chain_digest: record.chain_digest,
        },
    )
}

fn digest_chain(predecessor: Digest32, sequence: u64, event_digest: Digest32) -> Digest32 {
    let mut bytes = Vec::with_capacity(DOMAIN_CHAIN.len() + 72);
    bytes.extend_from_slice(DOMAIN_CHAIN);
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(event_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let id = value.as_str().as_bytes();
    bytes.extend_from_slice(&(id.len() as u32).to_be_bytes());
    bytes.extend_from_slice(id);
}

fn read_u32(file: &mut LockedFile) -> Result<u32, DurableLedgerError> {
    let mut bytes = [0_u8; 4];
    file.read_exact(&mut bytes)?;
    Ok(u32::from_be_bytes(bytes))
}

fn take_u64(input: &[u8], cursor: &mut usize) -> Result<u64, DurableLedgerError> {
    let end = cursor.checked_add(8).ok_or(DurableLedgerError::Corrupt)?;
    let bytes = input.get(*cursor..end).ok_or(DurableLedgerError::Corrupt)?;
    *cursor = end;
    Ok(u64::from_be_bytes(
        bytes.try_into().map_err(|_| DurableLedgerError::Corrupt)?,
    ))
}

fn take_byte(input: &[u8], cursor: &mut usize) -> Result<u8, DurableLedgerError> {
    let byte = *input.get(*cursor).ok_or(DurableLedgerError::Corrupt)?;
    *cursor += 1;
    Ok(byte)
}

fn take_digest(input: &[u8], cursor: &mut usize) -> Result<Digest32, DurableLedgerError> {
    let end = cursor.checked_add(32).ok_or(DurableLedgerError::Corrupt)?;
    let bytes = input.get(*cursor..end).ok_or(DurableLedgerError::Corrupt)?;
    *cursor = end;
    Ok(Digest32::from_array(
        bytes.try_into().map_err(|_| DurableLedgerError::Corrupt)?,
    ))
}

fn take_id(input: &[u8], cursor: &mut usize) -> Result<StableId, DurableLedgerError> {
    let length = take_u32(input, cursor)? as usize;
    if length == 0 || length > MAX_ID_BYTES {
        return Err(DurableLedgerError::Corrupt);
    }
    let end = cursor
        .checked_add(length)
        .ok_or(DurableLedgerError::Corrupt)?;
    let bytes = input.get(*cursor..end).ok_or(DurableLedgerError::Corrupt)?;
    *cursor = end;
    let text = std::str::from_utf8(bytes).map_err(|_| DurableLedgerError::Corrupt)?;
    StableId::new(text).map_err(|_| DurableLedgerError::Corrupt)
}

fn take_u32(input: &[u8], cursor: &mut usize) -> Result<u32, DurableLedgerError> {
    let end = cursor.checked_add(4).ok_or(DurableLedgerError::Corrupt)?;
    let bytes = input.get(*cursor..end).ok_or(DurableLedgerError::Corrupt)?;
    *cursor = end;
    Ok(u32::from_be_bytes(
        bytes.try_into().map_err(|_| DurableLedgerError::Corrupt)?,
    ))
}

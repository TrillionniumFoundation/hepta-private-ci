//! Independently anchored checkpoints for bounded tail-only attempt recovery.
//!
//! A checkpoint is not trusted because it is checksummed. Its exact canonical
//! bytes and the journal frontier they summarize are retained by an independent,
//! authenticated authority outside the journal backup domain. Recovery restores
//! the checkpointed reducer state and replays only the later journal tail.

use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use super::*;

const CHECKPOINT_MAGIC: &[u8; 8] = b"HEPTACP1";
const MAX_CHECKPOINT_BYTES: u64 = MAX_BYTES;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CheckpointRecord {
    binding: Digest32,
    event_count: u64,
    journal_byte_len: u64,
    journal_state_digest: Digest32,
    snapshot_digest: Digest32,
    checkpoint_digest: Digest32,
}

impl CheckpointRecord {
    fn validate(&self) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        if self.binding.is_zero()
            || self.journal_byte_len < HEADER
            || self.journal_state_digest.is_zero()
            || self.snapshot_digest.is_zero()
            || self.checkpoint_digest != checkpoint_record_digest(self)
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        Ok(())
    }
}

impl LockedFileProductEvaluationAttemptJournalV1 {
    /// Write one immutable canonical reducer snapshot and retain its identity in
    /// an independent authority. The live journal is not modified or truncated.
    pub fn checkpoint_into<A: ProductEvaluationAttemptAnchorStoreV1>(
        &self,
        mut target: File,
        authority: &mut A,
    ) -> Result<ProductEvaluationAttemptAnchorV1, ProductEvaluationAttemptJournalErrorV1> {
        let anchor = self.anchor()?;
        acquire_checkpoint(&target)?;
        if target.metadata().map_err(io_error)?.len() != 0 {
            return Err(ProductEvaluationAttemptJournalErrorV1::AlreadyInitialized);
        }
        let snapshot = encode_snapshot(&self.attempts)?;
        if snapshot.is_empty() || snapshot.len() as u64 > MAX_CHECKPOINT_BYTES {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        let snapshot_digest = Digest32::of_bytes(&snapshot);
        let mut record = CheckpointRecord {
            binding: self.binding,
            event_count: anchor.event_count,
            journal_byte_len: self.length,
            journal_state_digest: anchor.state_digest,
            snapshot_digest,
            checkpoint_digest: Digest32::ZERO,
        };
        record.checkpoint_digest = checkpoint_record_digest(&record);
        record.validate()?;
        let bytes = encode_checkpoint_file(record, &snapshot);
        if bytes.len() as u64 > MAX_CHECKPOINT_BYTES {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        target.seek(SeekFrom::Start(0)).map_err(io_error)?;
        target
            .write_all(&bytes)
            .and_then(|()| target.sync_all())
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Indeterminate)?;

        let checkpoint_anchor = ProductEvaluationAttemptAnchorV1 {
            binding: checkpoint_binding(self.binding),
            event_count: record.event_count,
            state_digest: record.checkpoint_digest,
        };
        let expected = authority.load(checkpoint_anchor.binding)?;
        if let Some(previous) = expected {
            if previous.binding != checkpoint_anchor.binding
                || previous.state_digest.is_zero()
                || previous.event_count > checkpoint_anchor.event_count
                || (previous.event_count == checkpoint_anchor.event_count
                    && previous != checkpoint_anchor)
            {
                return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
            }
            if previous == checkpoint_anchor {
                return Ok(checkpoint_anchor);
            }
        }
        match authority.compare_and_swap(checkpoint_anchor.binding, expected, checkpoint_anchor) {
            Ok(()) => Ok(checkpoint_anchor),
            Err(
                error @ (ProductEvaluationAttemptJournalErrorV1::Conflict
                | ProductEvaluationAttemptJournalErrorV1::Indeterminate),
            ) => {
                if authority.load(checkpoint_anchor.binding)? == Some(checkpoint_anchor) {
                    Ok(checkpoint_anchor)
                } else {
                    Err(error)
                }
            }
            Err(error) => Err(error),
        }
    }

    /// Restore an independently authenticated reducer snapshot and replay only
    /// the append-only journal tail after its exact byte frontier.
    pub fn recover_with_checkpoint<A: ProductEvaluationAttemptAnchorStoreV1>(
        mut file: File,
        mut checkpoint: File,
        binding: Digest32,
        minimum: ProductEvaluationAttemptAnchorV1,
        authority: &mut A,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        if minimum.binding != binding || minimum.state_digest.is_zero() {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        acquire(&file, binding)?;
        acquire_checkpoint(&checkpoint)?;
        let checkpoint_binding = checkpoint_binding(binding);
        let retained = authority
            .load(checkpoint_binding)?
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Binding)?;
        if retained.binding != checkpoint_binding
            || retained.state_digest.is_zero()
            || retained.event_count > minimum.event_count
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        let checkpoint_len = checkpoint.metadata().map_err(io_error)?.len();
        if checkpoint_len == 0 || checkpoint_len > MAX_CHECKPOINT_BYTES {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        checkpoint.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut checkpoint_bytes = Vec::with_capacity(checkpoint_len as usize);
        checkpoint
            .read_to_end(&mut checkpoint_bytes)
            .map_err(io_error)?;
        let (record, snapshot) = decode_checkpoint_file(&checkpoint_bytes)?;
        if record.binding != binding
            || record.event_count != retained.event_count
            || record.checkpoint_digest != retained.state_digest
            || Digest32::of_bytes(snapshot) != record.snapshot_digest
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }

        let length = file.metadata().map_err(io_error)?.len();
        if length > MAX_BYTES {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        if length < record.journal_byte_len || record.journal_byte_len < HEADER {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut header = [0_u8; HEADER as usize];
        file.read_exact(&mut header).map_err(io_error)?;
        if &header[..8] != MAGIC
            || &header[8..40] != binding.as_array()
            || &header[40..] != Digest32::of_bytes(&header[..40]).as_array()
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }

        let (mut attempts, mut plan_owners, mut capacity, snapshot_events) =
            decode_snapshot(snapshot)?;
        if snapshot_events != retained.event_count {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        let mut cursor = record.journal_byte_len;
        let mut event_count = usize::try_from(retained.event_count)
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
        let mut state_digest = record.journal_state_digest;
        let mut anchor_seen = minimum.event_count == retained.event_count
            && minimum.state_digest == record.journal_state_digest;
        file.seek(SeekFrom::Start(cursor)).map_err(io_error)?;
        while cursor < length {
            if length - cursor < 4 || event_count >= MAX_EVENTS {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let mut raw = [0_u8; 4];
            file.read_exact(&mut raw).map_err(io_error)?;
            let count = u32::from_be_bytes(raw) as usize;
            if !(1..=MAX_FRAME).contains(&count) || length - cursor - 4 < count as u64 + 32 {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let mut payload = vec![0_u8; count];
            let mut checksum = [0_u8; 32];
            file.read_exact(&mut payload)
                .and_then(|()| file.read_exact(&mut checksum))
                .map_err(io_error)?;
            if &checksum != Digest32::of_bytes(&payload).as_array() {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let transition = decode_transition(&payload)?;
            let (receipt, appended) = preview_transition(&attempts, &plan_owners, transition)?;
            if !appended {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let previous = attempts
                .get(&receipt.transition.attempt_id)
                .and_then(|events| events.last())
                .map(|event| event.transition.phase);
            let reservation = capacity.project(previous, &receipt.transition)?;
            install_transition(&mut attempts, &mut plan_owners, &receipt);
            capacity.install(reservation, &receipt.transition);
            event_count += 1;
            state_digest = advance_digest(state_digest, event_count, &payload);
            if minimum.event_count == event_count as u64 {
                anchor_seen = minimum.state_digest == state_digest;
            }
            cursor += 4 + count as u64 + 32;
        }
        if !anchor_seen || file.metadata().map_err(io_error)?.len() != length {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        Ok(Self {
            file,
            binding,
            attempts,
            plan_owners,
            capacity,
            length,
            event_count,
            state_digest,
            poisoned: false,
        })
    }
}

fn encode_snapshot(
    attempts: &AttemptEvents,
) -> Result<Vec<u8>, ProductEvaluationAttemptJournalErrorV1> {
    let attempt_count = u32::try_from(attempts.len())
        .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    let mut output = attempt_count.to_be_bytes().to_vec();
    for (attempt_id, events) in attempts {
        put_id(&mut output, attempt_id)?;
        let count = u16::try_from(events.len())
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
        output.extend_from_slice(&count.to_be_bytes());
        for event in events {
            event.validate_integrity()?;
            let payload = encode_transition(&event.transition)?;
            let length = u32::try_from(payload.len())
                .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
            output.extend_from_slice(&length.to_be_bytes());
            output.extend_from_slice(&payload);
        }
    }
    Ok(output)
}

fn decode_snapshot(
    bytes: &[u8],
) -> Result<
    (
        AttemptEvents,
        BTreeMap<[u8; 32], StableId>,
        AttemptCapacity,
        u64,
    ),
    ProductEvaluationAttemptJournalErrorV1,
> {
    let mut input = Input::new(bytes);
    let attempt_count = input.u32()? as usize;
    let mut attempts = AttemptEvents::new();
    let mut plan_owners = BTreeMap::new();
    let mut capacity = AttemptCapacity::default();
    let mut event_count = 0_u64;
    for _ in 0..attempt_count {
        let attempt_id = input.id()?;
        let events = input.u16()? as usize;
        if events == 0 {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        for _ in 0..events {
            let length = input.u32()? as usize;
            if !(1..=MAX_FRAME).contains(&length) {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let transition = decode_transition(input.take(length)?)?;
            if transition.attempt_id != attempt_id {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let (receipt, appended) = preview_transition(&attempts, &plan_owners, transition)?;
            if !appended {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let previous = attempts
                .get(&receipt.transition.attempt_id)
                .and_then(|history| history.last())
                .map(|event| event.transition.phase);
            let reservation = capacity.project(previous, &receipt.transition)?;
            install_transition(&mut attempts, &mut plan_owners, &receipt);
            capacity.install(reservation, &receipt.transition);
            event_count = event_count
                .checked_add(1)
                .ok_or(ProductEvaluationAttemptJournalErrorV1::Capacity)?;
        }
    }
    if !input.done() {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    Ok((attempts, plan_owners, capacity, event_count))
}

fn encode_checkpoint_file(record: CheckpointRecord, snapshot: &[u8]) -> Vec<u8> {
    let mut output = Vec::with_capacity(8 + 32 * 5 + 24 + snapshot.len());
    output.extend_from_slice(CHECKPOINT_MAGIC);
    output.extend_from_slice(record.binding.as_array());
    output.extend_from_slice(&record.event_count.to_be_bytes());
    output.extend_from_slice(&record.journal_byte_len.to_be_bytes());
    output.extend_from_slice(record.journal_state_digest.as_array());
    output.extend_from_slice(record.snapshot_digest.as_array());
    output.extend_from_slice(&(snapshot.len() as u64).to_be_bytes());
    output.extend_from_slice(snapshot);
    output.extend_from_slice(record.checkpoint_digest.as_array());
    output
}

fn decode_checkpoint_file(
    bytes: &[u8],
) -> Result<(CheckpointRecord, &[u8]), ProductEvaluationAttemptJournalErrorV1> {
    let mut input = Input::new(bytes);
    if input.take(CHECKPOINT_MAGIC.len())? != CHECKPOINT_MAGIC {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    let binding = input.digest()?;
    let event_count = input.u64()?;
    let journal_byte_len = input.u64()?;
    let journal_state_digest = input.digest()?;
    let snapshot_digest = input.digest()?;
    let snapshot_len = usize::try_from(input.u64()?)
        .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    let snapshot = input.take(snapshot_len)?;
    let checkpoint_digest = input.digest()?;
    if !input.done() {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    let record = CheckpointRecord {
        binding,
        event_count,
        journal_byte_len,
        journal_state_digest,
        snapshot_digest,
        checkpoint_digest,
    };
    record.validate()?;
    if Digest32::of_bytes(snapshot) != snapshot_digest {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    Ok((record, snapshot))
}

fn checkpoint_record_digest(record: &CheckpointRecord) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.learning-eval.attempt-checkpoint.v1",
        record.binding.as_array(),
        &record.event_count.to_be_bytes(),
        &record.journal_byte_len.to_be_bytes(),
        record.journal_state_digest.as_array(),
        record.snapshot_digest.as_array(),
    ])
}

fn checkpoint_binding(binding: Digest32) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.learning-eval.attempt-checkpoint-binding.v1",
        binding.as_array(),
    ])
}

fn put_id(
    output: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
    let bytes = value.as_str().as_bytes();
    let length =
        u16::try_from(bytes.len()).map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(bytes);
    Ok(())
}

fn acquire_checkpoint(file: &File) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
    if !file.metadata().map_err(io_error)?.file_type().is_file() {
        return Err(ProductEvaluationAttemptJournalErrorV1::NotRegular);
    }
    match file.try_lock() {
        Ok(()) => Ok(()),
        Err(TryLockError::WouldBlock) => Err(ProductEvaluationAttemptJournalErrorV1::Busy),
        Err(TryLockError::Error(error)) => Err(io_error(error)),
    }
}

struct Input<'a> {
    bytes: &'a [u8],
    cursor: usize,
}

impl<'a> Input<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, cursor: 0 }
    }

    fn take(&mut self, count: usize) -> Result<&'a [u8], ProductEvaluationAttemptJournalErrorV1> {
        let end = self
            .cursor
            .checked_add(count)
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
        let value = self
            .bytes
            .get(self.cursor..end)
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
        self.cursor = end;
        Ok(value)
    }

    fn u16(&mut self) -> Result<u16, ProductEvaluationAttemptJournalErrorV1> {
        let mut raw = [0_u8; 2];
        raw.copy_from_slice(self.take(2)?);
        Ok(u16::from_be_bytes(raw))
    }

    fn u32(&mut self) -> Result<u32, ProductEvaluationAttemptJournalErrorV1> {
        let mut raw = [0_u8; 4];
        raw.copy_from_slice(self.take(4)?);
        Ok(u32::from_be_bytes(raw))
    }

    fn u64(&mut self) -> Result<u64, ProductEvaluationAttemptJournalErrorV1> {
        let mut raw = [0_u8; 8];
        raw.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(raw))
    }

    fn digest(&mut self) -> Result<Digest32, ProductEvaluationAttemptJournalErrorV1> {
        let mut raw = [0_u8; 32];
        raw.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(raw))
    }

    fn id(&mut self) -> Result<StableId, ProductEvaluationAttemptJournalErrorV1> {
        let length = self.u16()? as usize;
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
        StableId::new(value).map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)
    }

    fn done(&self) -> bool {
        self.cursor == self.bytes.len()
    }
}

#[cfg(test)]
#[path = "attempt_checkpoint_tests.rs"]
mod tests;

//! Pure, bounded transport of complete ledger content. No I/O or authority.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::AppendDisposition;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::durable_codec::FRAME_OVERHEAD;
use crate::durable_codec::MAX_EVENT;
use crate::durable_codec::decode_event;
use crate::durable_codec::encode_frame;

/// Maximum complete encoded snapshot, including this codec's header.
///
/// Any containing control message must still enforce its own total byte limit,
/// including encoding overhead and all other fields.
pub const MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1: usize = 64 * 1024;

const DOMAIN: &[u8] = b"hepta.learning-ledger.snapshot.v1";
const HEADER_BYTES: usize = DOMAIN.len() + 4 + 32;
const MAX_RECORDS: usize =
    (MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1 - HEADER_BYTES) / FRAME_OVERHEAD;

/// Invalid, oversized, or semantically inconsistent snapshot content.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OriginalLedgerSnapshotCodecErrorV1 {
    Capacity,
    Corrupt,
    Semantic(LedgerError),
}

impl fmt::Display for OriginalLedgerSnapshotCodecErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl Error for OriginalLedgerSnapshotCodecErrorV1 {}

use OriginalLedgerSnapshotCodecErrorV1 as CodecError;

/// Encode every original record and the head after exact ledger replay.
///
/// Frames use the existing durable canonical event/frame encoding, without
/// changing or manufacturing a durable file header. This verifies content only:
/// callers must independently authenticate the freeze signature, preheld trust,
/// source, task, plan, and contract before admitting the returned content.
pub fn encode_original_ledger_snapshot_v1(
    snapshot: &LedgerSnapshot,
) -> Result<Vec<u8>, OriginalLedgerSnapshotCodecErrorV1> {
    if snapshot.records().len() > MAX_RECORDS {
        return Err(CodecError::Capacity);
    }
    let count = u32::try_from(snapshot.records().len()).map_err(|_| CodecError::Capacity)?;
    let mut output = Vec::with_capacity(MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1);
    output.extend_from_slice(DOMAIN);
    output.extend_from_slice(&count.to_be_bytes());
    output.extend_from_slice(snapshot.head_digest.as_array());
    let mut core = LearningLedger::new();
    for record in snapshot.records() {
        // Bound every variable collection before cloning or encoding an
        // untrusted in-memory event. StableId itself bounds each scalar string.
        let bounded = match &record.event {
            LedgerEvent::Decision(value) => value.candidate_ids.len() <= 128,
            LedgerEvent::AuthenticatedDecisionV2(value) => value.candidate_ids.len() <= 128,
            LedgerEvent::RetrievalAssignment(value) => {
                value.enumerated_candidate_digests.len() <= 512
                    && value.legal_candidate_indices.len() <= 512
                    && value.selected_candidate_indices.len() <= 16
                    && value.delivered_candidate_indices.len() <= 16
            }
            LedgerEvent::CreditBatchV2(value) => value.allocations.len() <= 256,
            LedgerEvent::Outcome(_)
            | LedgerEvent::Credit(_)
            | LedgerEvent::PromptDelivery(_)
            | LedgerEvent::Revocation(_)
            | LedgerEvent::AuthenticatedOutcomeV2(_)
            | LedgerEvent::UnlearningLineageV1(_) => true,
        };
        if !bounded {
            return Err(CodecError::Capacity);
        }
        let prepared = core
            .prepare(record.event.clone())
            .map_err(CodecError::Semantic)?;
        if prepared.disposition != AppendDisposition::Appended || &prepared.record != record {
            return Err(CodecError::Corrupt);
        }
        let frame = encode_frame(&prepared.record).map_err(|_| CodecError::Capacity)?;
        let next_length = output
            .len()
            .checked_add(frame.len())
            .ok_or(CodecError::Capacity)?;
        if next_length > MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1 {
            return Err(CodecError::Capacity);
        }
        core.apply(prepared).map_err(CodecError::Semantic)?;
        output.extend_from_slice(&frame);
    }
    if core.snapshot().head_digest != snapshot.head_digest {
        return Err(CodecError::Corrupt);
    }
    Ok(output)
}

/// Decode a complete snapshot by bounded canonical parsing and ledger replay.
///
/// No tail recovery, normalization of the wire representation, partial history,
/// or duplicate record is accepted. The result contains all original records;
/// it does not authenticate their signatures or confer any writer or execution
/// authority. A containing control message retains its separate aggregate cap.
pub fn decode_original_ledger_snapshot_v1(
    input: &[u8],
) -> Result<LedgerSnapshot, OriginalLedgerSnapshotCodecErrorV1> {
    if input.len() > MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1 {
        return Err(CodecError::Capacity);
    }
    let (header, mut remaining) = input
        .split_at_checked(HEADER_BYTES)
        .ok_or(CodecError::Corrupt)?;
    if &header[..DOMAIN.len()] != DOMAIN {
        return Err(CodecError::Corrupt);
    }
    let count = u32::from_be_bytes(
        header[DOMAIN.len()..DOMAIN.len() + 4]
            .try_into()
            .map_err(|_| CodecError::Corrupt)?,
    );
    let count = usize::try_from(count).map_err(|_| CodecError::Capacity)?;
    if count > MAX_RECORDS {
        return Err(CodecError::Capacity);
    }
    if count > remaining.len() / FRAME_OVERHEAD {
        return Err(CodecError::Corrupt);
    }
    let head = Digest32::from_array(
        header[DOMAIN.len() + 4..]
            .try_into()
            .map_err(|_| CodecError::Corrupt)?,
    );
    // Never reserve storage using the claimed record count.
    let mut core = LearningLedger::new();
    for _ in 0..count {
        let prefix = remaining.get(..8).ok_or(CodecError::Corrupt)?;
        let size = u32::from_be_bytes(
            prefix[..4]
                .try_into()
                .map_err(|_| CodecError::Corrupt)?,
        );
        let complement = u32::from_be_bytes(
            prefix[4..]
                .try_into()
                .map_err(|_| CodecError::Corrupt)?,
        );
        if size != !complement || size == 0 {
            return Err(CodecError::Corrupt);
        }
        let size = usize::try_from(size).map_err(|_| CodecError::Capacity)?;
        if size > MAX_EVENT {
            return Err(CodecError::Capacity);
        }
        let total = size.checked_add(FRAME_OVERHEAD).ok_or(CodecError::Capacity)?;
        let (frame, tail) = remaining
            .split_at_checked(total)
            .ok_or(CodecError::Corrupt)?;
        if Digest32::of_bytes(&frame[..total - 32]).as_array() != &frame[total - 32..] {
            return Err(CodecError::Corrupt);
        }
        let event = decode_event(&frame[48..48 + size]).map_err(|_| CodecError::Corrupt)?;
        let prepared = core.prepare(event).map_err(CodecError::Semantic)?;
        if prepared.disposition != AppendDisposition::Appended
            || encode_frame(&prepared.record)
                .map_err(|_| CodecError::Corrupt)?
                .as_slice()
                != frame
        {
            return Err(CodecError::Corrupt);
        }
        core.apply(prepared).map_err(CodecError::Semantic)?;
        remaining = tail;
    }
    if !remaining.is_empty() {
        return Err(CodecError::Corrupt);
    }
    let snapshot = core.snapshot();
    if snapshot.head_digest != head {
        return Err(CodecError::Corrupt);
    }
    Ok(snapshot)
}

#[cfg(test)]
#[path = "snapshot_codec_tests.rs"]
mod tests;

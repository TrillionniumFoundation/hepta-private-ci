//! Verify the original journal bytes summarized by an authenticated checkpoint.
//! This performs one bounded streaming hash pass, without replaying reducer state.
use super::*;

pub(super) fn verify(
    file: &mut File,
    header: &[u8],
    record: CheckpointRecord,
) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
    if record.event_count > MAX_EVENTS as u64 {
        return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
    }
    file.seek(SeekFrom::Start(HEADER)).map_err(io_error)?;
    let mut cursor = HEADER;
    let mut count = 0usize;
    let mut state_digest = Digest32::of_bytes(header);
    while cursor < record.journal_byte_len {
        let remaining = record.journal_byte_len - cursor;
        if remaining < 4 || count >= MAX_EVENTS {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        let mut raw = [0_u8; 4];
        file.read_exact(&mut raw).map_err(io_error)?;
        let length = u32::from_be_bytes(raw) as usize;
        if !(1..=MAX_FRAME).contains(&length) || remaining - 4 < length as u64 + 32 {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        let mut payload = vec![0_u8; length];
        let mut checksum = [0_u8; 32];
        file.read_exact(&mut payload)
            .and_then(|()| file.read_exact(&mut checksum))
            .map_err(io_error)?;
        if &checksum != Digest32::of_bytes(&payload).as_array() {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        count += 1;
        state_digest = advance_digest(state_digest, count, &payload);
        cursor += 4 + length as u64 + 32;
    }
    if count as u64 != record.event_count || state_digest != record.journal_state_digest {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    Ok(())
}

//! Strict ordinary witness replay. No writer recovery, repair or cached frontier.

use super::*;

pub(crate) fn inspect_ordinary_witness(
    bytes: &[u8],
    binding: Digest32,
    max_records: usize,
) -> Result<LedgerWitnessFrontier, DurableLedgerError> {
    validate_binding(binding)?;
    if !(1..=8192).contains(&max_records) {
        return Err(DurableLedgerError::InvalidLimit);
    }
    if bytes.len() < HEADER {
        return Err(DurableLedgerError::MissingHeader);
    }
    if bytes.len() > HEADER + FRAME * max_records {
        return Err(DurableLedgerError::Capacity);
    }
    let header = &bytes[..HEADER];
    if &header[..8] != MAGIC
        || &header[8..40] != binding.as_array()
        || Digest32::of_bytes(&header[..40]).as_array() != &header[40..]
    {
        return Err(DurableLedgerError::BindingMismatch);
    }
    if !(bytes.len() - HEADER).is_multiple_of(FRAME) {
        return Err(DurableLedgerError::IncompleteTail);
    }
    let mut frontier = LedgerWitnessFrontier::empty();
    for frame in bytes[HEADER..].chunks_exact(FRAME) {
        if Digest32::of_bytes(&frame[..FRAME - 32]).as_array() != &frame[FRAME - 32..] {
            return Err(DurableLedgerError::Corrupt);
        }
        let next = decode_frontier(&frame[..FRAME - 32])?;
        // This view deliberately has no segmented/rotation recovery semantics.
        // Every record, including the final one, must have an ordinary witness.
        if next.segment.is_some() || next.sealed {
            return Err(DurableLedgerError::InvalidAnchor);
        }
        validate_advance(frontier, next)?;
        if encode_frontier(next)? != frame {
            return Err(DurableLedgerError::Corrupt);
        }
        frontier = next;
    }
    Ok(frontier)
}

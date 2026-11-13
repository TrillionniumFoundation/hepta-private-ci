//! Shared canonical frame decoder. It never repairs bytes or checks authority.
use super::*;
use crate::cell_journal_codec::apply_record;

pub(super) struct ParsedCellImage {
    pub(super) owner: CellPartitionOwnerV1,
    pub(super) offset: usize,
    pub(super) head: Option<JournalAnchor>,
    pub(super) witnessed: bool,
}

pub(super) fn parse_original_cell_image(
    bytes: &[u8],
    header: &[u8],
    specs: &[CellJournalPartitionV1],
    max_records: usize,
    expected: Option<JournalAnchor>,
) -> Result<ParsedCellImage, CellExecutionError> {
    if bytes.len() < HEADER_BYTES
        || bytes.len() as u64 > MAX_JOURNAL_BYTES
        || bytes[..HEADER_BYTES] != *header
    {
        return Err(CellExecutionError::JournalCorrupt);
    }
    let mut owner = initial_owner(specs)?;
    let mut offset = HEADER_BYTES;
    let mut head = None;
    let mut count = 0;
    let mut witnessed = expected.is_none();
    while offset < bytes.len() {
        if bytes.len() - offset < 4 {
            break;
        }
        let size = u32::from_be_bytes(
            bytes[offset..offset + 4]
                .try_into()
                .map_err(|_| CellExecutionError::JournalCorrupt)?,
        ) as usize;
        if size == 0 || size > MAX_FRAME_BYTES {
            return Err(CellExecutionError::JournalCorrupt);
        }
        let end = offset
            .checked_add(4 + size + 32)
            .ok_or(CellExecutionError::JournalCorrupt)?;
        if end > bytes.len() {
            break;
        }
        count += 1;
        if count > max_records {
            return Err(CellExecutionError::CapacityExceeded);
        }
        let payload = &bytes[offset + 4..end - 32];
        let anchor = next_anchor(header, head, payload)?;
        if anchor.checkpoint_digest.as_array() != &bytes[end - 32..end] {
            return Err(CellExecutionError::JournalCorrupt);
        }
        apply_record(payload, specs, &mut owner)?;
        if expected == Some(anchor) {
            witnessed = true;
        }
        head = Some(anchor);
        offset = end;
    }
    Ok(ParsedCellImage {
        owner,
        offset,
        head,
        witnessed,
    })
}

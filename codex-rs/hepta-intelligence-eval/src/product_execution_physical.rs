//! Shared original HEPTEX01 grammar and bounded physical image observation.
//! Callers retain the appropriate original lock for both complete reads.

use super::*;

pub(super) struct Replay {
    pub(super) records: BTreeMap<StableId, (Digest32, State)>,
    pub(super) anchor: ProductEvaluationExecutionAnchorV1,
}

pub(super) fn read_stable_image(file: &mut File) -> Result<Vec<u8>, FileError> {
    let mut previous = None;
    for _ in 0..2 {
        let metadata = file.metadata().map_err(io_error)?;
        if !metadata.is_file() {
            return Err(FileError::NotRegular);
        }
        let length = metadata.len();
        if length > MAX_FILE_BYTES {
            return Err(FileError::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut *file)
            .take(MAX_FILE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != length
            || file.metadata().map_err(io_error)?.len() != length
            || previous.as_ref().is_some_and(|original| original != &bytes)
        {
            return Err(FileError::Indeterminate);
        }
        previous = Some(bytes);
    }
    previous.ok_or(FileError::Indeterminate)
}

pub(super) fn replay_image(
    bytes: &[u8],
    binding: Digest32,
    minimum: ProductEvaluationExecutionAnchorV1,
) -> Result<Replay, FileError> {
    if bytes.len() < HEADER {
        return Err(FileError::MissingHeader);
    }
    if &bytes[..8] != MAGIC
        || &bytes[8..40] != binding.as_array()
        || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
    {
        return Err(FileError::Corrupt);
    }
    let mut anchor = ProductEvaluationExecutionAnchorV1 {
        sequence: 0,
        history_digest: Digest32::of_bytes(&bytes[..HEADER]),
    };
    let mut records = BTreeMap::new();
    let mut witnessed = anchor == minimum;
    let mut remaining = &bytes[HEADER..];
    while !remaining.is_empty() {
        let raw: [u8; 4] = take(&mut remaining, 4)?
            .try_into()
            .map_err(|_| FileError::Corrupt)?;
        let count = u32::from_be_bytes(raw) as usize;
        if !(36..=MAX_FRAME).contains(&count) {
            return Err(FileError::Capacity);
        }
        let payload = take(&mut remaining, count)?;
        let checksum = take(&mut remaining, 32)?;
        let next = next_anchor(anchor, payload)?;
        if checksum != next.history_digest.as_array() {
            return Err(FileError::Corrupt);
        }
        replay(&mut records, payload)?;
        anchor = next;
        witnessed |= anchor == minimum;
    }
    if !witnessed {
        return Err(FileError::Rollback);
    }
    Ok(Replay { records, anchor })
}

//! Full physical CURRENT from the original locked final-holdout file.
//! No cached record, replacement handle, minimum-anchor repair or effect occurs.

use super::*;

pub(super) struct PhysicalCurrent {
    pub(super) bytes: Vec<u8>,
    pub(super) state: Option<FinalHoldoutCasRecordV1>,
    pub(super) history_digest: Digest32,
}

pub(super) fn read_physical(
    file: &mut File,
    binding: Digest32,
    minimum: Option<FinalHoldoutCasAnchorV1>,
) -> Result<PhysicalCurrent, LockedFileCasErrorV1> {
    let original_position = file.stream_position().map_err(io_error)?;
    let result = (|| {
        let length = file.metadata().map_err(io_error)?.len();
        if length > MAX_BYTES {
            return Err(LockedFileCasErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut *file)
            .take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 > MAX_BYTES {
            return Err(LockedFileCasErrorV1::Capacity);
        }
        if bytes.len() as u64 != length || file.metadata().map_err(io_error)?.len() != length {
            return Err(LockedFileCasErrorV1::Corrupt);
        }
        Ok(bytes)
    })();
    // Restore even when the actual read failed. An unknown restoration result
    // is an I/O failure; the live store permanently fences every such failure.
    file.seek(SeekFrom::Start(original_position))
        .map_err(io_error)?;
    let bytes = result?;
    let state = replay(&bytes, binding, minimum)?;
    let history_digest = Digest32::of_parts(&[
        b"hepta.intelligence-eval.locked-holdout-current.v1\0",
        binding.as_array(),
        &bytes,
    ]);
    Ok(PhysicalCurrent {
        bytes,
        state,
        history_digest,
    })
}

fn replay(
    bytes: &[u8],
    binding: Digest32,
    minimum: Option<FinalHoldoutCasAnchorV1>,
) -> Result<Option<FinalHoldoutCasRecordV1>, LockedFileCasErrorV1> {
    if bytes.len() < HEADER {
        return Err(LockedFileCasErrorV1::MissingHeader);
    }
    if &bytes[..8] != MAGIC
        || &bytes[8..40] != binding.as_array()
        || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
    {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    let mut state: Option<FinalHoldoutCasRecordV1> = None;
    let mut minimum_witnessed = minimum.is_none();
    let mut cursor = HEADER;
    while cursor < bytes.len() {
        let raw = bytes
            .get(cursor..cursor + 4)
            .ok_or(LockedFileCasErrorV1::Corrupt)?;
        let count = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]) as usize;
        if !(1..=MAX_FRAME).contains(&count) {
            return Err(LockedFileCasErrorV1::Capacity);
        }
        cursor += 4;
        let payload = bytes
            .get(cursor..cursor + count)
            .ok_or(LockedFileCasErrorV1::Corrupt)?;
        cursor += count;
        let checksum = bytes
            .get(cursor..cursor + 32)
            .ok_or(LockedFileCasErrorV1::Corrupt)?;
        cursor += 32;
        if checksum != Digest32::of_bytes(payload).as_array() {
            return Err(LockedFileCasErrorV1::Corrupt);
        }
        state = Some(replay_event(binding, state, payload)?);
        if minimum.is_some_and(|anchor| {
            state
                .as_ref()
                .is_some_and(|record| record_anchor(record) == anchor)
        }) {
            minimum_witnessed = true;
        }
    }
    validate_minimum(state.as_ref(), minimum, minimum_witnessed)?;
    Ok(state)
}

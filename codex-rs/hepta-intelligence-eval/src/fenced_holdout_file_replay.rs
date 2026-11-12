//! One physical image grammar for recovery and every live CAS observation.
//! These reads do not repair, truncate, reopen paths or create a new writer.

use super::*;

pub(super) fn read_stable_image(file: &mut HeldFile) -> Result<Vec<u8>, LockedFileCasErrorV1> {
    let first = read_image(file)?;
    if read_image(file)? != first {
        return Err(LockedFileCasErrorV1::Indeterminate);
    }
    Ok(first)
}

fn read_image(file: &mut HeldFile) -> Result<Vec<u8>, LockedFileCasErrorV1> {
    let length = file.metadata().map_err(io_error)?.len();
    if length > MAX_BYTES {
        return Err(LockedFileCasErrorV1::Capacity);
    }
    file.seek(SeekFrom::Start(0)).map_err(io_error)?;
    let mut bytes = Vec::new();
    (&mut **file)
        .take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(io_error)?;
    if bytes.len() as u64 != length || file.metadata().map_err(io_error)?.len() != length {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    Ok(bytes)
}

pub(super) fn replay_image(
    bytes: &[u8],
    binding: Digest32,
    minimum: Option<FinalHoldoutCasAnchorV1>,
) -> Result<Option<FinalHoldoutCasRecordV1>, LockedFileCasErrorV1> {
    if bytes.len() < HEADER {
        return Err(LockedFileCasErrorV1::MissingHeader);
    }
    if bytes.len() as u64 > MAX_BYTES {
        return Err(LockedFileCasErrorV1::Capacity);
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

//! One framing, checksum, canonical record and chain parser for the owner and
//! physical readers. The owner alone decides whether to truncate a partial tail.

use super::*;

pub(super) struct ReplayedRunStartFrames {
    pub(super) records: Vec<StoredRunStart>,
    pub(super) by_run: BTreeMap<StableId, usize>,
    pub(super) valid_length: u64,
    pub(super) observed_length: u64,
    pub(super) frame_ranges: Vec<(u64, u64)>,
}

pub(super) fn replay_frames(
    file: &mut File,
    binding: Digest32,
    max_records: usize,
) -> Result<ReplayedRunStarts, RunStartStoreError> {
    let length = file.metadata()?.len();
    let replay = replay_reader(file, binding, max_records, length)?;
    drop(replay.frame_ranges);
    Ok((
        replay.records,
        replay.by_run,
        replay.valid_length,
        replay.observed_length,
    ))
}

pub(super) fn replay_reader(
    file: &mut (impl Read + Seek),
    binding: Digest32,
    max_records: usize,
    length: u64,
) -> Result<ReplayedRunStartFrames, RunStartStoreError> {
    if length < HEADER as u64 {
        return Err(RunStartStoreError::MissingHeader);
    }
    if length > MAX_FILE_BYTES {
        return Err(RunStartStoreError::Capacity);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut header = [0_u8; HEADER];
    file.read_exact(&mut header)?;
    if &header[..8] != MAGIC || Digest32::of_bytes(&header[..40]).as_array() != &header[40..] {
        return Err(RunStartStoreError::Corrupt);
    }
    if &header[8..40] != binding.as_array() {
        return Err(RunStartStoreError::BindingMismatch);
    }

    let mut records = Vec::new();
    let mut frame_ranges = Vec::new();
    let mut by_run = BTreeMap::new();
    let mut cursor = HEADER as u64;
    while cursor < length {
        if length - cursor < 8 {
            break;
        }
        let mut prefix = [0_u8; 8];
        file.read_exact(&mut prefix)?;
        let size = u32::from_be_bytes(
            prefix[..4]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        ) as usize;
        let complement = u32::from_be_bytes(
            prefix[4..]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        if size == 0 || (size as u32) != !complement || size > MAX_RUN_START_PAYLOAD_BYTES {
            return Err(RunStartStoreError::Corrupt);
        }
        let total = size + FRAME_OVERHEAD;
        if length - cursor < total as u64 {
            break;
        }
        if records.len() >= max_records {
            return Err(RunStartStoreError::Capacity);
        }
        let mut frame = vec![0_u8; total];
        frame[..8].copy_from_slice(&prefix);
        file.read_exact(&mut frame[8..])?;
        if Digest32::of_bytes(&frame[..total - 32]).as_array() != &frame[total - 32..] {
            return Err(RunStartStoreError::Corrupt);
        }
        let sequence = u64::from_be_bytes(
            frame[8..16]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        if sequence != records.len() as u64 + 1 {
            return Err(RunStartStoreError::Corrupt);
        }
        let predecessor = Digest32::from_array(
            frame[16..48]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        let expected_predecessor = records
            .last()
            .map_or(Digest32::ZERO, |value: &StoredRunStart| value.chain_digest);
        if predecessor != expected_predecessor {
            return Err(RunStartStoreError::Corrupt);
        }
        let payload_end = 48 + size;
        let record = decode_outcome_record(&frame[48..payload_end])?;
        if by_run.contains_key(record.run_id()) {
            return Err(RunStartStoreError::Corrupt);
        }
        let record_digest = Digest32::of_bytes(&frame[48..payload_end]);
        let chain_digest = Digest32::from_array(
            frame[payload_end..payload_end + 32]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        if chain_digest != digest_chain(predecessor, sequence, record_digest) {
            return Err(RunStartStoreError::Corrupt);
        }
        let index = records.len();
        by_run.insert(record.run_id().clone(), index);
        records.push(StoredRunStart {
            sequence,
            predecessor_chain_digest: predecessor,
            record_digest,
            chain_digest,
            record,
        });
        frame_ranges.push((cursor, cursor + total as u64));
        cursor += total as u64;
    }
    Ok(ReplayedRunStartFrames {
        records,
        by_run,
        valid_length: cursor,
        observed_length: length,
        frame_ranges,
    })
}

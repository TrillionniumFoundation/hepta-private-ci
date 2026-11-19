//! Read an existing physical witness with the original codec. This observer
//! acquires no writer lock and never initializes, repairs, syncs or advances it.

use std::os::unix::fs::FileExt;

use super::*;

/// Observe the original physical witness codec without taking its writer lock.
/// Returned data is not independent evidence that this cut was acknowledged;
/// the calling owner must bind it to its separately retained trust and scope.
pub fn read_original_file(
    file: &File,
    scope: JournalScope,
    generation: Generation,
    max_records: usize,
) -> Result<Option<JournalAnchor>, WitnessStoreError> {
    if !(1..=MAX_RECORDS).contains(&max_records) {
        return Err(WitnessStoreError::InvalidLimit);
    }
    if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
        return Err(WitnessStoreError::ContextMismatch);
    }
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(WitnessStoreError::NotRegular);
    }
    let length = metadata.len();
    if length < HEADER as u64 || !(length - HEADER as u64).is_multiple_of(RECORD as u64) {
        return Err(WitnessStoreError::Corrupt);
    }
    let records = ((length - HEADER as u64) / RECORD as u64) as usize;
    if records > max_records {
        return Err(WitnessStoreError::Capacity);
    }
    let mut header = [0; HEADER];
    file.read_exact_at(&mut header, 0)?;
    if header != encode_header(scope, generation) {
        return Err(WitnessStoreError::ContextMismatch);
    }
    let mut current = None;
    let mut raw = [0; RECORD];
    for index in 0..records {
        file.read_exact_at(&mut raw, (HEADER + index * RECORD) as u64)?;
        let (expected, next) = decode_record(&raw)?;
        if expected != current || !is_successor(expected, next) {
            return Err(WitnessStoreError::Corrupt);
        }
        current = Some(next);
    }
    Ok(current)
}

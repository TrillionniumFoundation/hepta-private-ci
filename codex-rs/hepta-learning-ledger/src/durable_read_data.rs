//! Pure canonical transport data from an already observed ordinary Ledger.
//! No file, writer, recovery, witness or authority is created here. Root keeps
//! physical observation inside its refusal domain; the recipient's actual
//! same-Root receipt, not these bytes or their cut, authorizes a learning read.

use super::*;

pub fn encode_readonly_ledger_data_v1(
    binding: Digest32,
    records: &[LedgerRecord],
) -> Result<Vec<u8>, DurableLedgerError> {
    validate_domain(binding, records.len())?;
    let head_digest = records
        .last()
        .ok_or(DurableLedgerError::InvalidAnchor)?
        .chain_digest;
    LearningLedger::from_snapshot(LedgerSnapshot {
        records: records.to_vec(),
        head_digest,
    })
    .map_err(DurableLedgerError::Semantic)?;
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(binding.as_array());
    let header_digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(header_digest.as_array());
    for record in records {
        let frame = encode_frame(record)?;
        if bytes
            .len()
            .checked_add(frame.len())
            .is_none_or(|size| size as u64 > MAX_BYTES)
        {
            return Err(DurableLedgerError::Capacity);
        }
        bytes.extend_from_slice(&frame);
    }
    Ok(bytes)
}

pub fn decode_readonly_ledger_data_v1(
    bytes: &[u8],
    expected: LedgerReadOnlyCutV1,
    max_records: usize,
) -> Result<LedgerSnapshot, DurableLedgerError> {
    validate_domain(expected.binding, max_records)?;
    let recovery = LedgerRecovery::Acknowledged(expected.frontier.anchor);
    validate_recovery(recovery, max_records)?;
    if expected.frontier.segment.is_some() || expected.frontier.sealed {
        return Err(DurableLedgerError::InvalidAnchor);
    }
    if bytes.len() as u64 != expected.ledger_length
        || bytes.len() as u64 > MAX_BYTES
        || Digest32::of_bytes(bytes) != expected.ledger_digest
    {
        return Err(DurableLedgerError::Corrupt);
    }
    let (core, cursor, length) = replay_reader(
        &mut io::Cursor::new(bytes),
        expected.binding,
        max_records,
        recovery,
        bytes.len() as u64,
    )?;
    if cursor != length {
        return Err(DurableLedgerError::IncompleteTail);
    }
    if core.records().len() as u64 != expected.frontier.anchor.sequence {
        return Err(DurableLedgerError::UnwitnessedTail);
    }
    let snapshot = core.snapshot();
    if encode_readonly_ledger_data_v1(expected.binding, snapshot.records())? != bytes {
        return Err(DurableLedgerError::Corrupt);
    }
    Ok(snapshot)
}

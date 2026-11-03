//! Original run-owner cancellation and terminal decisions, in its existing journal.
//!
//! These immutable facts block restoration of execution eligibility. They are
//! neither execution grants nor a second cancellation or authorization owner.

use super::*;

pub(super) const CANCELLATION_DOMAIN: &[u8] = b"hepta.run-cancellation-record.v1";
pub(super) const CLOSED_DOMAIN: &[u8] = b"hepta.run-closed-record.v1";
const MAX_CANCEL_REASON_BYTES: usize = 512;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunCancellationRecordV1 {
    pub run_id: StableId,
    pub run_start_record_digest: Digest32,
    pub revision: u64,
    pub cancel_reason: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RunClosedPhaseV1 {
    Cancelled,
    Succeeded,
    Failed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunClosedRecordV1 {
    pub run_id: StableId,
    pub run_start_record_digest: Digest32,
    pub closed_revision: u64,
    pub phase: RunClosedPhaseV1,
    pub cancel_reason: Option<String>,
}

impl DurableRunStartJournal {
    /// Persist the original control owner's accepted cancellation before its ACK.
    /// Exact retries retain the first decision and do not advance the journal.
    pub fn append_cancellation(
        &mut self,
        expected_predecessor: Digest32,
        record: RunCancellationRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        validate_cancellation(&record)?;
        self.append_outcome(
            expected_predecessor,
            StoredRunStartRecord::Cancellation(Box::new(record)),
        )
    }

    /// Persist the original terminal decision before ACK or removal from memory.
    /// A prior cancellation, if present, remains in the same original hash chain.
    pub fn append_closed(
        &mut self,
        expected_predecessor: Digest32,
        record: RunClosedRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        validate_closed(&record)?;
        self.append_outcome(
            expected_predecessor,
            StoredRunStartRecord::Closed(Box::new(record)),
        )
    }

    pub fn cancellation(
        &self,
        run_id: &StableId,
    ) -> Result<Option<&RunCancellationRecordV1>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        let Some(index) = self.by_run.get(run_id).and_then(|value| value.cancellation) else {
            return Ok(None);
        };
        let stored = self.records.get(index).ok_or(RunStartStoreError::Corrupt)?;
        let StoredRunStartRecord::Cancellation(record) = &stored.record else {
            return Err(RunStartStoreError::Corrupt);
        };
        validate_append(&self.records, &self.by_run, &stored.record)?;
        Ok(Some(record))
    }

    pub fn closed(
        &self,
        run_id: &StableId,
    ) -> Result<Option<&RunClosedRecordV1>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        let Some(index) = self.by_run.get(run_id).and_then(|value| value.closed) else {
            return Ok(None);
        };
        let stored = self.records.get(index).ok_or(RunStartStoreError::Corrupt)?;
        let StoredRunStartRecord::Closed(record) = &stored.record else {
            return Err(RunStartStoreError::Corrupt);
        };
        validate_append(&self.records, &self.by_run, &stored.record)?;
        Ok(Some(record))
    }
}

fn valid_reason(reason: &str) -> bool {
    !reason.trim().is_empty()
        && reason.len() <= MAX_CANCEL_REASON_BYTES
        && !reason.as_bytes().contains(&0)
}

fn validate_cancellation(record: &RunCancellationRecordV1) -> Result<(), RunStartStoreError> {
    if record.run_start_record_digest.is_zero()
        || record.revision == 0
        || !valid_reason(&record.cancel_reason)
    {
        return Err(RunStartStoreError::InvalidSnapshot("run cancellation"));
    }
    Ok(())
}

fn validate_closed(record: &RunClosedRecordV1) -> Result<(), RunStartStoreError> {
    if record.run_start_record_digest.is_zero()
        || record.closed_revision == 0
        || record.cancel_reason.as_deref().is_some_and(|reason| !valid_reason(reason))
    {
        return Err(RunStartStoreError::InvalidSnapshot("run closed"));
    }
    Ok(())
}

pub(super) fn validate_append(
    records: &[StoredRunStart],
    by_run: &BTreeMap<StableId, RunProjection>,
    record: &StoredRunStartRecord,
) -> Result<(), RunStartStoreError> {
    let digest = match record {
        StoredRunStartRecord::Cancellation(value) => {
            validate_cancellation(value)?;
            value.run_start_record_digest
        }
        StoredRunStartRecord::Closed(value) => {
            validate_closed(value)?;
            value.run_start_record_digest
        }
        StoredRunStartRecord::Run(_)
        | StoredRunStartRecord::Conflict(_)
        | StoredRunStartRecord::Prepared(_) => return Ok(()),
    };
    let projection = by_run.get(record.run_id()).ok_or(RunStartStoreError::Conflict)?;
    let start = records.get(projection.start).ok_or(RunStartStoreError::Corrupt)?;
    if !matches!(&start.record, StoredRunStartRecord::Run(_)) || start.record_digest != digest {
        return Err(RunStartStoreError::Conflict);
    }
    match record {
        StoredRunStartRecord::Cancellation(_)
            if projection.closed.is_some() && projection.cancellation.is_none() =>
        {
            return Err(RunStartStoreError::Conflict);
        }
        StoredRunStartRecord::Closed(value) => {
            if let Some(index) = projection.cancellation {
                let prior = records.get(index).ok_or(RunStartStoreError::Corrupt)?;
                let StoredRunStartRecord::Cancellation(prior) = &prior.record else {
                    return Err(RunStartStoreError::Corrupt);
                };
                if value.closed_revision < prior.revision
                    || value.cancel_reason.as_deref() != Some(prior.cancel_reason.as_str())
                {
                    return Err(RunStartStoreError::Conflict);
                }
            }
        }
        StoredRunStartRecord::Cancellation(_)
        | StoredRunStartRecord::Run(_)
        | StoredRunStartRecord::Conflict(_)
        | StoredRunStartRecord::Prepared(_) => {}
    }
    Ok(())
}

fn encode_binding(domain: &[u8], run_id: &StableId, digest: Digest32, revision: u64) -> Vec<u8> {
    let mut bytes = domain.to_vec();
    push_id(&mut bytes, run_id);
    push_digest(&mut bytes, digest);
    push_u64(&mut bytes, revision);
    bytes
}

fn push_reason(bytes: &mut Vec<u8>, reason: &str) {
    push_len(bytes, reason.len());
    bytes.extend_from_slice(reason.as_bytes());
}

pub(super) fn encode_cancellation(record: &RunCancellationRecordV1) -> Vec<u8> {
    let mut bytes = encode_binding(
        CANCELLATION_DOMAIN, &record.run_id, record.run_start_record_digest, record.revision,
    );
    push_reason(&mut bytes, &record.cancel_reason);
    bytes
}

pub(super) fn encode_closed(record: &RunClosedRecordV1) -> Vec<u8> {
    let mut bytes = encode_binding(
        CLOSED_DOMAIN, &record.run_id, record.run_start_record_digest, record.closed_revision,
    );
    bytes.push(match record.phase {
        RunClosedPhaseV1::Cancelled => 0,
        RunClosedPhaseV1::Succeeded => 1,
        RunClosedPhaseV1::Failed => 2,
    });
    match &record.cancel_reason {
        None => bytes.push(0),
        Some(reason) => {
            bytes.push(1);
            push_reason(&mut bytes, reason);
        }
    }
    bytes
}

fn read_reason(reader: &mut Reader<'_>) -> Result<String, RunStartStoreError> {
    let length = reader.len()?;
    if !(1..=MAX_CANCEL_REASON_BYTES).contains(&length) {
        return Err(RunStartStoreError::Corrupt);
    }
    let reason = std::str::from_utf8(reader.bytes(length)?)
        .map_err(|_| RunStartStoreError::Corrupt)?;
    if !valid_reason(reason) {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(reason.to_owned())
}

pub(super) fn decode_cancellation(input: &[u8]) -> Result<RunCancellationRecordV1, RunStartStoreError> {
    let mut reader = Reader(input.strip_prefix(CANCELLATION_DOMAIN).ok_or(RunStartStoreError::Corrupt)?);
    let record = RunCancellationRecordV1 {
        run_id: reader.id()?,
        run_start_record_digest: reader.digest()?,
        revision: reader.u64()?,
        cancel_reason: read_reason(&mut reader)?,
    };
    if !reader.0.is_empty() || validate_cancellation(&record).is_err() {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(record)
}

pub(super) fn decode_closed(input: &[u8]) -> Result<RunClosedRecordV1, RunStartStoreError> {
    let mut reader = Reader(input.strip_prefix(CLOSED_DOMAIN).ok_or(RunStartStoreError::Corrupt)?);
    let run_id = reader.id()?;
    let run_start_record_digest = reader.digest()?;
    let closed_revision = reader.u64()?;
    let phase = match reader.take::<1>()?[0] {
        0 => RunClosedPhaseV1::Cancelled,
        1 => RunClosedPhaseV1::Succeeded,
        2 => RunClosedPhaseV1::Failed,
        _ => return Err(RunStartStoreError::Corrupt),
    };
    let cancel_reason = match reader.take::<1>()?[0] {
        0 => None,
        1 => Some(read_reason(&mut reader)?),
        _ => return Err(RunStartStoreError::Corrupt),
    };
    let record = RunClosedRecordV1 {
        run_id, run_start_record_digest, closed_revision, phase, cancel_reason,
    };
    if !reader.0.is_empty() || validate_closed(&record).is_err() {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(record)
}

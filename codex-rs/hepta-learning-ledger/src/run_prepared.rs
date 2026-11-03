//! A completed canonical preparation in the original run-owner journal.
//!
//! The payload is owner state, not a grant or a second dispatch queue. Its
//! larger storage bound does not change a model's selected-context budget.

use super::*;

pub const MAX_RUN_PREPARED_BYTES: usize = 2 * 1024 * 1024;
pub(super) const DOMAIN: &[u8] = b"hepta.run-prepared-record.v1";

#[derive(Clone, Eq, PartialEq)]
pub struct RunPreparedRecordV1 {
    pub run_id: StableId,
    pub run_start_record_digest: Digest32,
    pub payload_digest: Digest32,
    pub payload: Vec<u8>,
}

impl fmt::Debug for RunPreparedRecordV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("RunPreparedRecordV1").field("run_id", &self.run_id)
            .field("run_start_record_digest", &self.run_start_record_digest)
            .field("payload_digest", &self.payload_digest)
            .field("payload_bytes", &self.payload.len()).finish()
    }
}

/// Issued only by a successful read of the original durable journal.
/// There is no constructor or deserializer. This proves storage provenance,
/// not current authorization, and never grants model/tool execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommittedRunPreparedV1 {
    record: RunPreparedRecordV1,
    original: RunStartRecordV1,
    receipt: RunStartAppendReceipt,
}

impl CommittedRunPreparedV1 {
    pub fn record(&self) -> &RunPreparedRecordV1 { &self.record }
    pub fn original(&self) -> &RunStartRecordV1 { &self.original }
    pub fn receipt(&self) -> &RunStartAppendReceipt { &self.receipt }
}

#[derive(Clone, Copy)]
pub(super) struct RunProjection {
    pub(super) start: usize,
    prepared: Option<usize>,
    pub(super) cancellation: Option<usize>,
    pub(super) closed: Option<usize>,
}

impl RunProjection {
    pub(super) fn index(&self, record: &StoredRunStartRecord) -> Option<usize> {
        match record {
            StoredRunStartRecord::Run(_) | StoredRunStartRecord::Conflict(_) => Some(self.start),
            StoredRunStartRecord::Prepared(_) => self.prepared,
            StoredRunStartRecord::Cancellation(_) => self.cancellation,
            StoredRunStartRecord::Closed(_) => self.closed,
        }
    }
}

impl DurableRunStartJournal {
    /// Publish completed preparation under the already committed run identity.
    /// Identical retries do not append; conflicts and shared quota exhaustion
    /// leave the old history intact. The original file is fsynced before return.
    pub fn append_prepared(&mut self, expected_predecessor: Digest32, record: RunPreparedRecordV1)
        -> Result<RunStartAppendReceipt, RunStartStoreError> {
        validate(&record)?;
        self.append_outcome(expected_predecessor, StoredRunStartRecord::Prepared(Box::new(record)))
    }

    pub fn run_start_record_digest(&self, run_id: &StableId) -> Result<Option<Digest32>, RunStartStoreError> {
        if self.poisoned { return Err(RunStartStoreError::Poisoned); }
        Ok(self.by_run.get(run_id).and_then(|projection| self.records.get(projection.start))
            .filter(|stored| matches!(&stored.record, StoredRunStartRecord::Run(_)))
            .map(|stored| stored.record_digest))
    }

    /// Read the exact committed payload; no replacement is synthesized for a
    /// RunStart-only record. Such a record has unknown preparation outcome.
    /// A later cancellation or terminal fact does not erase this audit record;
    /// consumers must check those facts before restoring execution eligibility.
    pub fn prepared(&self, run_id: &StableId) -> Result<Option<CommittedRunPreparedV1>, RunStartStoreError> {
        if self.poisoned { return Err(RunStartStoreError::Poisoned); }
        let Some(index) = self.by_run.get(run_id).and_then(|projection| projection.prepared) else {
            return Ok(None);
        };
        let stored = self.records.get(index).ok_or(RunStartStoreError::Corrupt)?;
        let StoredRunStartRecord::Prepared(record) = &stored.record else {
            return Err(RunStartStoreError::Corrupt);
        };
        validate_reference(&self.records, &self.by_run, record)?;
        Ok(Some(CommittedRunPreparedV1 {
            record: record.as_ref().clone(),
            original: self.get(run_id)?.ok_or(RunStartStoreError::Corrupt)?.clone(),
            receipt: RunStartAppendReceipt { disposition: RunStartAppendDisposition::IdempotentReplay,
                sequence: stored.sequence, record_digest: stored.record_digest, chain_digest: stored.chain_digest },
        }))
    }
}

fn validate(record: &RunPreparedRecordV1) -> Result<(), RunStartStoreError> {
    if record.run_start_record_digest.is_zero() || record.payload_digest.is_zero()
        || record.payload.is_empty() || record.payload.len() > MAX_RUN_PREPARED_BYTES
        || Digest32::of_bytes(&record.payload) != record.payload_digest {
        return Err(RunStartStoreError::InvalidSnapshot("prepared handoff"));
    }
    Ok(())
}

pub(super) fn validate_append(records: &[StoredRunStart], by_run: &BTreeMap<StableId, RunProjection>,
    record: &StoredRunStartRecord) -> Result<(), RunStartStoreError> {
    let StoredRunStartRecord::Prepared(prepared) = record else { return Ok(()); };
    validate_reference(records, by_run, prepared)?;
    if by_run.get(&prepared.run_id)
        .is_some_and(|value| value.cancellation.is_some() || value.closed.is_some()) {
        return Err(RunStartStoreError::Conflict);
    }
    Ok(())
}

fn validate_reference(records: &[StoredRunStart], by_run: &BTreeMap<StableId, RunProjection>,
    prepared: &RunPreparedRecordV1) -> Result<(), RunStartStoreError> {
    validate(prepared)?;
    let start = by_run.get(&prepared.run_id).and_then(|projection| records.get(projection.start))
        .ok_or(RunStartStoreError::Conflict)?;
    let StoredRunStartRecord::Run(original) = &start.record else { return Err(RunStartStoreError::Conflict); };
    if original.disposition != RunStartObjectiveDispositionV1::Compiled
        || start.record_digest != prepared.run_start_record_digest {
        return Err(RunStartStoreError::Conflict);
    }
    Ok(())
}

pub(super) fn record_projection(by_run: &mut BTreeMap<StableId, RunProjection>, record: &StoredRunStartRecord,
    index: usize) -> Result<(), RunStartStoreError> {
    match record {
        StoredRunStartRecord::Run(_) | StoredRunStartRecord::Conflict(_) => {
            by_run.insert(record.run_id().clone(), RunProjection { start: index, prepared: None, cancellation: None, closed: None });
        }
        StoredRunStartRecord::Prepared(_) => {
            by_run.get_mut(record.run_id()).ok_or(RunStartStoreError::Corrupt)?.prepared = Some(index);
        }
        StoredRunStartRecord::Cancellation(_) => {
            by_run.get_mut(record.run_id()).ok_or(RunStartStoreError::Corrupt)?.cancellation = Some(index);
        }
        StoredRunStartRecord::Closed(_) => {
            by_run.get_mut(record.run_id()).ok_or(RunStartStoreError::Corrupt)?.closed = Some(index);
        }
    }
    Ok(())
}

pub(super) fn encode(record: &RunPreparedRecordV1) -> Vec<u8> {
    let mut bytes = DOMAIN.to_vec();
    push_id(&mut bytes, &record.run_id);
    push_digest(&mut bytes, record.run_start_record_digest);
    push_digest(&mut bytes, record.payload_digest);
    push_len(&mut bytes, record.payload.len());
    bytes.extend_from_slice(&record.payload);
    bytes
}

pub(super) fn decode(input: &[u8]) -> Result<RunPreparedRecordV1, RunStartStoreError> {
    let mut reader = Reader(input.strip_prefix(DOMAIN).ok_or(RunStartStoreError::Corrupt)?);
    let run_id = reader.id()?;
    let run_start_record_digest = reader.digest()?;
    let payload_digest = reader.digest()?;
    let length = reader.len()?;
    if length == 0 || length > MAX_RUN_PREPARED_BYTES { return Err(RunStartStoreError::Corrupt); }
    let payload = reader.bytes(length)?.to_vec();
    let record = RunPreparedRecordV1 { run_id, run_start_record_digest, payload_digest, payload };
    if !reader.0.is_empty() || validate(&record).is_err() { return Err(RunStartStoreError::Corrupt); }
    Ok(record)
}

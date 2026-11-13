//! Private observations of a live daemon loan. These values are deliberately
//! not CircuitComputationAdmissionV2 and cannot be converted into that token.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_automation::CircuitComputationAdmissionV2;
use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;

use super::Error;
use super::data;
use super::wire::Frame;
use super::wire::Lane;
use super::wire::Operation;
use super::wire::Reader;
use super::wire::blob;

pub(super) struct AdmissionData {
    dispatch: CircuitDispatchV2,
    owner: String,
    definition: Sha256Digest,
    request: Option<Sha256Digest>,
    revision: u64,
    observed: u64,
    lease_end: u64,
    run_end: u64,
    reconciliation: bool,
}

impl AdmissionData {
    pub(super) fn from_original(original: &CircuitComputationAdmissionV2) -> Self {
        Self { dispatch: original.dispatch().clone(), owner: original.owner_agent_id().to_string(),
            definition: original.definition_digest().clone(), request: original.execution_request_digest().cloned(),
            revision: original.observed_revision(), observed: original.observed_at_ms(),
            lease_end: original.lease_expires_at_ms(), run_end: original.run_deadline_ms(),
            reconciliation: original.reconciliation_only() }
    }

    pub(super) fn encode(&self) -> Result<Vec<u8>, Error> {
        let mut bytes = b"HCRTADM1".to_vec();
        blob(&mut bytes, &data::encode_dispatch(&self.dispatch)?)?;
        blob(&mut bytes, self.owner.as_bytes())?;
        blob(&mut bytes, self.definition.as_str().as_bytes())?;
        blob(&mut bytes, self.request.as_ref().map_or(b"".as_slice(), |d| d.as_str().as_bytes()))?;
        for number in [self.revision, self.observed, self.lease_end, self.run_end] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        bytes.push(u8::from(self.reconciliation));
        super::wire::bounded(&bytes)?;
        Ok(bytes)
    }

    fn decode(bytes: &[u8]) -> Result<Self, Error> {
        let mut r = Reader::new(bytes, b"HCRTADM1")?;
        let dispatch = data::dispatch(r.blob()?)?;
        let owner = std::str::from_utf8(r.blob()?).map_err(|_| Error::InvalidBinding)?.to_owned();
        if owner.is_empty() || owner.len() > 128 || owner.chars().any(char::is_control) {
            return Err(Error::InvalidBinding);
        }
        let definition = sha(r.blob()?)?;
        let request = match r.blob()? { [] => None, value => Some(sha(value)?) };
        let value = Self { dispatch, owner, definition, request, revision: r.u64()?,
            observed: r.u64()?, lease_end: r.u64()?, run_end: r.u64()?,
            reconciliation: match r.take::<1>()? { [0] => false, [1] => true,
                _ => return Err(Error::InvalidBinding) } };
        r.end()?;
        if value.encode()? != bytes { return Err(Error::InvalidBinding); }
        Ok(value)
    }
}

/// Only the Root task service constructs this channel wrapper, after checking
/// its original registered non-Root peer on both fixed streams.
pub(super) struct ReverseClient {
    lane: Arc<Mutex<Lane>>,
    binding: Digest32,
}

impl ReverseClient {
    pub(super) fn new(lane: Lane, binding: Digest32) -> Self {
        Self { lane: Arc::new(Mutex::new(lane)), binding }
    }

    pub(super) fn check_record(&self, id: u64, record: &[u8]) -> Result<u64, Error> {
        check_record(&self.lane, id, record)
    }

    pub(super) fn open_admission(
        &self, id: u64, record_id: u64, record: &[u8],
    ) -> Result<OriginalRemoteAdmission, Error> {
        let bytes = super::wire::Lane::call(&mut *self.lane.try_lock().map_err(|_| Error::Unavailable)?, Frame {
            operation: Operation::OpenAdmission, loan: id, body: Vec::new(),
        })?;
        let mut r = Reader::new(&bytes, b"HCRTCHK1")?;
        if r.u64()? != record_id { return Err(Error::InvalidBinding); }
        let now = r.u64()?;
        if r.blob()? != record { return Err(Error::InvalidBinding); }
        let encoded = r.blob()?.to_vec();
        r.end()?;
        let data = AdmissionData::decode(&encoded)?;
        if now < data.observed { return Err(Error::ReconciliationRequired); }
        Ok(OriginalRemoteAdmission { lane: Arc::clone(&self.lane), id, record_id,
            record: record.to_vec(), encoded, data })
    }

    pub(super) fn completion(
        &self, id: u64, record_id: u64, record: &[u8], saved_input: &[u8],
    ) -> Result<OriginalRemoteCompletion, Error> {
        let bytes = super::wire::Lane::call(&mut *self.lane.try_lock().map_err(|_| Error::Unavailable)?, Frame {
            operation: Operation::ReadCompletion, loan: id, body: Vec::new(),
        })?;
        let mut r = Reader::new(&bytes, b"HCRTCHK1")?;
        if r.u64()? != record_id { return Err(Error::InvalidBinding); }
        r.u64()?;
        if r.blob()? != record || r.blob()? != saved_input { return Err(Error::InvalidBinding); }
        let payload = r.blob()?.to_vec();
        r.end()?;
        self.check_record(record_id, record)?;
        Ok(OriginalRemoteCompletion { lane: Arc::clone(&self.lane), binding: self.binding,
            record_id, record: record.to_vec(), saved_input: saved_input.to_vec(), payload })
    }

    pub(super) fn terminal(&self, id: u64, record_id: u64) -> Result<(), Error> {
        let reply = super::wire::Lane::call(&mut *self.lane.try_lock().map_err(|_| Error::Unavailable)?, Frame {
            operation: Operation::Terminal, loan: id, body: record_id.to_be_bytes().to_vec(),
        })?;
        if reply != b"HCRTEND1" { return Err(Error::InvalidBinding); }
        Ok(())
    }
}

/// A private live handle into one original admission held in the daemon.
/// There is no public constructor, Clone, Deserialize or conversion to the
/// original admission type. Every clock boundary revisits the same loan.
pub(crate) struct OriginalRemoteAdmission {
    lane: Arc<Mutex<Lane>>,
    id: u64,
    record_id: u64,
    record: Vec<u8>,
    encoded: Vec<u8>,
    data: AdmissionData,
}

impl OriginalRemoteAdmission {
    pub(crate) fn dispatch(&self) -> &CircuitDispatchV2 { &self.data.dispatch }
    pub(crate) fn owner_agent_id(&self) -> &str { &self.data.owner }
    pub(crate) fn definition_digest(&self) -> &Sha256Digest { &self.data.definition }
    pub(crate) fn execution_request_digest(&self) -> Option<&Sha256Digest> { self.data.request.as_ref() }
    pub(crate) fn observed_at_ms(&self) -> u64 { self.data.observed }
    pub(crate) fn lease_expires_at_ms(&self) -> u64 { self.data.lease_end }
    pub(crate) fn run_deadline_ms(&self) -> u64 { self.data.run_end }
    pub(crate) fn reconciliation_only(&self) -> bool { self.data.reconciliation }

    pub(crate) fn require_current(&self) -> Result<u64, Error> {
        let bytes = super::wire::Lane::call(&mut *self.lane.try_lock().map_err(|_| Error::Unavailable)?, Frame {
            operation: Operation::CheckAdmission, loan: self.id, body: Vec::new(),
        })?;
        let mut r = Reader::new(&bytes, b"HCRTCHK1")?;
        if r.u64()? != self.record_id { return Err(Error::InvalidBinding); }
        let now = r.u64()?;
        if r.blob()? != self.record || r.blob()? != self.encoded { return Err(Error::InvalidBinding); }
        r.end()?;
        Ok(now)
    }
}

/// Authenticated completion data from the fixed daemon loan. It still cannot
/// construct CircuitTaskReceiptV1; only the original Root Source may consume it.
pub(crate) struct OriginalRemoteCompletion {
    lane: Arc<Mutex<Lane>>,
    binding: Digest32,
    record_id: u64,
    record: Vec<u8>,
    saved_input: Vec<u8>,
    payload: Vec<u8>,
}

impl OriginalRemoteCompletion {
    pub(crate) fn into_original_payload(
        self, binding: Digest32, record: &[u8], saved_input: &[u8],
    ) -> Result<Vec<u8>, Error> {
        if self.binding != binding || self.record != record || self.saved_input != saved_input {
            return Err(Error::InvalidBinding);
        }
        check_record(&self.lane, self.record_id, &self.record)?;
        Ok(self.payload)
    }
}

fn check_record(lane: &Mutex<Lane>, id: u64, record: &[u8]) -> Result<u64, Error> {
    let bytes = super::wire::Lane::call(&mut *lane.try_lock().map_err(|_| Error::Unavailable)?, Frame {
        operation: Operation::CheckRecord, loan: id, body: record.to_vec(),
    })?;
    let mut r = Reader::new(&bytes, b"HCRTCHK1")?;
    if r.u64()? != id { return Err(Error::InvalidBinding); }
    let now = r.u64()?;
    if r.blob()? != record { return Err(Error::InvalidBinding); }
    r.end()?;
    Ok(now)
}

fn sha(bytes: &[u8]) -> Result<Sha256Digest, Error> {
    Sha256Digest::parse(std::str::from_utf8(bytes).map_err(|_| Error::InvalidBinding)?)
        .map_err(|_| Error::InvalidBinding)
}

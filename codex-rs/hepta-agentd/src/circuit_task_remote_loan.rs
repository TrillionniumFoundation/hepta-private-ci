//! Daemon-local custody. The original signed ingress, admission token and task
//! receipt remain here. The reverse channel can observe only this fixed loan.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::Weak;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_automation::CircuitComputationAdmissionV2;
use codex_hepta_learning_ledger::RunStartRecordV1;

use super::Error;
use super::admission::AdmissionData;
use super::wire::Frame;
use super::wire::Operation;
use super::wire::blob;
use crate::AgentdState;
use crate::CircuitTaskReceiptV1;
use crate::circuit_task::source::remote_source;

pub(super) struct DaemonLoans {
    state: OnceLock<Weak<AgentdState>>,
    cancellation: OnceLock<tokio_util::sync::CancellationToken>,
    pending: Arc<AtomicUsize>,
    inner: Mutex<LoanState>,
}

struct LoanState {
    next: u64,
    record: Option<RecordLoan>,
    admission: Option<AdmissionLoan>,
    completion: Option<CompletionLoan>,
}

struct RecordLoan {
    id: u64,
    record: RunStartRecordV1,
    encoded: Vec<u8>,
    caller_present: bool,
}

struct AdmissionLoan {
    record_id: u64,
    id: u64,
    original: CircuitComputationAdmissionV2,
    opened: bool,
    pending: Option<RemoteWork>,
}

struct CompletionLoan {
    record_id: u64,
    id: u64,
    original: CircuitTaskReceiptV1,
    request: crate::CircuitTaskRequestV1,
    definition: codex_hepta_automation::BoundedCircuitDefinitionV2,
    saved_input: Vec<u8>,
}

struct RemoteWork(Arc<AtomicUsize>);
impl Drop for RemoteWork {
    fn drop(&mut self) { self.0.fetch_sub(1, Ordering::AcqRel); }
}

/// Issued only by the crate-private signed RunStart entry, before invoking the
/// provider. Dropping the caller fences authority but does not release pending
/// Root work. Only its same terminal report releases that extra pending guard.
pub(crate) struct OriginalRecordLoan {
    shared: Arc<DaemonLoans>,
    id: u64,
}

impl Drop for OriginalRecordLoan {
    fn drop(&mut self) {
        if let Ok(mut state) = self.shared.inner.lock() {
            if let Some(record) = &mut state.record {
                if record.id == self.id { record.caller_present = false; }
            }
        }
    }
}

impl DaemonLoans {
    pub(super) fn new(pending: Arc<AtomicUsize>) -> Arc<Self> {
        Arc::new(Self {
            state: OnceLock::new(), cancellation: OnceLock::new(), pending,
            inner: Mutex::new(LoanState { next: 1, record: None, admission: None, completion: None }),
        })
    }

    pub(super) fn attach(&self, state: &Arc<AgentdState>,
        cancellation: tokio_util::sync::CancellationToken) -> Result<(), Error>
    {
        self.cancellation.set(cancellation).map_err(|_| Error::InvalidBinding)?;
        self.state.set(Arc::downgrade(state)).map_err(|_| Error::InvalidBinding)
    }

    pub(super) fn begin_record(
        self: &Arc<Self>, record: &RunStartRecordV1, encoded: Vec<u8>,
    ) -> Result<OriginalRecordLoan, Error> {
        self.current_state()?.require_current_run_start(record).map_err(|_| Error::Unavailable)?;
        let mut state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        if state.record.as_ref().is_some_and(|old| old.caller_present || old.record != *record)
            || state.admission.as_ref().is_some_and(|old| old.pending.is_some())
        { return Err(Error::Unavailable); }
        let id = allocate(&mut state)?;
        state.record = Some(RecordLoan { id, record: record.clone(), encoded, caller_present: true });
        state.admission = None;
        state.completion = None;
        Ok(OriginalRecordLoan { shared: Arc::clone(self), id })
    }

    pub(super) fn record(&self, original: &RunStartRecordV1) -> Result<(u64, Vec<u8>), Error> {
        let state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        let record = state.record.as_ref().ok_or(Error::Unavailable)?;
        if !record.caller_present || record.record != *original { return Err(Error::Unavailable); }
        Ok((record.id, record.encoded.clone()))
    }

    pub(super) fn current_record(&self) -> Result<(u64, Vec<u8>), Error> {
        let state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        let record = state.record.as_ref().ok_or(Error::Unavailable)?;
        if !record.caller_present { return Err(Error::Unavailable); }
        Ok((record.id, record.encoded.clone()))
    }

    pub(super) fn retain_admission(&self, original: CircuitComputationAdmissionV2) -> Result<u64, Error> {
        let mut state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        let record = state.record.as_ref().ok_or(Error::Unavailable)?;
        if !record.caller_present
            || record.record.snapshot.run_id.as_str() != original.dispatch().run_id
            || state.admission.as_ref().is_some_and(|old| old.pending.is_some())
        { return Err(Error::Unavailable); }
        let record_id = record.id;
        let id = allocate(&mut state)?;
        self.pending.fetch_add(1, Ordering::AcqRel);
        state.admission = Some(AdmissionLoan { record_id, id, original, opened: false,
            pending: Some(RemoteWork(Arc::clone(&self.pending))) });
        Ok(id)
    }

    pub(super) fn retain_completion(
        &self, request: crate::CircuitTaskRequestV1,
        definition: codex_hepta_automation::BoundedCircuitDefinitionV2,
        saved_input: Vec<u8>, original: &CircuitTaskReceiptV1,
    ) -> Result<u64, Error> {
        // Validate the real receipt before making any completion loan visible.
        remote_source::original_completion_bytes(&definition, &request, &saved_input, original)?;
        let mut state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        let record = state.record.as_ref().ok_or(Error::Unavailable)?;
        if !record.caller_present || record.record.snapshot.run_id.as_str() != request.start.run_id {
            return Err(Error::Unavailable);
        }
        let record_id = record.id;
        let id = allocate(&mut state)?;
        state.completion = Some(CompletionLoan { record_id, id, original: original.clone(),
            request, definition, saved_input });
        Ok(id)
    }

    /// This fixed handler has no supplied authorization callback. Authentication
    /// always calls the attached original AgentdState on the retained record.
    pub(super) fn respond(&self, frame: Frame) -> Result<Vec<u8>, Error> {
        if frame.operation == Operation::Terminal { return self.terminal(frame); }
        let (record_id, original, encoded) = {
            let state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
            let record = state.record.as_ref().ok_or(Error::Unavailable)?;
            if !record.caller_present { return Err(Error::Unavailable); }
            (record.id, record.record.clone(), record.encoded.clone())
        };
        // No loan mutex is held across Fleet/AuthBus/readiness file I/O.
        let now = self.current_state()?.require_current_run_start(&original)
            .map_err(|_| Error::Unavailable)?;
        let mut state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        let record = state.record.as_ref().ok_or(Error::Unavailable)?;
        if record.id != record_id || !record.caller_present || record.record != original {
            return Err(Error::Unavailable);
        }
        let mut bytes = b"HCRTCHK1".to_vec();
        bytes.extend_from_slice(&record_id.to_be_bytes());
        bytes.extend_from_slice(&now.to_be_bytes());
        blob(&mut bytes, &encoded)?;
        match frame.operation {
            Operation::CheckRecord if frame.loan == record_id && frame.body == encoded => {}
            Operation::OpenAdmission | Operation::CheckAdmission => {
                let admission = state.admission.as_mut().ok_or(Error::Unavailable)?;
                if admission.record_id != record_id || admission.id != frame.loan
                    || admission.pending.is_none() || !frame.body.is_empty()
                { return Err(Error::Unavailable); }
                match frame.operation {
                    Operation::OpenAdmission if !admission.opened => admission.opened = true,
                    Operation::CheckAdmission if admission.opened => {}
                    _ => return Err(Error::Unavailable),
                }
                blob(&mut bytes, &AdmissionData::from_original(&admission.original).encode()?)?;
            }
            Operation::ReadCompletion => {
                let completion = state.completion.as_ref().ok_or(Error::Unavailable)?;
                if completion.record_id != record_id || completion.id != frame.loan
                    || !frame.body.is_empty()
                { return Err(Error::Unavailable); }
                let payload = remote_source::original_completion_bytes(&completion.definition,
                    &completion.request, &completion.saved_input, &completion.original)?;
                blob(&mut bytes, &completion.saved_input)?;
                blob(&mut bytes, &payload)?;
            }
            _ => return Err(Error::InvalidBinding),
        }
        drop(state);
        self.current_state()?.require_current_run_start(&original).map_err(|_| Error::Unavailable)?;
        let state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        if state.record.as_ref().is_none_or(|record| record.id != record_id || !record.caller_present) {
            return Err(Error::Unavailable);
        }
        Ok(bytes)
    }

    fn terminal(&self, frame: Frame) -> Result<Vec<u8>, Error> {
        let mut state = self.inner.try_lock().map_err(|_| Error::Unavailable)?;
        let record_id = state.record.as_ref().ok_or(Error::Unavailable)?.id;
        let admission = state.admission.as_mut().ok_or(Error::Unavailable)?;
        if admission.id != frame.loan || admission.record_id != record_id
            || frame.body != record_id.to_be_bytes() || !admission.opened
        { return Err(Error::InvalidBinding); }
        // This releases only work reported terminal by the pinned Root pump.
        // It grants no admission, completion or permission to advance the run.
        drop(admission.pending.take());
        Ok(b"HCRTEND1".to_vec())
    }

    fn current_state(&self) -> Result<Arc<AgentdState>, Error> {
        if self.cancellation.get().is_none_or(|token| token.is_cancelled()) {
            return Err(Error::Unavailable);
        }
        self.state.get().and_then(Weak::upgrade).ok_or(Error::Unavailable)
    }
}

fn allocate(state: &mut LoanState) -> Result<u64, Error> {
    let id = state.next;
    state.next = id.checked_add(1).ok_or(Error::Unavailable)?;
    Ok(id)
}

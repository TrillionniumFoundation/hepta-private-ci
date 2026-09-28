//! Durable product port from the inference worker to `neuron.runtime`.
//!
//! The feature store persists `Reserved` before work and `Dispatched` before the
//! physical backend boundary. A recovered dispatched operation is query-only;
//! it is never re-executed under the same operation identity.

use codex_hepta_infer_core::FileNeuronFeatureExecutionStoreV1;
use codex_hepta_infer_core::NeuronFeatureAdmissionV1;
use codex_hepta_infer_core::NeuronFeatureExecutionRecordV1;
use codex_hepta_infer_core::NeuronFeatureExecutionStateV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureStoreError;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_neuron::DurableNeuronFeatureResolutionV2;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableNeuronFeatureBackendError {
    Unavailable,
    Indeterminate,
}

/// Provider/driver boundary for one stable operation identity.
///
/// `execute_new` is called only after the local dispatch fence is durable.
/// `reconcile` must query the provider/driver's existing operation and must not
/// start new physical work.
pub trait DurableNeuronFeatureBackend {
    fn execute_new(
        &mut self,
        operation_id: &StableId,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, DurableNeuronFeatureBackendError>;

    fn reconcile(
        &mut self,
        operation_id: &StableId,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, DurableNeuronFeatureBackendError>;
}

pub struct DurableNeuronFeaturePortV1<B> {
    store: FileNeuronFeatureExecutionStoreV1,
    backend: B,
}

impl<B: DurableNeuronFeatureBackend> DurableNeuronFeaturePortV1<B> {
    pub fn new(store: FileNeuronFeatureExecutionStoreV1, backend: B) -> Self {
        Self { store, backend }
    }

    pub fn unresolved_count(&self) -> Result<usize, NeuronFeatureStoreError> {
        self.store.unresolved_count()
    }

    pub fn reconcile_all(&mut self) -> Result<usize, NeuronModelError> {
        let pending = self.store.unresolved().map_err(map_store_error)?;
        let mut completed = 0_usize;
        for record in pending {
            if record.state == NeuronFeatureExecutionStateV1::Reserved {
                // No physical boundary was crossed. Leave the operation in the
                // safely executable state; startup reconciliation never starts
                // fresh model work.
                continue;
            }
            if record.state != NeuronFeatureExecutionStateV1::Dispatched {
                continue;
            }
            let operation_id = operation_id(&record);
            let Some(receipt) = self
                .backend
                .reconcile(&operation_id, &record.request)
                .map_err(map_backend_error)?
            else {
                continue;
            };
            verify_neuron_feature_receipt_v1(&record.request, &receipt)
                .map_err(|_| NeuronModelError::Indeterminate)?;
            self.store
                .observe(&record.request, receipt)
                .map_err(map_store_error)?;
            completed = completed.saturating_add(1);
        }
        Ok(completed)
    }

    pub fn store(&self) -> &FileNeuronFeatureExecutionStoreV1 {
        &self.store
    }

    pub fn backend_mut(&mut self) -> &mut B {
        &mut self.backend
    }

    fn execute(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let record = match self.store.admit(request).map_err(map_store_error)? {
            NeuronFeatureAdmissionV1::Historical(record) => *record,
            NeuronFeatureAdmissionV1::New => self
                .store
                .reserve(request.clone())
                .map_err(map_store_error)?,
        };
        self.resolve_record(record)
    }

    fn resolve_record(
        &mut self,
        record: NeuronFeatureExecutionRecordV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        if record.state.terminal() {
            return record.receipt.ok_or(NeuronModelError::Indeterminate);
        }
        let operation_id = operation_id(&record);
        match record.state {
            NeuronFeatureExecutionStateV1::Reserved => {
                self.store
                    .mark_dispatched(&record.request)
                    .map_err(map_store_error)?;
                let receipt = self
                    .backend
                    .execute_new(&operation_id, &record.request)
                    .map_err(map_backend_error)?;
                verify_neuron_feature_receipt_v1(&record.request, &receipt)
                    .map_err(|_| NeuronModelError::Indeterminate)?;
                let committed = self
                    .store
                    .observe(&record.request, receipt)
                    .map_err(map_store_error)?;
                committed.receipt.ok_or(NeuronModelError::Indeterminate)
            }
            NeuronFeatureExecutionStateV1::Dispatched => {
                let receipt = self
                    .backend
                    .reconcile(&operation_id, &record.request)
                    .map_err(map_backend_error)?
                    .ok_or(NeuronModelError::Indeterminate)?;
                verify_neuron_feature_receipt_v1(&record.request, &receipt)
                    .map_err(|_| NeuronModelError::Indeterminate)?;
                let committed = self
                    .store
                    .observe(&record.request, receipt)
                    .map_err(map_store_error)?;
                committed.receipt.ok_or(NeuronModelError::Indeterminate)
            }
            NeuronFeatureExecutionStateV1::Succeeded
            | NeuronFeatureExecutionStateV1::Failed
            | NeuronFeatureExecutionStateV1::Cancelled
            | NeuronFeatureExecutionStateV1::Indeterminate => {
                record.receipt.ok_or(NeuronModelError::Indeterminate)
            }
        }
    }
}

impl<B: DurableNeuronFeatureBackend> NeuronInferenceControlPort for DurableNeuronFeaturePortV1<B> {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.execute(request)
    }
}

impl<B: DurableNeuronFeatureBackend> DurableNeuronInferenceControlPort
    for DurableNeuronFeaturePortV1<B>
{
    fn reconcile_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<DurableNeuronFeatureResolutionV2, NeuronModelError> {
        let record = match self.store.admit(request).map_err(map_store_error)? {
            NeuronFeatureAdmissionV1::New => {
                return Ok(DurableNeuronFeatureResolutionV2::NotStarted);
            }
            NeuronFeatureAdmissionV1::Historical(record) => *record,
        };
        if record.state == NeuronFeatureExecutionStateV1::Reserved {
            return Ok(DurableNeuronFeatureResolutionV2::NotStarted);
        }
        // resolve_record can dispatch only Reserved records, excluded above.
        self.resolve_record(record)
            .map(Box::new)
            .map(DurableNeuronFeatureResolutionV2::Observed)
    }
}

fn operation_id(record: &NeuronFeatureExecutionRecordV1) -> StableId {
    // The request id is already a stable, conflict-fenced product operation id.
    // The durable store separately binds its exact request digest.
    record.request.request_id.clone()
}

fn map_store_error(error: NeuronFeatureStoreError) -> NeuronModelError {
    match error {
        NeuronFeatureStoreError::Conflict => NeuronModelError::Rejected,
        NeuronFeatureStoreError::InvalidRecord
        | NeuronFeatureStoreError::ContextMismatch
        | NeuronFeatureStoreError::InvalidTransition
        | NeuronFeatureStoreError::Corrupt => NeuronModelError::Indeterminate,
        NeuronFeatureStoreError::Indeterminate | NeuronFeatureStoreError::Poisoned => {
            NeuronModelError::Indeterminate
        }
        NeuronFeatureStoreError::Busy
        | NeuronFeatureStoreError::NotRegular
        | NeuronFeatureStoreError::HistoryMissing
        | NeuronFeatureStoreError::InvalidLimit
        | NeuronFeatureStoreError::Capacity
        | NeuronFeatureStoreError::ReplayBound
        | NeuronFeatureStoreError::Io(_) => NeuronModelError::Unavailable,
    }
}

fn map_backend_error(error: DurableNeuronFeatureBackendError) -> NeuronModelError {
    match error {
        DurableNeuronFeatureBackendError::Unavailable => NeuronModelError::Unavailable,
        DurableNeuronFeatureBackendError::Indeterminate => NeuronModelError::Indeterminate,
    }
}

#[cfg(test)]
#[path = "durable_neuron_feature_tests.rs"]
mod tests;

//! Two-phase crash-durable adapter for the registered inference-control port.
//!
//! Preparation may resolve current artifacts, source authority and a one-use
//! execution grant, but it must not enter the physical model. Only after that
//! preparation succeeds does this owner persist the dispatch fence and consume
//! the prepared value. A recovered dispatched operation is reconcile-only.

use codex_hepta_infer_core::FileNeuronFeatureExecutionStoreV1;
use codex_hepta_infer_core::NeuronFeatureAdmissionV1;
use codex_hepta_infer_core::NeuronFeatureExecutionStateV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureStoreError;

use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;

/// A split admission/dispatch backend. `prepare_feature` may perform bounded,
/// non-effectful verification and consume one-use admission material. It must
/// not enter the selected model or publish a model result. `dispatch_prepared`
/// is the only physical execution boundary.
pub trait PreparedNeuronInferenceControlPort {
    type Prepared;

    fn prepare_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Self::Prepared, NeuronModelError>;

    fn dispatch_prepared(
        &mut self,
        request: &NeuronFeatureRequestV1,
        prepared: Self::Prepared,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError>;
}

/// Compose one two-phase backend with the existing durable operation owner.
pub struct DurablePreparedNeuronInferenceControlPortV1<P> {
    store: FileNeuronFeatureExecutionStoreV1,
    inner: P,
}

impl<P> DurablePreparedNeuronInferenceControlPortV1<P> {
    #[must_use]
    pub fn new(store: FileNeuronFeatureExecutionStoreV1, inner: P) -> Self {
        Self { store, inner }
    }

    #[must_use]
    pub fn store(&self) -> &FileNeuronFeatureExecutionStoreV1 {
        &self.store
    }

    pub fn store_mut(&mut self) -> &mut FileNeuronFeatureExecutionStoreV1 {
        &mut self.store
    }

    #[must_use]
    pub fn inner(&self) -> &P {
        &self.inner
    }

    pub fn inner_mut(&mut self) -> &mut P {
        &mut self.inner
    }

    #[must_use]
    pub fn into_parts(self) -> (FileNeuronFeatureExecutionStoreV1, P) {
        (self.store, self.inner)
    }
}

impl<P: PreparedNeuronInferenceControlPort> NeuronInferenceControlPort
    for DurablePreparedNeuronInferenceControlPortV1<P>
{
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        match self.store.admit(request).map_err(map_admission_error)? {
            NeuronFeatureAdmissionV1::New => {
                self.store
                    .reserve(request.clone())
                    .map_err(map_persist_error)?;
            }
            NeuronFeatureAdmissionV1::Historical(record) => {
                if let Some(receipt) = record.receipt {
                    return Ok(receipt);
                }
                match record.state {
                    // No physical entry fence exists. Current authority and
                    // artifact preparation must be reacquired before dispatch.
                    NeuronFeatureExecutionStateV1::Reserved => {}
                    NeuronFeatureExecutionStateV1::Dispatched
                    | NeuronFeatureExecutionStateV1::Indeterminate => {
                        return Err(NeuronModelError::Indeterminate);
                    }
                    NeuronFeatureExecutionStateV1::Succeeded
                    | NeuronFeatureExecutionStateV1::Failed
                    | NeuronFeatureExecutionStateV1::Cancelled => {
                        return Err(NeuronModelError::Rejected);
                    }
                }
            }
        }

        // Preparation remains before the durable fence. A preparation failure
        // leaves an exact Reserved operation that can safely reacquire current
        // admission material without claiming physical execution happened.
        let prepared = self.inner.prepare_feature(request)?;

        self.store
            .mark_dispatched(request)
            .map_err(map_persist_error)?;

        // Every error after the fence is unknown to this generic owner. A
        // concrete backend may retain richer observations for reconciliation,
        // but this call path never converts them into redispatch authority.
        let receipt = self
            .inner
            .dispatch_prepared(request, prepared)
            .map_err(|_| NeuronModelError::Indeterminate)?;

        self.store
            .observe(request, receipt.clone())
            .map_err(|_| NeuronModelError::Indeterminate)?;
        Ok(receipt)
    }
}

fn map_admission_error(error: NeuronFeatureStoreError) -> NeuronModelError {
    match error {
        NeuronFeatureStoreError::Conflict
        | NeuronFeatureStoreError::InvalidLimit
        | NeuronFeatureStoreError::InvalidRecord
        | NeuronFeatureStoreError::ContextMismatch
        | NeuronFeatureStoreError::InvalidTransition
        | NeuronFeatureStoreError::Corrupt => NeuronModelError::Rejected,
        NeuronFeatureStoreError::Indeterminate | NeuronFeatureStoreError::Poisoned => {
            NeuronModelError::Indeterminate
        }
        NeuronFeatureStoreError::Busy
        | NeuronFeatureStoreError::NotRegular
        | NeuronFeatureStoreError::HistoryMissing
        | NeuronFeatureStoreError::Capacity
        | NeuronFeatureStoreError::ReplayBound
        | NeuronFeatureStoreError::Io(_) => NeuronModelError::Unavailable,
    }
}

fn map_persist_error(error: NeuronFeatureStoreError) -> NeuronModelError {
    match error {
        NeuronFeatureStoreError::Conflict
        | NeuronFeatureStoreError::InvalidLimit
        | NeuronFeatureStoreError::InvalidRecord
        | NeuronFeatureStoreError::ContextMismatch
        | NeuronFeatureStoreError::InvalidTransition
        | NeuronFeatureStoreError::Corrupt => NeuronModelError::Rejected,
        NeuronFeatureStoreError::Busy
        | NeuronFeatureStoreError::NotRegular
        | NeuronFeatureStoreError::HistoryMissing
        | NeuronFeatureStoreError::Capacity
        | NeuronFeatureStoreError::ReplayBound
        | NeuronFeatureStoreError::Indeterminate
        | NeuronFeatureStoreError::Poisoned
        | NeuronFeatureStoreError::Io(_) => NeuronModelError::Indeterminate,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use codex_hepta_infer_core::NeuronFeatureObservationV1;
    use codex_hepta_infer_core::NeuronFeatureStoreContextV1;
    use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
    use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
    use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;
    use pretty_assertions::assert_eq;

    const Q: i64 = 1 << 24;
    static NEXT_TEMP: AtomicU64 = AtomicU64::new(1);

    fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
        match result {
            Ok(value) => value,
            Err(error) => panic!("fixture failed: {error:?}"),
        }
    }

    struct TempJournal {
        root: PathBuf,
        path: PathBuf,
    }

    impl TempJournal {
        fn new() -> Self {
            let nonce = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!(
                "hepta-neuron-prepared-control-{}-{nonce}",
                std::process::id()
            ));
            checked(std::fs::create_dir(&root));
            let path = root.join("feature-execution.log");
            Self { root, path }
        }
    }

    impl Drop for TempJournal {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    fn context() -> NeuronFeatureStoreContextV1 {
        NeuronFeatureStoreContextV1 {
            generation: checked(Generation::new(11)),
            owner_digest: Digest32::of_bytes(b"prepared-neuron-owner"),
            max_records: 64,
            max_receipt_bytes: 64 * 1024,
            max_file_bytes: 1024 * 1024,
            max_startup_replay_bytes: 1024 * 1024,
        }
    }

    fn request() -> NeuronFeatureRequestV1 {
        NeuronFeatureRequestV1 {
            request_id: checked(StableId::new("feature:prepared:1")),
            generation: checked(Generation::new(11)),
            model_id: checked(StableId::new("model:laya:prepared")),
            encoder_digest: Digest32::of_bytes(b"encoder"),
            head_digest: Digest32::of_bytes(b"head"),
            weights_digest: Digest32::of_bytes(b"weights"),
            input_digest: Digest32::of_bytes(b"input"),
            feature_vector_q24: vec![Q / 3, -Q / 5],
            expected_output_width: 2,
        }
    }

    fn receipt(request: &NeuronFeatureRequestV1) -> NeuronFeatureReceiptV1 {
        checked(build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: Digest32::of_bytes(b"manifest"),
                weights_digest: request.weights_digest,
                tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
                preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
                quantization_digest: Digest32::of_bytes(b"quantization"),
                runtime_digest: Digest32::of_bytes(b"runtime"),
                device_digest: Digest32::of_bytes(b"device"),
            },
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24: vec![Q / 2; 2],
                prediction_q24: vec![0; 2],
                observed_memory_bytes: 8_192,
                transient_allocation_bytes: 2_048,
                queue_age_micros: 3,
                latency_micros: 17,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        ))
    }

    #[derive(Clone, Copy)]
    struct Prepared(u64);

    struct Backend {
        prepare_calls: usize,
        dispatch_calls: usize,
        preparation_error: Option<NeuronModelError>,
        dispatch_error: Option<NeuronModelError>,
    }

    impl PreparedNeuronInferenceControlPort for Backend {
        type Prepared = Prepared;

        fn prepare_feature(
            &mut self,
            _request: &NeuronFeatureRequestV1,
        ) -> Result<Self::Prepared, NeuronModelError> {
            self.prepare_calls += 1;
            if let Some(error) = self.preparation_error {
                return Err(error);
            }
            Ok(Prepared(
                u64::try_from(self.prepare_calls).expect("test call count fits u64"),
            ))
        }

        fn dispatch_prepared(
            &mut self,
            request: &NeuronFeatureRequestV1,
            prepared: Self::Prepared,
        ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
            self.dispatch_calls += 1;
            assert!(prepared.0 > 0);
            if let Some(error) = self.dispatch_error {
                return Err(error);
            }
            Ok(receipt(request))
        }
    }

    fn create_store(journal: &TempJournal) -> FileNeuronFeatureExecutionStoreV1 {
        checked(FileNeuronFeatureExecutionStoreV1::create(
            &journal.path,
            context(),
        ))
    }

    fn reopen_store(journal: &TempJournal) -> FileNeuronFeatureExecutionStoreV1 {
        checked(FileNeuronFeatureExecutionStoreV1::open_existing(
            &journal.path,
            context(),
        ))
    }

    #[test]
    fn preparation_failure_remains_reserved_and_can_reacquire_after_restart() {
        let journal = TempJournal::new();
        let request = request();
        let backend = Backend {
            prepare_calls: 0,
            dispatch_calls: 0,
            preparation_error: Some(NeuronModelError::Unavailable),
            dispatch_error: None,
        };
        let mut control =
            DurablePreparedNeuronInferenceControlPortV1::new(create_store(&journal), backend);

        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Unavailable)
        );
        assert_eq!(control.inner().dispatch_calls, 0);
        assert_eq!(
            checked(control.store().get(&request.request_id))
                .expect("reserved operation")
                .state,
            NeuronFeatureExecutionStateV1::Reserved
        );
        drop(control);

        let backend = Backend {
            prepare_calls: 0,
            dispatch_calls: 0,
            preparation_error: None,
            dispatch_error: None,
        };
        let mut reopened =
            DurablePreparedNeuronInferenceControlPortV1::new(reopen_store(&journal), backend);
        assert_eq!(
            checked(reopened.execute_feature(&request)).status,
            NeuronFeatureTerminalStatusV1::Succeeded
        );
        assert_eq!(reopened.inner().prepare_calls, 1);
        assert_eq!(reopened.inner().dispatch_calls, 1);
    }

    #[test]
    fn dispatch_failure_is_fenced_and_never_prepared_again() {
        let journal = TempJournal::new();
        let request = request();
        let backend = Backend {
            prepare_calls: 0,
            dispatch_calls: 0,
            preparation_error: None,
            dispatch_error: Some(NeuronModelError::Unavailable),
        };
        let mut control =
            DurablePreparedNeuronInferenceControlPortV1::new(create_store(&journal), backend);

        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(control.inner().prepare_calls, 1);
        assert_eq!(control.inner().dispatch_calls, 1);
        assert_eq!(
            checked(control.store().get(&request.request_id))
                .expect("fenced operation")
                .state,
            NeuronFeatureExecutionStateV1::Dispatched
        );
    }

    #[test]
    fn completed_result_is_reused_without_new_preparation() {
        let journal = TempJournal::new();
        let request = request();
        let backend = Backend {
            prepare_calls: 0,
            dispatch_calls: 0,
            preparation_error: None,
            dispatch_error: None,
        };
        let mut control =
            DurablePreparedNeuronInferenceControlPortV1::new(create_store(&journal), backend);

        let first = checked(control.execute_feature(&request));
        let second = checked(control.execute_feature(&request));
        assert_eq!(second, first);
        assert_eq!(control.inner().prepare_calls, 1);
        assert_eq!(control.inner().dispatch_calls, 1);
    }
}

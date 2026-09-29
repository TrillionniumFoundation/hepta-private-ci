//! Crash-durable Neuron feature inference adapter.
//!
//! This is a bounded adapter around the registered inference-control model port.
//! It persists complete immutable requests, fsyncs a dispatch fence before model
//! entry, records complete receipts before publishing them and never treats an
//! unresolved fenced dispatch as permission to execute again.

use codex_hepta_infer_core::FileNeuronFeatureExecutionStoreV1;
use codex_hepta_infer_core::NeuronFeatureAdmissionV1;
use codex_hepta_infer_core::NeuronFeatureExecutionStateV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureStoreError;

use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;

pub struct DurableNeuronInferenceControlPortV1<P> {
    store: FileNeuronFeatureExecutionStoreV1,
    inner: P,
}

impl<P> DurableNeuronInferenceControlPortV1<P> {
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

impl<P: NeuronInferenceControlPort> NeuronInferenceControlPort
    for DurableNeuronInferenceControlPortV1<P>
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
                return historical_result(record.state, record.receipt);
            }
        }

        self.store
            .mark_dispatched(request)
            .map_err(map_persist_error)?;

        let receipt = self
            .inner
            .execute_feature(request)
            .map_err(|_| NeuronModelError::Indeterminate)?;

        self.store
            .observe(request, receipt.clone())
            .map_err(|_| NeuronModelError::Indeterminate)?;
        Ok(receipt)
    }
}

fn historical_result(
    state: NeuronFeatureExecutionStateV1,
    receipt: Option<NeuronFeatureReceiptV1>,
) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
    match state {
        NeuronFeatureExecutionStateV1::Succeeded
        | NeuronFeatureExecutionStateV1::Failed
        | NeuronFeatureExecutionStateV1::Cancelled => receipt.ok_or(NeuronModelError::Rejected),
        NeuronFeatureExecutionStateV1::Reserved
        | NeuronFeatureExecutionStateV1::Dispatched
        | NeuronFeatureExecutionStateV1::Indeterminate => Err(NeuronModelError::Indeterminate),
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
                "hepta-neuron-durable-control-{}-{nonce}",
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
            generation: checked(Generation::new(7)),
            owner_digest: Digest32::of_bytes(b"durable-neuron-owner"),
            max_records: 64,
            max_receipt_bytes: 64 * 1024,
            max_file_bytes: 1024 * 1024,
            max_startup_replay_bytes: 1024 * 1024,
        }
    }

    fn request() -> NeuronFeatureRequestV1 {
        NeuronFeatureRequestV1 {
            request_id: checked(StableId::new("feature:request:1")),
            generation: checked(Generation::new(7)),
            model_id: checked(StableId::new("model:laya:test")),
            encoder_digest: Digest32::of_bytes(b"encoder"),
            head_digest: Digest32::of_bytes(b"head"),
            weights_digest: Digest32::of_bytes(b"weights"),
            input_digest: Digest32::of_bytes(b"input"),
            feature_vector_q24: vec![Q / 2, -Q / 4],
            expected_output_width: 2,
        }
    }

    fn receipt_with_status(
        request: &NeuronFeatureRequestV1,
        status: NeuronFeatureTerminalStatusV1,
    ) -> NeuronFeatureReceiptV1 {
        let has_output = status == NeuronFeatureTerminalStatusV1::Succeeded;
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
                drive_q24: if has_output { vec![Q; 2] } else { Vec::new() },
                prediction_q24: if has_output { vec![0; 2] } else { Vec::new() },
                observed_memory_bytes: 4096,
                transient_allocation_bytes: 2048,
                queue_age_micros: 2,
                latency_micros: 11,
                status,
            },
        ))
    }

    fn receipt(request: &NeuronFeatureRequestV1) -> NeuronFeatureReceiptV1 {
        receipt_with_status(request, NeuronFeatureTerminalStatusV1::Succeeded)
    }

    struct CountingPort {
        calls: usize,
        result: Result<NeuronFeatureTerminalStatusV1, NeuronModelError>,
    }

    impl NeuronInferenceControlPort for CountingPort {
        fn execute_feature(
            &mut self,
            request: &NeuronFeatureRequestV1,
        ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
            self.calls += 1;
            self.result
                .map(|status| receipt_with_status(request, status))
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
    fn completed_result_is_reused_without_model_reexecution() {
        let journal = TempJournal::new();
        let request = request();
        let inner = CountingPort {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(create_store(&journal), inner);

        let first = checked(control.execute_feature(&request));
        let second = checked(control.execute_feature(&request));
        assert_eq!(first, second);
        assert_eq!(control.inner().calls, 1);
    }

    #[test]
    fn changed_same_id_request_is_rejected_before_model_entry() {
        let journal = TempJournal::new();
        let request = request();
        let inner = CountingPort {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(create_store(&journal), inner);
        checked(control.execute_feature(&request));

        let mut changed = request.clone();
        changed.input_digest = Digest32::of_bytes(b"different-input");
        assert_eq!(
            control.execute_feature(&changed),
            Err(NeuronModelError::Rejected)
        );
        assert_eq!(control.inner().calls, 1);
    }

    #[test]
    fn model_error_after_fence_remains_indeterminate_and_never_retries() {
        let journal = TempJournal::new();
        let request = request();
        let inner = CountingPort {
            calls: 0,
            result: Err(NeuronModelError::Unavailable),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(create_store(&journal), inner);

        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(control.inner().calls, 1);
        let record = checked(control.store().get(&request.request_id)).expect("record");
        assert_eq!(record.state, NeuronFeatureExecutionStateV1::Dispatched);
    }

    #[test]
    fn terminal_indeterminate_receipt_is_persisted_and_not_reexecuted() {
        let journal = TempJournal::new();
        let request = request();
        let inner = CountingPort {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Indeterminate),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(create_store(&journal), inner);

        let first = checked(control.execute_feature(&request));
        let second = control.execute_feature(&request);
        assert_eq!(first.status, NeuronFeatureTerminalStatusV1::Indeterminate);
        assert_eq!(second, Err(NeuronModelError::Indeterminate));
        assert_eq!(control.inner().calls, 1);
        let record = checked(control.store().get(&request.request_id)).expect("record");
        assert_eq!(record.state, NeuronFeatureExecutionStateV1::Indeterminate);
        assert_eq!(
            record.receipt.expect("retained receipt").status,
            NeuronFeatureTerminalStatusV1::Indeterminate
        );
    }

    #[test]
    fn durable_result_survives_store_reopen_without_model_entry() {
        let journal = TempJournal::new();
        let request = request();
        let expected = receipt(&request);
        {
            let inner = CountingPort {
                calls: 0,
                result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
            };
            let mut control =
                DurableNeuronInferenceControlPortV1::new(create_store(&journal), inner);
            assert_eq!(checked(control.execute_feature(&request)), expected);
            assert_eq!(control.inner().calls, 1);
        }

        let inner = CountingPort {
            calls: 0,
            result: Err(NeuronModelError::Unavailable),
        };
        let mut reopened = DurableNeuronInferenceControlPortV1::new(reopen_store(&journal), inner);
        assert_eq!(checked(reopened.execute_feature(&request)), expected);
        assert_eq!(reopened.inner().calls, 0);
    }

    #[test]
    fn recovered_dispatch_fence_never_enters_model() {
        let journal = TempJournal::new();
        let request = request();
        {
            let mut store = create_store(&journal);
            checked(store.reserve(request.clone()));
            checked(store.mark_dispatched(&request));
        }

        let inner = CountingPort {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        };
        let mut reopened = DurableNeuronInferenceControlPortV1::new(reopen_store(&journal), inner);
        assert_eq!(
            reopened.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(reopened.inner().calls, 0);
    }
}

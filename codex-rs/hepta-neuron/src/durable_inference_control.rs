//! Crash-durable adapter for the registered inference-control feature port.
//!
//! The inference owner persists the operation identity before backend entry and
//! a dispatch fence before invoking the concrete port. Historical receipts are
//! returned exactly. A recovered dispatched operation is reconcile-only and is
//! never executed again merely because a caller lost the reply.

use codex_hepta_infer_core::FileNeuronFeatureExecutionStoreV1;
use codex_hepta_infer_core::NeuronFeatureAdmissionV1;
use codex_hepta_infer_core::NeuronFeatureExecutionStateV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureStoreError;

use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;

/// Compose one concrete inference-control port with its existing durable
/// operation owner. This adapter neither selects a model nor grants authority;
/// it only preserves exact execution and result semantics across restart.
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
                if let Some(receipt) = record.receipt {
                    return Ok(receipt);
                }
                match record.state {
                    // No physical dispatch fence exists yet. The exact request
                    // may resume from this owned reservation.
                    NeuronFeatureExecutionStateV1::Reserved => {}
                    // Backend entry may already have happened. Reconciliation,
                    // not redispatch, owns every later transition.
                    NeuronFeatureExecutionStateV1::Dispatched
                    | NeuronFeatureExecutionStateV1::Indeterminate => {
                        return Err(NeuronModelError::Indeterminate);
                    }
                    // Terminal records always carry their verified receipt.
                    NeuronFeatureExecutionStateV1::Succeeded
                    | NeuronFeatureExecutionStateV1::Failed
                    | NeuronFeatureExecutionStateV1::Cancelled => {
                        return Err(NeuronModelError::Rejected);
                    }
                }
            }
        }

        self.store
            .mark_dispatched(request)
            .map_err(map_persist_error)?;

        // Once the fence is durable, every backend error is conservatively
        // unknown. The inner port cannot prove that physical entry did not
        // occur, so a caller must not obtain permission to execute it again.
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
        // A mutating journal call can fail after writing or syncing bytes. Do
        // not advertise a safe retry unless a reopened owner proves one.
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
            request_id: checked(StableId::new("feature:durable:1")),
            generation: checked(Generation::new(7)),
            model_id: checked(StableId::new("model:laya:1")),
            encoder_digest: Digest32::of_bytes(b"encoder"),
            head_digest: Digest32::of_bytes(b"head"),
            weights_digest: Digest32::of_bytes(b"weights"),
            input_digest: Digest32::of_bytes(b"input"),
            feature_vector_q24: vec![Q / 4, -Q / 8],
            expected_output_width: 3,
        }
    }

    fn receipt(
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
                drive_q24: if has_output { vec![Q; 3] } else { Vec::new() },
                prediction_q24: if has_output { vec![0; 3] } else { Vec::new() },
                observed_memory_bytes: 4096,
                transient_allocation_bytes: 1024,
                queue_age_micros: 2,
                latency_micros: 11,
                status,
            },
        ))
    }

    struct RecordingControl {
        calls: usize,
        result: Result<NeuronFeatureTerminalStatusV1, NeuronModelError>,
    }

    impl NeuronInferenceControlPort for RecordingControl {
        fn execute_feature(
            &mut self,
            request: &NeuronFeatureRequestV1,
        ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
            self.calls += 1;
            self.result.map(|status| receipt(request, status))
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
    fn exact_historical_result_is_returned_without_second_backend_entry() {
        let journal = TempJournal::new();
        let store = create_store(&journal);
        let inner = RecordingControl {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(store, inner);
        let request = request();

        let first = checked(control.execute_feature(&request));
        let second = checked(control.execute_feature(&request));

        assert_eq!(second, first);
        assert_eq!(control.inner().calls, 1);
        assert_eq!(
            checked(control.store().get(&request.request_id))
                .expect("stored operation")
                .state,
            NeuronFeatureExecutionStateV1::Succeeded
        );
    }

    #[test]
    fn same_id_with_changed_input_is_rejected_without_backend_entry() {
        let journal = TempJournal::new();
        let store = create_store(&journal);
        let inner = RecordingControl {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(store, inner);
        let request = request();
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
    fn reopened_dispatched_operation_is_reconcile_only() {
        let journal = TempJournal::new();
        let request = request();
        {
            let mut store = create_store(&journal);
            checked(store.reserve(request.clone()));
            checked(store.mark_dispatched(&request));
        }

        let inner = RecordingControl {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(reopen_store(&journal), inner);

        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(control.inner().calls, 0);
    }

    #[test]
    fn reopened_reservation_can_enter_backend_once() {
        let journal = TempJournal::new();
        let request = request();
        {
            let mut store = create_store(&journal);
            checked(store.reserve(request.clone()));
        }

        let inner = RecordingControl {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        };
        let mut control = DurableNeuronInferenceControlPortV1::new(reopen_store(&journal), inner);

        assert_eq!(
            checked(control.execute_feature(&request)).status,
            NeuronFeatureTerminalStatusV1::Succeeded
        );
        assert_eq!(control.inner().calls, 1);
    }

    #[test]
    fn backend_error_after_dispatch_cannot_be_retried() {
        let journal = TempJournal::new();
        let request = request();
        let inner = RecordingControl {
            calls: 0,
            result: Err(NeuronModelError::Unavailable),
        };
        let mut control =
            DurableNeuronInferenceControlPortV1::new(create_store(&journal), inner);

        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(
            control.execute_feature(&request),
            Err(NeuronModelError::Indeterminate)
        );
        assert_eq!(control.inner().calls, 1);
        assert_eq!(
            checked(control.store().get(&request.request_id))
                .expect("stored operation")
                .state,
            NeuronFeatureExecutionStateV1::Dispatched
        );
    }

    #[test]
    fn indeterminate_receipt_is_durable_and_not_reexecuted() {
        let journal = TempJournal::new();
        let request = request();
        let inner = RecordingControl {
            calls: 0,
            result: Ok(NeuronFeatureTerminalStatusV1::Indeterminate),
        };
        let mut control =
            DurableNeuronInferenceControlPortV1::new(create_store(&journal), inner);

        let first = checked(control.execute_feature(&request));
        let second = checked(control.execute_feature(&request));
        assert_eq!(first.status, NeuronFeatureTerminalStatusV1::Indeterminate);
        assert_eq!(second, first);
        assert_eq!(control.inner().calls, 1);
    }
}

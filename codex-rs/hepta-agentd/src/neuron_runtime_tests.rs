use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::AgentdNeuronOwner;

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn file(root: &Path, name: &str) -> File {
    checked(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(root.join(name)),
    )
}

#[derive(Clone, Default)]
struct Witness(Arc<Mutex<Option<JournalAnchor>>>);

impl AnchorWitnessStore for Witness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| WitnessStoreError::Unavailable)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        let mut current = self.0.lock().map_err(|_| WitnessStoreError::Unavailable)?;
        if *current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        *current = Some(next);
        Ok(())
    }
}

#[derive(Clone, Copy, Default)]
enum ControlFault {
    #[default]
    None,
    RuntimeTupleDrift,
    TamperedReceipt,
}

#[derive(Default)]
struct Control {
    requests: Vec<NeuronFeatureRequestV1>,
    fault: ControlFault,
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.requests.push(request.clone());
        let tokenizer_digest = match self.fault {
            ControlFault::RuntimeTupleDrift => Digest32::of_bytes(b"wrong-tokenizer"),
            ControlFault::None | ControlFault::TamperedReceipt => Digest32::of_bytes(b"tokenizer"),
        };
        let mut drive_q24 = vec![0; request.expected_output_width];
        drive_q24[0] = Q;
        let mut receipt = checked(build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: Digest32::of_bytes(b"manifest"),
                weights_digest: request.weights_digest,
                tokenizer_digest,
                preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
                quantization_digest: Digest32::of_bytes(b"quantization"),
                runtime_digest: Digest32::of_bytes(b"runtime"),
                device_digest: Digest32::of_bytes(b"device"),
            },
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24,
                prediction_q24: vec![0; request.expected_output_width],
                observed_memory_bytes: 4096,
                transient_allocation_bytes: 2048,
                queue_age_micros: 3,
                latency_micros: 17,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        ));
        if matches!(self.fault, ControlFault::TamperedReceipt) {
            receipt.receipt_digest = Digest32::of_bytes(b"tampered");
        }
        Ok(receipt)
    }
}

fn native() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"head"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: Vec::new(),
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn config(native: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("config.agentd")),
        generation: native.generation,
        model_id: checked(StableId::new("model.1")),
        model_manifest_digest: Digest32::of_bytes(b"manifest"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: native.model_digest,
        weights_digest: Digest32::of_bytes(b"weights"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
        quantization_digest: Digest32::of_bytes(b"quantization"),
        runtime_digest: Digest32::of_bytes(b"runtime"),
        device_digest: Digest32::of_bytes(b"device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 16,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 2_000,
            maximum_false_acceptance_ppm: 5_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    }
}

fn subject() -> StableId {
    checked(StableId::new("subject.agentd"))
}

fn scope() -> JournalScope {
    let subject = subject();
    let raw = subject.as_str().as_bytes();
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
    JournalScope {
        scope_digest: Digest32::of_bytes(&bytes),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

fn tick(sequence: u64, checkpoint_digest: Digest32) -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: checked(StableId::new(format!("tick.agentd.{sequence}"))),
        subject_id: subject(),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1_000,
        checkpoint_digest,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

#[test]
fn owner_tick_uses_typed_control_and_preserves_journal_lifecycle() {
    let root = checked(tempfile::tempdir());
    let native = native();
    let config = config(&native);
    let witness = Witness::default();
    let runtime = checked(NeuronRuntime::bootstrap(
        file(root.path(), "journal"),
        native.clone(),
        scope(),
        /*max_records*/ 1,
        config.clone(),
        witness.clone(),
    ));
    let mut owner = AgentdNeuronOwner::new(runtime, Control::default());
    let input = tick(/*sequence*/ 1, Digest32::ZERO);
    let expected_request = NeuronFeatureRequestV1 {
        request_id: input.tick_id.clone(),
        generation: config.generation,
        model_id: config.model_id.clone(),
        encoder_digest: config.encoder_digest,
        head_digest: config.head_digest,
        weights_digest: config.weights_digest,
        input_digest: checked(input.semantic_digest()),
        feature_vector_q24: input.feature_vector_q24.clone(),
        expected_output_width: native.width,
    };
    let first = checked(owner.tick(input));
    assert_eq!(
        owner.inference_control_mut().requests,
        vec![expected_request]
    );
    assert_eq!(first.tick.active_indices, vec![0]);
    assert!(!first.tick.abstain);
    assert!(!first.signal.authority.grants_any());
    assert_eq!(
        first.model_runtime.tokenizer_digest,
        config.tokenizer_digest
    );
    checked(owner.rollover(file(root.path(), "successor"), /*max_records*/ 1));
    let second = checked(owner.tick(tick(/*sequence*/ 2, first.tick.checkpoint_after)));
    let final_anchor = JournalAnchor {
        sequence: 2,
        checkpoint_digest: second.tick.checkpoint_after,
    };
    assert_eq!(
        checked(owner.runtime().current_anchor()),
        Some(final_anchor)
    );
    assert_eq!(checked(witness.current()), Some(final_anchor));
    assert_eq!(owner.inference_control_mut().requests.len(), 2);
    drop(owner);

    let runtime = checked(NeuronRuntime::recover_chain_root(
        file(root.path(), "journal"),
        native,
        scope(),
        /*max_records*/ 1,
        config,
        witness.clone(),
    ));
    let mut recovered = AgentdNeuronOwner::new(runtime, Control::default());
    checked(recovered.recover_next_segment(file(root.path(), "successor"), /*max_records*/ 1));
    assert_eq!(
        checked(recovered.runtime().current_anchor()),
        Some(final_anchor)
    );
    assert_eq!(checked(witness.current()), Some(final_anchor));
    checked(recovered.rollover(file(root.path(), "third"), /*max_records*/ 1));
    let third = checked(recovered.tick(tick(/*sequence*/ 3, final_anchor.checkpoint_digest)));
    assert_eq!(third.tick.checkpoint_before, final_anchor.checkpoint_digest);
    assert_eq!(recovered.inference_control_mut().requests.len(), 1);
}

#[test]
fn owner_rejects_tuple_drift_and_tampered_receipt_without_mutation() {
    for (fault, expected_error) in [
        (
            ControlFault::RuntimeTupleDrift,
            NeuronRuntimeError::ModelBindingMismatch,
        ),
        (
            ControlFault::TamperedReceipt,
            NeuronRuntimeError::Model(NeuronModelError::Rejected),
        ),
    ] {
        let root = checked(tempfile::tempdir());
        let native = native();
        let witness = Witness::default();
        let runtime = checked(NeuronRuntime::bootstrap(
            file(root.path(), "journal"),
            native.clone(),
            scope(),
            /*max_records*/ 8,
            config(&native),
            witness.clone(),
        ));
        let before = checked(std::fs::read(root.path().join("journal")));
        let mut owner = AgentdNeuronOwner::new(
            runtime,
            Control {
                requests: Vec::new(),
                fault,
            },
        );
        assert_eq!(
            owner.tick(tick(/*sequence*/ 1, Digest32::ZERO)),
            Err(expected_error)
        );
        assert_eq!(checked(owner.runtime().current_anchor()), None);
        assert_eq!(checked(witness.current()), None);
        assert_eq!(checked(std::fs::read(root.path().join("journal"))), before);
        assert_eq!(owner.inference_control_mut().requests.len(), 1);
    }
}

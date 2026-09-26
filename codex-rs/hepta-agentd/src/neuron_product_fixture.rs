//! Qualification fixture using the real durable owner and the real
//! inference-control adapter. The feature backend below is a deterministic test
//! double, not evidence of selected Laya execution or independent calibration.
use super::digest;
use super::generation;
use super::id;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Digest32;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

pub(super) struct FixtureControl {
    pub calls: AtomicUsize,
    pub force_ood: AtomicBool,
    after_execute: Mutex<Option<Box<dyn FnOnce() + Send>>>,
    operation_file: std::fs::File,
}
impl FixtureControl {
    pub fn after_execute(&self, hook: impl FnOnce() + Send + 'static) {
        *self.after_execute.lock().expect("fixture hook") = Some(Box::new(hook));
    }
    pub fn operation_bytes(&self) -> u64 {
        self.operation_file
            .metadata()
            .expect("operation metadata")
            .len()
    }
}

const Q: i64 = 1 << 24;

struct FixtureFeaturePort(Arc<FixtureControl>);
impl NeuronInferenceControlPort for FixtureFeaturePort {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        if let Some(hook) = self.0.after_execute.lock().expect("fixture hook").take() {
            hook();
        }
        let prediction = if self.0.force_ood.load(Ordering::SeqCst) {
            -8 * Q
        } else {
            0
        };
        build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: digest("manifest"),
                weights_digest: digest("weights"),
                tokenizer_digest: digest("tokenizer"),
                preprocessor_digest: digest("preprocessor"),
                quantization_digest: digest("quantization"),
                runtime_digest: digest("runtime"),
                device_digest: digest("device"),
            },
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24: vec![Q, Q / 2, 0, 0, 0],
                prediction_q24: vec![prediction; request.expected_output_width],
                observed_memory_bytes: 4096,
                transient_allocation_bytes: 8192,
                queue_age_micros: 1,
                latency_micros: 5,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Rejected)
    }
}

struct FixtureSelectedAdmission(Digest32);
impl NeuronAdmissionGuard for FixtureSelectedAdmission {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if config.semantic_digest().ok() != Some(self.0) {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        Ok(())
    }
}

pub(super) fn invocation(
    objective: Digest32,
    ndu: Digest32,
) -> (crate::AgentdNeuronInvocationV1, Arc<FixtureControl>) {
    let native = SparseConfig {
        model_digest: digest("head"),
        normalization_digest: digest("normalization"),
        generation: generation(7),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: id("neuron.config.7"),
        generation: generation(7),
        model_id: id("model.7"),
        model_manifest_digest: digest("manifest"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest().expect("native digest"),
        input_feature_dimension: 3,
        state_width: 5,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
            generation: generation(7),
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 5_000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    let features = vec![Q / 4, Q / 8, -Q / 8];
    let input = NeuronTickInputV1 {
        tick_id: id("run:agentd-intelligence"),
        subject_id: id("subject.agentd"),
        logical_sequence: 1,
        monotonic_time_micros: 1000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: objective,
        ndu_snapshot_digest: ndu,
        body_generation: Some(7),
        modulator_digest: None,
    };
    let scope = input.journal_scope().expect("scope");
    let admission = FixtureSelectedAdmission(config.semantic_digest().expect("configuration"));
    let witness = FileAnchorWitnessStore::open(
        tempfile::tempfile().expect("witness file"),
        scope,
        generation(7),
        /*max_records*/ 32,
    )
    .expect("witness");
    let operations = tempfile::tempfile().expect("operation store");
    let control = Arc::new(FixtureControl {
        calls: AtomicUsize::new(0),
        force_ood: AtomicBool::new(false),
        after_execute: Mutex::new(None),
        operation_file: operations.try_clone().expect("observation handle"),
    });
    let runtime = NeuronRuntime::bootstrap(
        tempfile::tempfile().expect("journal"),
        operations,
        native,
        scope,
        /*max_records*/ 16,
        /*max_operations*/ 32,
        config,
        witness,
    )
    .expect("durable neuron");
    let handle = crate::AgentdNeuronOwner::new(runtime, FixtureFeaturePort(Arc::clone(&control)))
        .into_shared(admission)
        .expect("shared owner");
    (
        handle
            .prepare(id("run:agentd-intelligence"), digest("body"), input)
            .expect("invocation"),
        control,
    )
}

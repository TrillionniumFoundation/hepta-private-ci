//! Actual NeuronModelPort computes the cell query and frozen readout in Rust.
use crate::cell::Cell;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::time::Instant;
pub const Q: i64 = 1 << 24;
pub const LIMIT: usize = 1024;
pub fn marker(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}
pub fn id(text: &str) -> StableId {
    StableId::new(text).expect("bounded static native identifier")
}

pub fn configuration(model: Digest32) -> (SparseConfig, NeuronRuntimeConfigV1) {
    let generation = Generation::new(1).expect("generation one");
    let native = SparseConfig {
        model_digest: model,
        normalization_digest: model,
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: 0,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 5,
        threshold_rate_q24: 0,
        threshold_min_q24: 0,
        threshold_max_q24: 0,
        eligibility_decay_q24: 0,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: id("hepta.native-cell.v1"),
        generation,
        model_id: id("hepta.finite-cell-and-readout.v1"),
        model_manifest_digest: model,
        encoder_digest: marker("rust.finite-cell.causal-inputs.v1"),
        head_digest: model,
        weights_digest: model,
        tokenizer_digest: marker("numeric.no-tokenizer"),
        preprocessor_digest: marker("driver-duration-horizon-reset-count.q24.v1"),
        quantization_digest: marker("nonnegative-five-features.q24.v1"),
        runtime_digest: marker(env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST")),
        device_digest: marker(std::env::consts::ARCH),
        normalization_digest: model,
        native_config_digest: native.digest().expect("bounded native config"),
        input_feature_dimension: 5,
        state_width: 5,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: marker("research.calibration-unestablished.worst-case"),
            ood_artifact_digest: marker("research.ood-unestablished.worst-case"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: LIMIT as u64,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 16 * Q,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 20,
            measured_ece_ppm: 1_000_000,
            maximum_ece_ppm: 1_000_000,
            measured_false_acceptance_ppm: 1_000_000,
            maximum_false_acceptance_ppm: 1_000_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 10_000_000,
            p99_latency_micros: 30_000_000,
            transient_allocation_bytes: 1 << 24,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    (native, config)
}

pub struct CellPort {
    pub config: NeuronRuntimeConfigV1,
    pub expected_input: Vec<i64>,
    pub cell: Cell,
    pub driver: f64,
    pub horizon_micros: u64,
    pub last_features: Option<[f64; 5]>,
    pub execution_nanos: u64,
}
impl NeuronModelPort for CellPort {
    fn execute(&mut self, request: &NeuronModelRequestV1) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let start = Instant::now();
        if request.feature_vector_q24 != self.expected_input || request.weights_digest != self.config.weights_digest {
            return Err(NeuronModelError::Rejected);
        }
        let features = self
            .cell
            .query(self.driver, self.horizon_micros)
            .map_err(|_| NeuronModelError::Rejected)?;
        let drive = features
            .iter()
            .map(|x| (x * Q as f64).round() as i64)
            .collect::<Vec<_>>();
        self.last_features = Some(features);
        self.execution_nanos = start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX);
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.config.model_id.clone(),
            model_manifest_digest: self.config.model_manifest_digest,
            weights_digest: self.config.weights_digest,
            tokenizer_digest: self.config.tokenizer_digest,
            preprocessor_digest: self.config.preprocessor_digest,
            quantization_id: id("native-cell.q24.v1"),
            quantization_digest: self.config.quantization_digest,
            backend_id: id("rust.native-cell-and-readout"),
            runtime_digest: self.config.runtime_digest,
            device_identity_digest: self.config.device_digest,
            latency_micros: start.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            resident_bytes: 512,
        };
        let prediction = vec![0; 5];
        let output_digest =
            canonical_model_output_digest_v1(&drive, &prediction, &receipt).map_err(|_| NeuronModelError::Rejected)?;
        Ok(NeuronModelOutputV1 {
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            output_digest,
            drive_q24: drive,
            prediction_q24: prediction,
            queue_age_micros: 0,
            transient_allocation_bytes: 512,
            runtime_receipt: receipt,
        })
    }
}

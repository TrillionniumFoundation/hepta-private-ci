//! The actual NeuronModelPort executes the frozen learned model in Rust.
use crate::model::ACTIONS;
use crate::model::Identity;
use crate::model::Model;
use crate::model::Prediction;
use crate::model::Request;
use crate::model::State;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::time::Instant;
pub const Q: i64 = 1 << 24;
pub const LIMIT: usize = 1024;
pub fn marker(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
pub fn id(s: &str) -> StableId {
    StableId::new(s).expect("bounded owner identity")
}

pub fn configuration(model: Digest32) -> (SparseConfig, NeuronRuntimeConfigV1) {
    let generation = Generation::new(1).expect("generation one");
    let sparse = SparseConfig {
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
        config_id: id("hepta.r7-native-policy.v1"),
        generation,
        model_id: id("hepta.r7-learned-finite-policy.v1"),
        model_manifest_digest: model,
        encoder_digest: model,
        head_digest: model,
        weights_digest: model,
        tokenizer_digest: marker("numeric.public18.no-tokenizer"),
        preprocessor_digest: marker("public18.q24-binding.raw-f64-model.v1"),
        quantization_digest: marker("selected-action.onehot.q24.v1"),
        runtime_digest: marker(env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST")),
        device_digest: marker(std::env::consts::ARCH),
        normalization_digest: model,
        native_config_digest: sparse.digest().expect("bounded sparse configuration"),
        input_feature_dimension: 18,
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
    (sparse, config)
}

pub struct Port<'a> {
    pub config: NeuronRuntimeConfigV1,
    pub expected_input: Vec<i64>,
    pub model: &'a Model,
    pub identity: &'a Identity,
    pub before: &'a State,
    pub request: &'a Request,
    pub result: Option<(State, Prediction)>,
}

impl NeuronModelPort for Port<'_> {
    fn execute(&mut self, request: &NeuronModelRequestV1) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let start = Instant::now();
        if request.feature_vector_q24 != self.expected_input
            || request.weights_digest != self.config.weights_digest
        {
            return Err(NeuronModelError::Rejected);
        }
        let result = self
            .model
            .predict(self.identity, self.before, self.request)
            .map_err(|_| NeuronModelError::Rejected)?;
        let mut drive: Vec<_> = ACTIONS
            .iter()
            .map(|action| if *action == result.1.action { Q } else { 0 })
            .collect();
        drive.push(0); // SparseConfig requires top_k <= width/5; fifth channel is an explicit zero pad.
        self.result = Some(result);
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.config.model_id.clone(),
            model_manifest_digest: self.config.model_manifest_digest,
            weights_digest: self.config.weights_digest,
            tokenizer_digest: self.config.tokenizer_digest,
            preprocessor_digest: self.config.preprocessor_digest,
            quantization_id: id("r7-action.q24.v1"),
            quantization_digest: self.config.quantization_digest,
            backend_id: id("rust.r7-finite-learned-policy"),
            runtime_digest: self.config.runtime_digest,
            device_identity_digest: self.config.device_digest,
            latency_micros: start.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            resident_bytes: 1 << 17,
        };
        let prediction = vec![0; 5];
        let output_digest = canonical_model_output_digest_v1(&drive, &prediction, &receipt)
            .map_err(|_| NeuronModelError::Rejected)?;
        Ok(NeuronModelOutputV1 {
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            output_digest,
            drive_q24: drive,
            prediction_q24: prediction,
            queue_age_micros: 0,
            transient_allocation_bytes: 1 << 17,
            runtime_receipt: receipt,
        })
    }
}

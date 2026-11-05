//! Qualification fixtures: real native Cell mechanisms, controlled model receipts.

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const Q: i64 = 1 << 24;

pub(crate) fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

pub(crate) fn id(value: &str) -> StableId {
    checked(StableId::new(value))
}

pub(crate) fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(crate) fn definition() -> CellDefinitionV1 {
    let native = SparseConfig {
        model_digest: d("head"),
        normalization_digest: d("normalizer"),
        generation: checked(Generation::new(1)),
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
    let runtime = NeuronRuntimeConfigV1 {
        config_id: id("config"),
        generation: native.generation,
        model_id: id("model"),
        model_manifest_digest: d("manifest"),
        encoder_digest: d("encoder"),
        head_digest: native.model_digest,
        weights_digest: d("weights"),
        tokenizer_digest: d("tokenizer"),
        preprocessor_digest: d("preprocessor"),
        quantization_digest: d("quantization"),
        runtime_digest: d("runtime"),
        device_digest: d("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 2,
        state_width: 5,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: d("calibration"),
            ood_artifact_digest: d("ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 1000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 1000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1000,
            p99_latency_micros: 2000,
            transient_allocation_bytes: 16384,
            checkpoint_bytes: 8192,
            write_amplification_ppm: 4_000_000,
        },
    };
    CellDefinitionV1 {
        cell_id: id("cell"),
        bundle_digest: d("bundle"),
        state_schema_digest: d("schema"),
        runtime,
        native,
        candidates: vec![
            CellCandidateV1 {
                candidate_id: id("a"),
                activation_index: 0,
                kind: CellCandidateKindV1::Action,
            },
            CellCandidateV1 {
                candidate_id: id("b"),
                activation_index: 1,
                kind: CellCandidateKindV1::SlowPath,
            },
            CellCandidateV1 {
                candidate_id: id("abstain"),
                activation_index: 4,
                kind: CellCandidateKindV1::Abstain,
            },
        ],
        max_input_bytes: 65_536,
        max_queue_age_micros: 1000,
        max_resident_bytes: 16384,
    }
}

pub(crate) fn scope(run: &str) -> CellScopeV1 {
    CellScopeV1 {
        agent_id: id("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"),
        cell_id: id("cell"),
        run_id: id(run),
        principal_digest: d("principal"),
    }
}

pub(crate) fn input(run: &str) -> CellStepInputV1 {
    CellStepInputV1 {
        operation_id: id("operation"),
        scope: scope(run),
        source_frontier: d("frontier"),
        objective_digest: d("objective"),
        ndu_snapshot_digest: d("ndu"),
        monotonic_micros: 10,
        deadline_micros: 100,
        observation: b"input".to_vec(),
        candidates: definition().candidates.iter().map(|c| CellCandidateMaskV1 {
            candidate_id: c.candidate_id.clone(),
            allowed: true,
        }).collect(),
    }
}

pub(crate) struct Encoder;

impl CellInputEncoderV1 for Encoder {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        Ok(CellEncodedInputV1 {
            encoder_digest: request.encoder_digest,
            feature_vector_q24: vec![Q, Q / 2],
            consumed_bytes: request.observation.len(),
            truncated_bytes: 0,
        })
    }
}

pub(crate) struct Model {
    pub(crate) calls: Arc<AtomicUsize>,
    pub(crate) reads: Arc<AtomicUsize>,
    pub(crate) latency: u64,
    pub(crate) lose_response: bool,
    receipt: Option<codex_hepta_infer_core::NeuronFeatureReceiptV1>,
}

impl Model {
    pub(crate) fn new(latency: u64, lose_response: bool) -> Self {
        Self {
            calls: Arc::new(AtomicUsize::new(0)),
            reads: Arc::new(AtomicUsize::new(0)),
            latency,
            lose_response,
            receipt: None,
        }
    }
}

impl NeuronInferenceControlPort for Model {
    fn execute_feature(
        &mut self,
        request: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, NeuronModelError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let receipt = feature_receipt(request, self.latency);
        self.receipt = Some(receipt.clone());
        if self.lose_response { return Err(NeuronModelError::Indeterminate); }
        Ok(receipt)
    }
}

impl CellInferenceReadbackPortV1 for Model {
    fn read_feature(
        &mut self,
        _request: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<Option<codex_hepta_infer_core::NeuronFeatureReceiptV1>, NeuronModelError> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        Ok(self.receipt.clone())
    }
}

pub(crate) fn feature_receipt(
    request: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    latency: u64,
) -> codex_hepta_infer_core::NeuronFeatureReceiptV1 {
    use codex_hepta_infer_core::*;
    checked(build_neuron_feature_receipt_v1(
        request,
        NeuronModelRuntimeTupleV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: d("manifest"),
            weights_digest: request.weights_digest,
            tokenizer_digest: d("tokenizer"),
            preprocessor_digest: d("preprocessor"),
            quantization_digest: d("quantization"),
            runtime_digest: d("runtime"),
            device_digest: d("device"),
        },
        NeuronFeatureObservationV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            drive_q24: vec![Q, Q / 2, 0, 0, 0],
            prediction_q24: vec![0; 5],
            queue_age_micros: 3,
            latency_micros: latency,
            observed_memory_bytes: 4096,
            transient_allocation_bytes: 4096,
            status: NeuronFeatureTerminalStatusV1::Succeeded,
        },
    ))
}


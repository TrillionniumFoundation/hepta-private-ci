use crate::*;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
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
        max_input_bytes: 64,
        max_queue_age_micros: 1000,
        max_resident_bytes: 16384,
    }
}

pub(crate) fn scope(run: &str) -> CellScopeV1 {
    CellScopeV1 {
        agent_id: id("agent"),
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

pub(crate) fn owner(runs: &[&str]) -> CellPartitionOwnerV1 {
    let mut owner = checked(CellPartitionOwnerV1::new(
        /*max_partitions*/8,
        /*max_receipts_per_partition*/8,
    ));
    for run in runs {
        checked(owner.admit(scope(run), &definition(), d("frontier"), /*writer_epoch*/1));
    }
    owner
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
    pub(crate) calls: usize,
    pub(crate) latency: u64,
}

impl NeuronInferenceControlPort for Model {
    fn execute_feature(
        &mut self,
        request: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, NeuronModelError> {
        self.calls += 1;
        Ok(feature_receipt(request, self.latency))
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

pub(crate) fn proposal(
    owner: &mut impl CellStateOwnerV1,
    request: CellStepInputV1,
) -> CellStateProposalV1 {
    let now = request.monotonic_micros;
    let prepared = checked(prepare_cell_step(&definition(), owner, &Encoder, request, now));
    let inferred = checked(infer_cell(prepared, owner, &mut Model { calls: 0, latency: 20 }, now + 1));
    checked(decide_cell(inferred, now + 2))
}

pub(crate) struct RecordedControl {
    pub(crate) executions: usize,
    pub(crate) reads: usize,
    pub(crate) failure: Option<NeuronModelError>,
    pub(crate) receipt: Option<NeuronFeatureReceiptV1>,
}

impl RecordedControl {
    pub(crate) fn new() -> Self {
        Self { executions: 0, reads: 0, failure: None, receipt: None }
    }
}

impl NeuronInferenceControlPort for RecordedControl {
    fn execute_feature(&mut self, request: &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.executions += 1;
        let receipt = feature_receipt(request, /*latency*/20);
        self.receipt = Some(receipt.clone());
        match self.failure {
            Some(error) => Err(error),
            None => Ok(receipt),
        }
    }
}

impl CellInferenceReadbackPortV1 for RecordedControl {
    fn read_feature(&mut self, _: &NeuronFeatureRequestV1) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.reads += 1;
        Ok(self.receipt.clone())
    }
}


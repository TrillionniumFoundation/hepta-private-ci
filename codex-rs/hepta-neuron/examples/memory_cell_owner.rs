//! Exact-source owner composition against an externally supplied learned artifact.
//! The grant/calibration inputs below are explicit qualification fixtures.
#[allow(dead_code, reason = "same Agentd state handoff, no duplicate runtime")]
#[path = "../../hepta-agentd/src/neuron_runtime.rs"]
mod agentd_owner;
#[allow(dead_code, reason = "same numerical driver as the worker-host library")]
#[path = "../../hepta-infer-worker-host/src/memory_cell_driver.rs"]
mod memory_cell_driver;
#[allow(
    dead_code,
    reason = "exercise the exact worker source without a second implementation"
)]
#[path = "../../hepta-infer-worker-host/src/model_worker.rs"]
mod model_worker;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use memory_cell_driver::MemoryCellBindingV1;
use memory_cell_driver::MemoryCellDriver;
use model_worker::*;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::path::Path;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Vector {
    input_q24: Vec<i64>,
    expected_probability_q24: i64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Parity {
    weights_sha256: String,
    maximum_absolute_q24_error: i64,
    vectors: Vec<Vector>,
    trained_tensor_digest: String,
}
struct Control {
    worker: InferenceWorker<MemoryCellDriver>,
    requests: BTreeMap<String, NeuronFeatureRequest>,
    predictions: Vec<Vec<i64>>,
}
impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        input: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let request = self
            .requests
            .remove(input.request_id.as_str())
            .ok_or(NeuronModelError::Rejected)?;
        if request.input_digest != input.input_digest.to_string()
            || request.feature_vector_q24 != input.feature_vector_q24
            || request.weights_digest != input.weights_digest.to_string()
            || request.head_digest != input.head_digest.to_string()
            || request.encoder_digest != input.encoder_digest.to_string()
            || request.expected_output_width != input.expected_output_width
        {
            return Err(NeuronModelError::Rejected);
        }
        let receipt = self
            .worker
            .run_neuron_features_receipt(1, input.model_id.as_str(), request)
            .map_err(|_| NeuronModelError::Rejected)?;
        self.predictions.push(receipt.prediction_q24.clone());
        Ok(receipt)
    }
}
fn file(path: &Path) -> std::io::Result<fs::File> {
    OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .truncate(false)
        .open(path)
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let [input, output] = args.as_slice() else {
        return Err("memory_cell_owner INPUT_EXPORT OUTPUT_NEW_DIR".into());
    };
    let input = Path::new(input);
    let output = Path::new(output);
    fs::create_dir(output)?;
    let payload = fs::read(input.join("circuit.json"))?;
    let info: serde_json::Value = serde_json::from_slice(&payload)?;
    let parity: Parity = serde_json::from_slice(&fs::read(input.join("parity.json"))?)?;
    if parity.vectors.is_empty()
        || parity.vectors.len() > 32
        || parity.maximum_absolute_q24_error != 64
        || parity.trained_tensor_digest.len() != 64
    {
        return Err("invalid independent parity input".into());
    }
    let binding = MemoryCellBindingV1 {
        encoder_digest: info["encoder_digest"].as_str().ok_or("encoder")?.parse()?,
        dataset_digest: info["dataset_digest"].as_str().ok_or("dataset")?.parse()?,
        scope_digest: info["scope_digest"].as_str().ok_or("scope")?.parse()?,
    };
    let manifest = ModelManifest {
        model_id: "memory.circuit.1".into(),
        model_digest: Digest32::of_bytes(parity.weights_sha256.as_bytes()).to_string(),
        weights_digest: parity.weights_sha256,
        tokenizer_digest: binding.encoder_digest.to_string(),
        preprocessor_digest: Digest32::of_bytes(b"frozen-query-times-document-vector.v1")
            .to_string(),
        quantization_digest: MemoryCellDriver::quantization_digest().to_string(),
        runtime_digest: MemoryCellDriver::runtime_digest().to_string(),
        device_digest: Digest32::of_bytes(b"qualification-native-cpu").to_string(),
        maximum_tokens: 512,
    };
    let driver = MemoryCellDriver::from_pinned_bytes(&payload, manifest.clone(), &binding)?;
    let grant = ResourceGrant {
        grant_id: "qualification.grant".into(),
        authority_epoch: 1,
        generation: 1,
        expires_at_ms: 100,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 1,
        maximum_memory_bytes: 1 << 20,
        semantic_digest: Digest32::of_bytes(b"qualification-only-grant").to_string(),
    };
    let mut worker = InferenceWorker::new(1, "qualification.worker".into(), 1, grant, driver)?;
    worker.load_model(1, manifest.clone())?;
    let control = Control {
        worker,
        requests: BTreeMap::new(),
        predictions: Vec::new(),
    };
    let q = 1_i64 << 24;
    let generation = Generation::new(1)?;
    let native = SparseConfig {
        model_digest: MemoryCellDriver::head_digest(),
        normalization_digest: Digest32::of_bytes(b"unit-feature-product"),
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: q / 2,
        inhibition_gain_q24: q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: q / 2,
        threshold_rate_q24: q / 8,
        threshold_min_q24: -q,
        threshold_max_q24: q,
        eligibility_decay_q24: q / 2,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: StableId::new("qualification.memory.config")?,
        generation,
        model_id: StableId::new(manifest.model_id.clone())?,
        model_manifest_digest: manifest.model_digest.parse()?,
        encoder_digest: binding.encoder_digest,
        head_digest: native.model_digest,
        weights_digest: manifest.weights_digest.parse()?,
        tokenizer_digest: manifest.tokenizer_digest.parse()?,
        preprocessor_digest: manifest.preprocessor_digest.parse()?,
        quantization_digest: manifest.quantization_digest.parse()?,
        runtime_digest: manifest.runtime_digest.parse()?,
        device_digest: manifest.device_digest.parse()?,
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: parity.vectors[0].input_q24.len(),
        state_width: 5,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"qualification-only-calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"qualification-only-ood"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 64,
            zero_confidence_error_q24: 16 * q,
            maximum_in_domain_error_q24: 8 * q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 1,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 0,
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
    let subject = StableId::new("qualification.memory.subject")?;
    let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
    scope_bytes.extend_from_slice(subject.as_str().as_bytes());
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&scope_bytes),
        objective_digest: Digest32::of_bytes(b"qualification-memory-objective"),
    };
    let witness =
        FileAnchorWitnessStore::open(file(&output.join("witness"))?, scope, generation, 64)?;
    let runtime = NeuronRuntime::bootstrap(
        file(&output.join("journal"))?,
        native.clone(),
        scope,
        64,
        config.clone(),
        witness,
    )?;
    let mut owner = agentd_owner::AgentdNeuronOwner::new(runtime, control);
    let mut checkpoint = Digest32::ZERO;
    let mut observed = Vec::new();
    for (index, vector) in parity.vectors.iter().enumerate() {
        let sequence = index as u64 + 1;
        let input = NeuronTickInputV1 {
            tick_id: StableId::new(format!("memory.tick.{sequence}"))?,
            subject_id: subject.clone(),
            logical_sequence: sequence,
            monotonic_time_micros: sequence * 1000,
            checkpoint_digest: checkpoint,
            input_feature_digest: canonical_feature_vector_digest_v1(&vector.input_q24),
            feature_vector_q24: vector.input_q24.clone(),
            objective_digest: scope.objective_digest,
            ndu_snapshot_digest: Digest32::of_bytes(b"qualification-ndu"),
            body_generation: Some(1),
            modulator_digest: None,
        };
        let model_request = owner.runtime().model_request(&input)?;
        let mut request = NeuronFeatureRequest {
            authorization: WorkerRequest {
                request_id: input.tick_id.to_string(),
                reservation_id: format!("qualification.reservation.{sequence}"),
                model_digest: manifest.model_digest.clone(),
                payload_digest: "1".repeat(64),
                maximum_tokens: 1,
                deadline_ms: 99,
                lease_payload_digest: "1".repeat(64),
                reservation_model_digest: manifest.model_digest.clone(),
                reservation_maximum_tokens: 512,
                cancelled: false,
            },
            encoder_digest: binding.encoder_digest.to_string(),
            head_digest: config.head_digest.to_string(),
            weights_digest: manifest.weights_digest.clone(),
            input_digest: model_request.input_digest.to_string(),
            feature_vector_q24: vector.input_q24.clone(),
            expected_output_width: 5,
        };
        let binding = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = binding.clone();
        request.authorization.lease_payload_digest = binding;
        owner
            .inference_control_mut()
            .requests
            .insert(input.tick_id.to_string(), request);
        let result = owner.tick(input)?;
        let prediction = owner
            .inference_control_mut()
            .predictions
            .last()
            .ok_or("missing prediction")?[1];
        let error = prediction.abs_diff(vector.expected_probability_q24);
        if error > parity.maximum_absolute_q24_error as u64 {
            return Err("torch/native numerical parity failed".into());
        }
        checkpoint = result.tick.checkpoint_after;
        observed.push(serde_json::json!({"sequence": sequence, "absolute_q24_error": error,
            "checkpoint": checkpoint.to_string(), "model_runtime_digest": result.signal.model_runtime_digest.to_string()}));
    }
    let anchor = owner
        .runtime()
        .current_anchor()?
        .ok_or("missing committed anchor")?;
    drop(owner);
    let witness =
        FileAnchorWitnessStore::open(file(&output.join("witness"))?, scope, generation, 64)?;
    let recovered = NeuronRuntime::recover(
        file(&output.join("journal"))?,
        native,
        scope,
        64,
        config,
        anchor,
        witness,
    )?;
    if recovered.current_anchor()? != Some(anchor) {
        return Err("reopen lost acknowledged state".into());
    }
    fs::write(
        output.join("owner-report.json"),
        serde_json::to_vec_pretty(&serde_json::json!({
            "schema": "hepta.memory-cell.owner-execution.v1", "real_tensor_artifact": true,
            "observations": observed, "journal_reopened": true, "authority_profile": "qualification-fixture",
            "calibration_profile": "fixture-not-measured-product-calibration", "production_activated": false, "daemon_started": false
        }))?,
    )?;
    Ok(())
}

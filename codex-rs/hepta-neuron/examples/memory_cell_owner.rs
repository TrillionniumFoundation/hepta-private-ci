//! Exact-source owner composition against an externally supplied learned artifact.
//! The grant/calibration inputs below are explicit qualification fixtures.
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_infer_worker_host::MemoryCellBindingV1;
use codex_hepta_infer_worker_host::MemoryCellDriver;
use codex_hepta_infer_worker_host::model_worker::InferenceWorker;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::NeuronFeatureRequest;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_infer_worker_host::model_worker::canonical_neuron_feature_payload_digest;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

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
// The immutable Cell request reaches this worker only after the original
// DurableInferenceControl has durably consumed its dispatch token.
struct MemoryWorker {
    worker: Mutex<InferenceWorker<MemoryCellDriver>>,
    runtime: NeuronModelRuntimeTupleV1,
}
impl NeuronFeatureWorkerV1 for MemoryWorker {
    fn runtime_tuple(&self) -> &NeuronModelRuntimeTupleV1 {
        &self.runtime
    }

    fn execute(
        &self,
        input: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureObservationV1, NeuronModelError> {
        let mut request = NeuronFeatureRequest {
            authorization: WorkerRequest {
                request_id: input.request_id.to_string(),
                reservation_id: format!("qualification.reservation.{}", input.request_id),
                model_digest: self.runtime.model_manifest_digest.to_string(),
                payload_digest: "1".repeat(64),
                maximum_tokens: 1,
                deadline_ms: 99,
                lease_payload_digest: "1".repeat(64),
                reservation_model_digest: self.runtime.model_manifest_digest.to_string(),
                reservation_maximum_tokens: 512,
                cancelled: false,
            },
            encoder_digest: input.encoder_digest.to_string(),
            head_digest: input.head_digest.to_string(),
            weights_digest: input.weights_digest.to_string(),
            input_digest: input.input_digest.to_string(),
            feature_vector_q24: input.feature_vector_q24.clone(),
            expected_output_width: input.expected_output_width,
        };
        let payload_digest = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload_digest.clone();
        request.authorization.lease_payload_digest = payload_digest;
        let receipt = self
            .worker
            .try_lock()
            .map_err(|_| NeuronModelError::Rejected)?
            .run_neuron_features_receipt(1, input.model_id.as_str(), request)
            .map_err(|_| NeuronModelError::Rejected)?;
        verify_neuron_feature_receipt_v1(input, &receipt)
            .map_err(|_| NeuronModelError::Rejected)?;
        if receipt.runtime_tuple != self.runtime {
            return Err(NeuronModelError::Rejected);
        }
        Ok(NeuronFeatureObservationV1 {
            encoder_digest: receipt.encoder_digest,
            head_digest: receipt.head_digest,
            drive_q24: receipt.drive_q24,
            prediction_q24: receipt.prediction_q24,
            observed_memory_bytes: receipt.observed_memory_bytes,
            transient_allocation_bytes: receipt.transient_allocation_bytes,
            queue_age_micros: receipt.queue_age_micros,
            latency_micros: receipt.latency_micros,
            status: receipt.status,
        })
    }
}

// The qualification artifact supplies Q24 features; no expected prediction or
// mutable shared state enters this identity encoder.
struct QualificationEncoder {
    encoder_digest: Digest32,
    dimension: usize,
}
impl CellInputEncoderV1 for QualificationEncoder {
    fn encode(
        &self,
        input: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        if input.encoder_digest != self.encoder_digest
            || self.dimension.checked_mul(8) != Some(input.observation.len())
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        let feature_vector_q24 = input
            .observation
            .as_chunks::<8>()
            .0
            .iter()
            .copied()
            .map(i64::from_be_bytes)
            .collect();
        Ok(CellEncodedInputV1 {
            encoder_digest: self.encoder_digest,
            feature_vector_q24,
            consumed_bytes: input.observation.len(),
            truncated_bytes: 0,
        })
    }
}
// Reconstruct the original report identity from the committed representation
// and its actual measurements. The output digest first authenticates this
// frozen tuple; the final domain is the original Neuron signal binding.
fn committed_model_runtime_digest(
    config: &NeuronRuntimeConfigV1,
    receipt: &CellDecisionReceiptV1,
) -> Result<Digest32, Box<dyn Error>> {
    let runtime_receipt = LocalModelRuntimeReceiptV1 {
        model_id: config.model_id.clone(),
        model_manifest_digest: config.model_manifest_digest,
        weights_digest: config.weights_digest,
        tokenizer_digest: config.tokenizer_digest,
        preprocessor_digest: config.preprocessor_digest,
        quantization_id: StableId::new(format!("quantization:{}", config.quantization_digest))?,
        quantization_digest: config.quantization_digest,
        backend_id: StableId::new(format!("runtime:{}", config.runtime_digest))?,
        runtime_digest: config.runtime_digest,
        device_identity_digest: config.device_digest,
        latency_micros: receipt.cost.model_latency_micros,
        resident_bytes: receipt.cost.resident_bytes,
    };
    if canonical_model_output_digest_v1(
        &receipt.representation.drive_q24,
        &receipt.representation.prediction_q24,
        &runtime_receipt,
    )? != receipt.model_output_digest
    {
        return Err("committed runtime identity mismatch".into());
    }
    let mut bytes = b"hepta.neuron.model-runtime-binding.v1".to_vec();
    bytes.extend_from_slice(config.encoder_digest.as_array());
    bytes.extend_from_slice(config.head_digest.as_array());
    bytes.extend_from_slice(receipt.model_output_digest.as_array());
    bytes.extend_from_slice(runtime_receipt.semantic_digest()?.as_array());
    Ok(Digest32::of_bytes(&bytes))
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
        // This qualification fixture consumes the supplied feature vectors unchanged.
        normalizer_digest: Digest32::of_bytes(b"qualification-identity-feature-normalizer.v1")
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
    let cell_scope = CellScopeV1 {
        agent_id: subject.clone(),
        cell_id: StableId::new("qualification.memory.cell")?,
        run_id: StableId::new("qualification.memory.run")?,
        principal_digest: scope.scope_digest,
    };
    // Preserve the fixture worker lease's original 99 - 1 ms remaining budget
    // while the durable Cell control samples an actual monotonic clock.
    let deadline_budget_micros = (99_u64 - 1) * 1000;
    let definition = CellDefinitionV1 {
        cell_id: cell_scope.cell_id.clone(),
        bundle_digest: config.model_manifest_digest,
        state_schema_digest: native.digest()?,
        runtime: config.clone(),
        native,
        candidates: vec![CellCandidateV1 {
            candidate_id: StableId::new("qualification.memory.abstain")?,
            activation_index: 4,
            kind: CellCandidateKindV1::Abstain,
        }],
        max_input_bytes: config
            .input_feature_dimension
            .checked_mul(8)
            .ok_or("feature dimension overflow")?,
        max_queue_age_micros: deadline_budget_micros,
        max_resident_bytes: 1 << 20,
    };
    let partitions = vec![CellJournalPartitionV1 {
        scope: cell_scope.clone(),
        definition: definition.clone(),
        source_frontier: binding.scope_digest,
        writer_epoch: 1,
    }];
    let witness =
        FileAnchorWitnessStore::open(file(&output.join("witness"))?, scope, generation, 64)?;
    let mut owner = CellOwnerJournalV1::open(
        file(&output.join("journal"))?,
        witness,
        partitions.clone(),
        64,
    )?;
    let runtime = NeuronModelRuntimeTupleV1 {
        model_id: config.model_id.clone(),
        model_manifest_digest: config.model_manifest_digest,
        weights_digest: config.weights_digest,
        tokenizer_digest: config.tokenizer_digest,
        preprocessor_digest: config.preprocessor_digest,
        quantization_digest: config.quantization_digest,
        runtime_digest: config.runtime_digest,
        device_digest: config.device_digest,
    };
    let clock_origin = Instant::now();
    let clock: Arc<dyn Fn() -> u64 + Send + Sync> = Arc::new(move || {
        u64::try_from(clock_origin.elapsed().as_micros())
            .unwrap_or(u64::MAX)
            .saturating_add(1)
    });
    let mut control = ControlledNeuronFeaturePortV1::new(
        DurableInferenceControl::open(output.join("inference-control.log"), 64)?,
        definition.clone(),
        1,
        MemoryWorker {
            worker: Mutex::new(worker),
            runtime,
        },
        Arc::clone(&clock),
    )?;
    let encoder = QualificationEncoder {
        encoder_digest: binding.encoder_digest,
        dimension: config.input_feature_dimension,
    };
    let mut committed = Vec::new();
    let mut checkpoint = Digest32::ZERO;
    let mut observed = Vec::new();
    for (index, vector) in parity.vectors.iter().enumerate() {
        let sequence = index as u64 + 1;
        let started = clock();
        let input = CellStepInputV1 {
            operation_id: StableId::new(format!("memory.tick.{sequence}"))?,
            scope: cell_scope.clone(),
            source_frontier: binding.scope_digest,
            objective_digest: scope.objective_digest,
            ndu_snapshot_digest: Digest32::of_bytes(b"qualification-ndu"),
            monotonic_micros: started,
            deadline_micros: started
                .checked_add(deadline_budget_micros)
                .ok_or("deadline overflow")?,
            observation: vector
                .input_q24
                .iter()
                .flat_map(|value| value.to_be_bytes())
                .collect(),
            candidates: vec![CellCandidateMaskV1 {
                candidate_id: definition.candidates[0].candidate_id.clone(),
                allowed: true,
            }],
        };
        let prepared = prepare_cell_step(&definition, &owner, &encoder, input, clock())?;
        // The compatibility entry records admission and commit: two records
        // per vector, preserving the original 64-record journal/witness bound.
        // Its cost includes actual control-port queue time, not host fsync wait.
        let inferred = infer_cell(prepared, &mut owner, &mut control, clock())?;
        let proposal = decide_cell(inferred, clock())?;
        let result = commit_cell_step(&mut owner, proposal, clock())?;
        if result.checkpoint_before != checkpoint {
            return Err("checkpoint chain mismatch".into());
        }
        let prediction = *result
            .representation
            .prediction_q24
            .get(1)
            .ok_or("missing prediction")?;
        let error = prediction.abs_diff(vector.expected_probability_q24);
        if error > parity.maximum_absolute_q24_error as u64 {
            return Err("torch/native numerical parity failed".into());
        }
        checkpoint = result.checkpoint_after;
        let model_runtime_digest = committed_model_runtime_digest(&config, &result)?;
        observed.push(serde_json::json!({"sequence": sequence, "absolute_q24_error": error,
            "checkpoint": checkpoint.to_string(), "model_runtime_digest": model_runtime_digest.to_string()}));
        committed.push(result);
    }
    let acknowledged = owner.snapshot(&cell_scope)?;
    drop(owner);
    drop(control);
    let witness =
        FileAnchorWitnessStore::open(file(&output.join("witness"))?, scope, generation, 64)?;
    let anchor = witness.current()?.ok_or("missing committed anchor")?;
    let recovered =
        CellOwnerJournalV1::open(file(&output.join("journal"))?, witness, partitions, 64)?;
    if recovered.snapshot(&cell_scope)? != acknowledged {
        return Err("reopen lost acknowledged state".into());
    }
    for receipt in committed {
        if recovered.reconcile(&cell_scope, &receipt.operation_id, receipt.operation_digest)?
            != Some(receipt)
        {
            return Err("reopen lost acknowledged receipt".into());
        }
    }
    drop(recovered);
    let witness =
        FileAnchorWitnessStore::open(file(&output.join("witness"))?, scope, generation, 64)?;
    if witness.current()? != Some(anchor) {
        return Err("reopen lost acknowledged state".into());
    }
    fs::write(
        output.join("owner-report.json"),
        serde_json::to_vec_pretty(&serde_json::json!({
            "schema": "hepta.memory-cell.owner-execution.v1", "real_tensor_artifact": true,
            "execution_contract": "CellFeatureV1",
            "dispatch_authority": "durable-inference-control-token",
            "host_queue_accounting": "control-port-only",
            "observations": observed, "journal_reopened": true, "authority_profile": "qualification-fixture",
            "calibration_profile": "fixture-not-measured-product-calibration", "production_activated": false, "daemon_started": false
        }))?,
    )?;
    Ok(())
}

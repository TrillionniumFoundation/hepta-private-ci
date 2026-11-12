//! Frozen trained semantic-head arithmetic and durable native owner qualification.
//! Original FP64 feature rows are provided by the audited Python exporter.
//! This is not native screenshot encoding, daemon admission or source attestation.
//! Linux same-boot clock; separate local witness is not an independent trust domain.

#![recursion_limit = "256"]

use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::error::Error;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const Q: i64 = 1 << 24;
const LIMIT: i64 = 8 * Q;
const ABSTAIN_ID: &str = "qualification-abstain";

include!("perc1_semantic_native_model.rs");

struct ScopeInput {
    agent_id: String,
    cell_id: String,
    run_id: String,
    principal_digest: [u8; 32],
}
struct Expected {
    scope: ScopeInput,
    source_frontier: [u8; 32],
    encoder_digest: [u8; 32],
    feature_dimension: usize,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    boot_sha256: [u8; 32],
    monotonic_micros: u64,
    deadline_micros: u64,
    files: BTreeMap<String, [u8; 32]>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Observed {
    request_sha256: [u8; 32],
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
    logits_f64: Vec<f64>,
    logits_bits_u64: Vec<u64>,
    latency_micros: u64,
    memory_bytes: u64,
    transient_bytes: u64,
    receipt_sha256: [u8; 32],
}
// Decode the authoritative IEEE-754 bits, then verify the original decimal
// presentation bytes. This avoids a JSON parser's one-ULP float conversion
// changing a retained execution or weakening the owner-committed score hash.
fn retained_observed(root: &Path) -> Result<Observed> {
    let bytes = read(&root.join("head-receipt.json"), 65_536)?;
    if read(&root.join("head-receipt.sha256"), 32)? != Digest32::of_bytes(&bytes).into_array() {
        return Err("retained inference scores changed".into());
    }
    let mut value: Observed = serde_json::from_slice(&bytes)?;
    if value.logits_bits_u64.len() != 4 {
        return Err("invalid retained semantic scores".into());
    }
    value.logits_f64 = value
        .logits_bits_u64
        .iter()
        .map(|bits| f64::from_bits(*bits))
        .collect();
    if value.logits_f64.iter().any(|v| !v.is_finite()) {
        return Err("invalid retained semantic scores".into());
    }
    if serde_json::to_vec(&value)? != bytes {
        return Err("retained semantic output mismatch".into());
    }
    Ok(value)
}

enum Mode {
    Start,
    LoseAck,
    ReadOnly,
}
struct Encoder {
    observation: Vec<u8>,
    values: Vec<i64>,
    digest: Digest32,
    frontier: Digest32,
}
impl CellInputEncoderV1 for Encoder {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> std::result::Result<CellEncodedInputV1, CellExecutionError> {
        if request.encoder_digest != self.digest
            || request.source_frontier != self.frontier
            || request.observation != self.observation
        {
            return Err(CellExecutionError::Backend(NeuronModelError::Indeterminate));
        }
        Ok(CellEncodedInputV1 {
            encoder_digest: self.digest,
            feature_vector_q24: self.values.clone(),
            consumed_bytes: request.observation.len(),
            truncated_bytes: 0,
        })
    }
}
fn read(path: &Path, limit: usize) -> Result<Vec<u8>> {
    if !fs::symlink_metadata(path)?.file_type().is_file() {
        return Err("regular nonsymlink input required".into());
    }
    let mut bytes = Vec::new();
    File::open(path)?
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > limit {
        return Err("input byte bound exceeded".into());
    }
    Ok(bytes)
}

fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    File::open(path.parent().ok_or("missing parent")?)?.sync_all()?;
    Ok(())
}

fn clock() -> Result<u64> {
    let uptime = fs::read_to_string("/proc/uptime")?;
    let (seconds, fraction) = uptime
        .split_whitespace()
        .next()
        .ok_or("uptime")?
        .split_once('.')
        .ok_or("uptime decimal")?;
    if fraction.len() != 2 {
        return Err("unsupported uptime precision".into());
    }
    seconds
        .parse::<u64>()?
        .checked_mul(1_000_000)
        .and_then(|v| {
            fraction
                .parse::<u64>()
                .ok()?
                .checked_mul(10_000)?
                .checked_add(v)
        })
        .ok_or_else(|| "uptime overflow".into())
}

fn id(value: &str) -> Result<StableId> {
    Ok(StableId::new(value)?)
}
fn pin(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn definition(
    expected: &Expected,
    model: Digest32,
    boot: Digest32,
    width: usize,
    candidate_ids: &[String],
) -> Result<CellDefinitionV1> {
    let generation = Generation::new(1)?;
    let native = SparseConfig {
        model_digest: model,
        normalization_digest: pin("perc-semantic-qualification-normalizer-v1"),
        generation,
        width,
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
        config_id: id("perc-native-owner-qualification")?,
        generation,
        model_id: id("trained-fp64-tanh-ranking-head")?,
        model_manifest_digest: model,
        encoder_digest: Digest32::from_array(expected.encoder_digest),
        head_digest: model,
        weights_digest: model,
        tokenizer_digest: pin("no-tokenizer-q24"),
        preprocessor_digest: native.normalization_digest,
        quantization_digest: pin("FP64-tanh-logit-round-Q24-clamp8-rawSHA256-v1"),
        runtime_digest: pin("perc-native-fp64-tanh-original-rows-v1"),
        device_digest: boot,
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: expected.feature_dimension,
        state_width: width,
        modulator_dimension: 1,
        // Qualification fixture only. These calibration fields are not empirical measurements.
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: pin("semantic-qualification-not-scientific-calibration"),
            ood_artifact_digest: pin("semantic-qualification-not-scientific-ood"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 500_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 1000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 1000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 100_000,
            p99_latency_micros: 1_000_000,
            transient_allocation_bytes: 1_048_576,
            checkpoint_bytes: 65_536,
            write_amplification_ppm: 4_000_000,
        },
    };
    let mut candidates = Vec::with_capacity(5);
    for (activation_index, candidate_id) in candidate_ids.iter().enumerate() {
        candidates.push(CellCandidateV1 {
            candidate_id: id(candidate_id)?,
            activation_index,
            kind: CellCandidateKindV1::SlowPath,
        });
    }
    candidates.push(CellCandidateV1 {
        candidate_id: id(ABSTAIN_ID)?,
        activation_index: width - 1,
        kind: CellCandidateKindV1::Abstain,
    });
    Ok(CellDefinitionV1 {
        cell_id: id(&expected.scope.cell_id)?,
        bundle_digest: model,
        state_schema_digest: pin("perc-native-owner-qualification-v1"),
        runtime,
        native,
        candidates,
        max_input_bytes: 65_536,
        max_queue_age_micros: 1_000_000,
        max_resident_bytes: 1_048_576,
    })
}

// Qualification-only prediction channel: 32 unscaled bytes commit the four exact
// IEEE-754 little-endian raw logits. It is not a learned semantic prediction.
fn semantic_output(logits: &[f64]) -> Result<(Vec<i64>, Vec<i64>, Digest32)> {
    if logits.len() != 4 || logits.iter().any(|v| !v.is_finite()) {
        return Err("invalid retained semantic scores".into());
    }
    let raw: Vec<u8> = logits.iter().flat_map(|v| v.to_le_bytes()).collect();
    let digest = Digest32::of_bytes(&raw);
    let mut drive = vec![0; 32];
    for (target, value) in drive.iter_mut().zip(logits) {
        *target = (value * Q as f64)
            .clamp(-LIMIT as f64, LIMIT as f64)
            .round() as i64;
    }
    let prediction = digest.into_array().into_iter().map(i64::from).collect();
    Ok((drive, prediction, digest))
}

struct Control {
    root: PathBuf,
    head: Head,
    features: Features,
    transport: Vec<i64>,
    runtime: NeuronModelRuntimeTupleV1,
    encoder_digest: Digest32,
    head_digest: Digest32,
    executions: usize,
    reads: usize,
    lose_ack: bool,
}

impl Control {
    fn receipt(
        &self,
        request: &NeuronFeatureRequestV1,
        value: &Observed,
    ) -> Result<NeuronFeatureReceiptV1> {
        let (drive, prediction, _) = semantic_output(&value.logits_f64)?;
        if drive != value.drive_q24 || prediction != value.prediction_q24 {
            return Err("retained semantic output mismatch".into());
        }
        if neuron_feature_request_digest_v1(request)?.into_array() != value.request_sha256 {
            return Err("original inference request mismatch".into());
        }
        Ok(build_neuron_feature_receipt_v1(
            request,
            self.runtime.clone(),
            NeuronFeatureObservationV1 {
                encoder_digest: self.encoder_digest,
                head_digest: self.head_digest,
                drive_q24: value.drive_q24.clone(),
                prediction_q24: value.prediction_q24.clone(),
                observed_memory_bytes: value.memory_bytes,
                transient_allocation_bytes: value.transient_bytes,
                queue_age_micros: 0,
                latency_micros: value.latency_micros,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )?)
    }

    fn execute(&mut self, request: &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1> {
        if request.encoder_digest != self.encoder_digest
            || request.head_digest != self.head_digest
            || request.weights_digest != self.runtime.weights_digest
            || request.expected_output_width != 32
            || request.feature_vector_q24 != self.transport
        {
            return Err("head input binding mismatch".into());
        }
        let request_sha256 = neuron_feature_request_digest_v1(request)?.into_array();
        write(&self.root.join("head-claim.bin"), &request_sha256)?;
        self.executions += 1;
        let started = Instant::now();
        let logits_f64 = self.head.scores(&self.features.rows)?;
        let (drive_q24, prediction_q24, _) = semantic_output(&logits_f64)?;
        let transient_bytes = (drive_q24.capacity() + prediction_q24.capacity()) as u64 * 8;
        let latency_micros = u64::try_from(started.elapsed().as_micros())?;
        let mut value = Observed {
            request_sha256,
            logits_bits_u64: logits_f64.iter().map(|value| value.to_bits()).collect(),
            logits_f64,
            drive_q24,
            prediction_q24,
            latency_micros,
            memory_bytes: ((self
                .head
                .parameters
                .w1
                .iter()
                .map(Vec::capacity)
                .sum::<usize>()
                + self.head.parameters.b1.capacity()
                + self.head.parameters.w2.capacity())
                * 8) as u64,
            transient_bytes,
            receipt_sha256: [0; 32],
        };
        let receipt = self.receipt(request, &value)?;
        value.receipt_sha256 = receipt.receipt_digest.into_array();
        let bytes = serde_json::to_vec(&value)?;
        write(&self.root.join("head-receipt.json"), &bytes)?;
        write(
            &self.root.join("head-receipt.sha256"),
            &Digest32::of_bytes(&bytes).into_array(),
        )?;
        Ok(receipt)
    }
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let receipt = self
            .execute(request)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        if self.lose_ack {
            Err(NeuronModelError::Indeterminate)
        } else {
            Ok(receipt)
        }
    }
}

impl CellInferenceReadbackPortV1 for Control {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.reads += 1;
        let result = (|| -> Result<_> {
            let value = retained_observed(&self.root)?;
            let receipt = self.receipt(request, &value)?;
            if receipt.receipt_digest.into_array() != value.receipt_sha256
                || read(&self.root.join("head-claim.bin"), 32)? != value.request_sha256
            {
                return Err("retained inference receipt mismatch".into());
            }
            Ok(receipt)
        })();
        result
            .map(Some)
            .map_err(|_| NeuronModelError::Indeterminate)
    }
}

fn initialize(root: &Path, paths: &[std::ffi::OsString]) -> Result<()> {
    fs::create_dir(root)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
    }
    let mut files = BTreeMap::new();
    for ((name, limit), source) in [("features.json", 65_536), ("head.json", 1_048_576)]
        .into_iter()
        .zip(paths)
    {
        let raw = read(Path::new(source), limit)?;
        files.insert(name.to_string(), Digest32::of_bytes(&raw).into_array());
        write(&root.join(name), &raw)?;
    }
    let monotonic_micros = clock()?;
    let manifest = Manifest {
        schema: "perc1.semantic-native-owner-qualification.v1".into(),
        boot_sha256: Digest32::of_bytes(&read(Path::new("/proc/sys/kernel/random/boot_id"), 128)?)
            .into_array(),
        monotonic_micros,
        deadline_micros: monotonic_micros
            .checked_add(3_600_000_000)
            .ok_or("deadline overflow")?,
        files,
    };
    write(&root.join("manifest.json"), &serde_json::to_vec(&manifest)?)?;
    write(&root.join("cell.journal"), &[])?;
    write(&root.join("witness.journal"), &[])
}

fn run(root: &Path, output: &Path, mode: Mode) -> Result<()> {
    let manifest: Manifest = serde_json::from_slice(&read(&root.join("manifest.json"), 8192)?)?;
    if manifest.schema != "perc1.semantic-native-owner-qualification.v1"
        || manifest.boot_sha256
            != Digest32::of_bytes(&read(Path::new("/proc/sys/kernel/random/boot_id"), 128)?)
                .into_array()
        || manifest.monotonic_micros == 0
        || manifest.deadline_micros <= manifest.monotonic_micros
    {
        return Err("same-boot manifest binding mismatch".into());
    }
    let limits = [("features.json", 65_536), ("head.json", 1_048_576)];
    if manifest.files.len() != limits.len() {
        return Err("manifest inventory mismatch".into());
    }
    let mut retained = BTreeMap::new();
    for (name, limit) in limits {
        let bytes = read(&root.join(name), limit)?;
        if manifest.files.get(name) != Some(&Digest32::of_bytes(&bytes).into_array()) {
            return Err("retained source changed".into());
        }
        retained.insert(name, bytes);
    }
    let features: Features = serde_json::from_slice(&retained["features.json"])?;
    features.validate(&retained["head.json"])?;
    let head: Head = serde_json::from_slice(&retained["head.json"])?;
    head.validate(&features)?;
    let (transport, transport_scale, reconstruction_error) = features.transport();
    let expected = Expected {
        scope: ScopeInput {
            agent_id: "semantic-qualification".into(),
            cell_id: "trained-semantic-head".into(),
            run_id: "frozen-features-step".into(),
            principal_digest: pin("local-qualification-no-authority").into_array(),
        },
        source_frontier: hash(&features.source_manifest_sha256)?.into_array(),
        encoder_digest: pin("frozen-fp64-features-q24-transport-v1").into_array(),
        feature_dimension: transport.len(),
    };
    let width = 32;
    let scope = CellScopeV1 {
        agent_id: id(&expected.scope.agent_id)?,
        cell_id: id(&expected.scope.cell_id)?,
        run_id: id(&expected.scope.run_id)?,
        principal_digest: Digest32::from_array(expected.scope.principal_digest),
    };
    let definition = definition(
        &expected,
        Digest32::of_bytes(&retained["head.json"]),
        Digest32::from_array(manifest.boot_sha256),
        width,
        &features.candidate_ids,
    )?;
    let r = &definition.runtime;
    let mut control = Control {
        root: root.into(),
        head,
        features,
        transport: transport.clone(),
        runtime: NeuronModelRuntimeTupleV1 {
            model_id: r.model_id.clone(),
            model_manifest_digest: r.model_manifest_digest,
            weights_digest: r.weights_digest,
            tokenizer_digest: r.tokenizer_digest,
            preprocessor_digest: r.preprocessor_digest,
            quantization_digest: r.quantization_digest,
            runtime_digest: r.runtime_digest,
            device_digest: r.device_digest,
        },
        encoder_digest: r.encoder_digest,
        head_digest: r.head_digest,
        executions: 0,
        reads: 0,
        lose_ack: matches!(mode, Mode::LoseAck),
    };
    let frontier = Digest32::from_array(expected.source_frontier);
    let input = CellStepInputV1 {
        operation_id: id("perc-native-step-1")?,
        scope: scope.clone(),
        source_frontier: frontier,
        objective_digest: pin("local-perception-mechanism-qualification"),
        ndu_snapshot_digest: pin("no-learned-ctrl-claim"),
        monotonic_micros: manifest.monotonic_micros,
        deadline_micros: manifest.deadline_micros,
        observation: retained["features.json"].clone(),
        candidates: definition
            .candidates
            .iter()
            .map(|c| CellCandidateMaskV1 {
                candidate_id: c.candidate_id.clone(),
                allowed: true,
            })
            .collect(),
    };
    let witness = FileAnchorWitnessStore::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join("witness.journal"))?,
        JournalScope {
            scope_digest: scope.digest(),
            objective_digest: input.objective_digest,
        },
        definition.runtime.generation,
        /*max_records*/ 64,
    )?;
    let mut owner = CellOwnerJournalV1::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join("cell.journal"))?,
        witness,
        vec![CellJournalPartitionV1 {
            scope: scope.clone(),
            definition: definition.clone(),
            source_frontier: frontier,
            writer_epoch: 1,
        }],
        /*max_records*/ 64,
    )?;
    let request_digest = canonical_cell_step_request_digest_v1(&definition, &input)?;
    let committed = match owner.lookup(&scope, &input.operation_id, request_digest) {
        Ok(value) => value,
        Err(CellExecutionError::InferencePending) => None,
        Err(error) => return Err(error.into()),
    };
    if matches!(mode, Mode::ReadOnly)
        && committed.is_none()
        && owner.pending_inference(&scope)?.is_none()
    {
        return Err("read-only request has no original admission; no work dispatched".into());
    }
    let (receipt, status, encodings) = if let Some(value) = committed {
        (Some(value), "REPLAYED", 0)
    } else {
        let encoder = Encoder {
            observation: retained["features.json"].clone(),
            values: transport,
            digest: r.encoder_digest,
            frontier,
        };
        let inferred = if owner.pending_inference(&scope)?.is_some() {
            recover_cell_inference(&definition, &owner, &encoder, input, &mut control, clock()?)
        } else {
            let prepared = prepare_cell_step(&definition, &owner, &encoder, input, clock()?)?;
            infer_cell_with_clock(prepared, &mut owner, &mut control, || {
                clock().unwrap_or(u64::MAX)
            })
        };
        match inferred {
            Ok(value) => (
                Some(commit_cell_step(
                    &mut owner,
                    decide_cell(value, clock()?)?,
                    clock()?,
                )?),
                "COMMITTED",
                1,
            ),
            Err(CellExecutionError::Backend(NeuronModelError::Indeterminate)) => {
                (None, "PENDING_ORIGINAL_READBACK", 1)
            }
            Err(error) => return Err(error.into()),
        }
    };
    let snapshot = owner.snapshot(&scope)?;
    let observed = if root.join("head-receipt.json").exists() {
        Some(retained_observed(root)?)
    } else {
        None
    };
    if receipt.is_some() && observed.is_none() {
        return Err("original semantic score receipt unavailable".into());
    }
    let raw_logit_sha256 = if let Some(value) = &observed {
        let (drive, prediction, score_digest) = semantic_output(&value.logits_f64)?;
        if drive != value.drive_q24 || prediction != value.prediction_q24 {
            return Err("retained semantic output mismatch".into());
        }
        if read(&root.join("head-claim.bin"), 32)? != value.request_sha256 {
            return Err("retained inference receipt mismatch".into());
        }
        if let Some(committed) = &receipt {
            let runtime = &control.runtime;
            let runtime_receipt = LocalModelRuntimeReceiptV1 {
                model_id: runtime.model_id.clone(),
                model_manifest_digest: runtime.model_manifest_digest,
                weights_digest: runtime.weights_digest,
                tokenizer_digest: runtime.tokenizer_digest,
                preprocessor_digest: runtime.preprocessor_digest,
                quantization_id: StableId::new(format!(
                    "quantization:{}",
                    runtime.quantization_digest
                ))?,
                quantization_digest: runtime.quantization_digest,
                backend_id: StableId::new(format!("runtime:{}", runtime.runtime_digest))?,
                runtime_digest: runtime.runtime_digest,
                device_identity_digest: runtime.device_digest,
                latency_micros: value.latency_micros,
                resident_bytes: value.memory_bytes,
            };
            if canonical_model_output_digest_v1(&drive, &prediction, &runtime_receipt)?
                != committed.model_output_digest
            {
                return Err("committed semantic output mismatch".into());
            }
        }
        Some(score_digest.to_string())
    } else {
        None
    };
    let logits = observed.as_ref().map(|v| v.logits_f64.clone());
    let ranking = logits.as_ref().map(|values| {
        let mut indices: Vec<usize> = (0..4).collect();
        indices.sort_by(|a, b| {
            values[*b]
                .partial_cmp(&values[*a])
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    control.features.candidate_ids[*a].cmp(&control.features.candidate_ids[*b])
                })
        });
        indices
            .into_iter()
            .map(|i| control.features.candidate_ids[i].clone())
            .collect::<Vec<_>>()
    });
    let selected_candidate = receipt
        .as_ref()
        .map(|value| value.selected_candidate.to_string());
    let selected_source_candidate = selected_candidate
        .as_ref()
        .filter(|value| control.features.candidate_ids.contains(value))
        .cloned();
    let abstained = selected_candidate.as_deref() == Some(ABSTAIN_ID);
    let value = serde_json::json!({
        "schema": "perc1.semantic-native-owner-observation.v1", "status": status,
        "scientific_status": "HOLD", "authority_granted": false, "daemon_admission_exercised": false,
        "native_cell_owner_exercised": true, "trained_semantic_head_inference_executions": control.executions,
        "inference_readbacks": control.reads, "encoder_calls": encodings,
        "head_provenance": "supplied_semantic_head_with_declared_training_metadata", "trained_semantic_model_executed": control.executions>0,
        "logits_f64":logits,"ranking":ranking,
        "source_candidate_ids":&control.features.candidate_ids,
        "source_candidate_activation_indices":[0,1,2,3],
        "abstain_candidate_id":ABSTAIN_ID,"abstain_activation_index":31,
        "selected_source_candidate":selected_source_candidate,"abstained":abstained,
        "logits_bits_u64":observed.as_ref().map(|v|v.logits_bits_u64.clone()),
        "score_retention":"authoritative IEEE-754 bits with exact canonical original decimal presentation",
        "raw_logit_sha256":raw_logit_sha256,"owner_commits_exact_raw_logit_sha256":receipt.is_some() && observed.is_some(),
        "prediction_channel":"qualification-only 32 unscaled SHA256 bytes of four FP64 little-endian logits; not a learned prediction",
        "historical_head_membership_verified_by_native":false,
        "historical_membership_scope":"parent driver verifies frozen archive membership and training parameter lineage","semantic_inference_uses_original_fp64_rows":true,
        "quantization":{"transport_scale":transport_scale,"maximum_reconstruction_error":reconstruction_error,"clipped_features":0,
            "scope":"scaled Q24 ownership snapshot; semantic arithmetic uses original FP64 rows"},
        "source_manifest_sha256":control.features.source_manifest_sha256,
        "source_authority":"binding only; Python parent verifies source membership; no independent source attestation",
        "retained_score_reads":usize::from(observed.is_some()),
        "calibration": "hand-authored fixture; no empirical calibration or OOD qualification",
        "scope_digest": scope.digest().to_string(), "definition_digest": definition.semantic_digest()?.to_string(),
        "source_frontier": frontier.to_string(), "head_sha256": control.head_digest.to_string(),
        "features_sha256": Digest32::of_bytes(&retained["features.json"]).to_string(),
        "owner_revision": snapshot.revision, "pending": owner.pending_inference(&scope)?.is_some(),
        "decision": receipt.as_ref().map(|v| serde_json::json!({
            "operation_id": v.operation_id.to_string(), "operation_digest": v.operation_digest.to_string(),
            "request_digest": v.semantic_request_digest.to_string(), "scope_digest": v.scope.digest().to_string(),
            "bundle_digest": v.bundle_digest.to_string(), "source_frontier": v.source_frontier.to_string(),
            "checkpoint_before": v.checkpoint_before.to_string(), "checkpoint_after": v.checkpoint_after.to_string(),
            "model_output_digest": v.model_output_digest.to_string(), "selected_candidate": v.selected_candidate.to_string(),
            "policy": v.policy.iter().map(|p| serde_json::json!({"candidate_id":p.candidate_id.to_string(),"allowed":p.allowed,"probability_ppm":p.probability_ppm})).collect::<Vec<_>>(),
            "confidence_ppm": v.confidence_ppm, "ood_ppm": v.ood_ppm, "authority_granted": v.authority.grants_any(),
            "consumed_input_bytes": v.cost.consumed_input_bytes, "truncated_input_bytes": v.cost.truncated_input_bytes,
            "deadline_exceeded": v.deadline_exceeded, "model_latency_micros": v.cost.model_latency_micros,
            "queue_age_micros": v.cost.queue_age_micros, "resident_bytes": v.cost.resident_bytes,
            "transient_allocation_bytes": v.cost.transient_allocation_bytes, "checkpoint_bytes": v.cost.checkpoint_bytes,
        })),
        "clock": "Linux /proc/uptime centisecond resolution, same boot only",
        "cost_scope": "head Instant wall and owned parameter capacities; no CPU, RSS, energy or billing claim",
        "scope":"trained-head arithmetic and native owner only; no native screenshot encoder, production daemon or new-source benefit",
        "ranking_is_raw_mlp_not_sparse_cell_policy":true,
    });
    write(output, &serde_json::to_vec_pretty(&value)?)
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    match args.first().and_then(|v| v.to_str()) {
        Some(mode @ ("start" | "lose-ack")) if args.len() == 5 => {
            initialize(Path::new(&args[1]), &args[2..4])?;
            run(
                Path::new(&args[1]),
                Path::new(&args[4]),
                if mode == "lose-ack" {
                    Mode::LoseAck
                } else {
                    Mode::Start
                },
            )
        }
        Some("read") if args.len() == 3 => {
            run(Path::new(&args[1]), Path::new(&args[2]), Mode::ReadOnly)
        }
        _ => Err("usage: start|lose-ack ROOT FEATURES HEAD OUTPUT | read ROOT OUTPUT".into()),
    }
}

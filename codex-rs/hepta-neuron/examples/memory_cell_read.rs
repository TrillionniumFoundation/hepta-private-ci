//! Bounded qualification driver for actual parameter reads and native ownership.
//!
//! Usage: memory_cell_read ARTIFACT MANIFEST QUERIES STATE_DIR bootstrap|recover
//! Queries contain only {"queries_q12": [[...], ...]}. Accepted requests contain
//! no labels or training examples. Each row performs a diagnostic raw
//! parameter read and a real NeuronRuntime tick. The calibration profile is
//! deliberately outside the entire journal lifetime, so every native signal
//! abstains; the driver does not assert product admission or source authority.

use std::error::Error;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::MAX_MEMORY_CELL_ARTIFACT_BYTES;
use codex_hepta_neuron::MEMORY_CELL_Q12_PROFILE_V1;
use codex_hepta_neuron::MemoryCellArtifactV1;
use codex_hepta_neuron::MemoryCellModelPortV1;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::json;

const Q24: i64 = 1 << 24;
const MAX_RECORDS: usize = 1_024;
const SUBJECT: &str = "memory.qualification.subject";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Queries {
    queries_q12: Vec<Vec<i16>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    model_id: String,
    generation: u64,
    weights_sha256: String,
    encoder_sha256: String,
    preprocessor_sha256: String,
    source_set_sha256: String,
    input_dimension: usize,
    hidden_width: usize,
    output_bits: usize,
}

fn read_bounded(path: &Path, limit: usize) -> Result<Vec<u8>, Box<dyn Error>> {
    let file = File::open(path)?;
    if !file.metadata()?.is_file() || file.metadata()?.len() > limit as u64 {
        return Err("input file exceeds qualification bounds".into());
    }
    let mut bytes = Vec::new();
    file.take((limit + 1) as u64).read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err("input file grew beyond qualification bounds".into());
    }
    Ok(bytes)
}

fn state_file(path: &Path, bootstrap: bool) -> Result<File, Box<dyn Error>> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(bootstrap)
        .open(path)?)
}

fn run() -> Result<(), Box<dyn Error>> {
    let args = std::env::args_os().collect::<Vec<_>>();
    if args.len() != 6 {
        return Err(
            "usage: memory_cell_read ARTIFACT MANIFEST QUERIES STATE_DIR bootstrap|recover".into(),
        );
    }
    let bootstrap = match args[5].to_str() {
        Some("bootstrap") => true,
        Some("recover") => false,
        _ => return Err("mode must be bootstrap or recover".into()),
    };
    let bytes = read_bounded(Path::new(&args[1]), MAX_MEMORY_CELL_ARTIFACT_BYTES)?;
    let manifest_bytes = read_bounded(Path::new(&args[2]), /*limit*/ 32_768)?;
    let query_bytes = read_bounded(Path::new(&args[3]), /*limit*/ 8 << 20)?;
    let manifest: Manifest = serde_json::from_slice(&manifest_bytes)?;
    let queries: Queries = serde_json::from_slice(&query_bytes)?;
    if queries.queries_q12.is_empty() || queries.queries_q12.len() > MAX_RECORDS {
        return Err("query count outside qualification bounds".into());
    }
    let artifact = MemoryCellArtifactV1::from_bytes(&bytes)?;
    if manifest.schema != "hepta.memory.native-model.v1"
        || manifest.input_dimension != artifact.input_dimension()
        || manifest.hidden_width != artifact.hidden_width()
        || manifest.output_bits != artifact.output_bits()
        || manifest.weights_sha256.parse::<Digest32>()? != artifact.digest()
    {
        return Err("artifact differs from manifest".into());
    }
    for features in &queries.queries_q12 {
        if features.len() != artifact.input_dimension()
            || features
                .iter()
                .any(|value| !(-4_096..=4_096).contains(value))
        {
            return Err("query dimensions or Q12 values are invalid".into());
        }
    }
    let generation = Generation::new(manifest.generation)?;
    let encoder = manifest.encoder_sha256.parse::<Digest32>()?;
    let preprocessing = manifest.preprocessor_sha256.parse::<Digest32>()?;
    let source_set = manifest.source_set_sha256.parse::<Digest32>()?;
    let executable = read_bounded(&std::env::current_exe()?, /*limit*/ 256 << 20)?;
    let runtime_digest = Digest32::of_bytes(&executable);
    let device_profile = format!(
        "arch={};os={};parallelism={}",
        std::env::consts::ARCH,
        std::env::consts::OS,
        std::thread::available_parallelism()?.get()
    );
    let device_digest = Digest32::of_bytes(device_profile.as_bytes());
    let native = SparseConfig {
        model_digest: artifact.head_digest(),
        normalization_digest: preprocessing,
        generation,
        width: artifact.output_width(),
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: 0,
        threshold_rate_q24: 0,
        threshold_min_q24: 0,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    };
    let inactive_calibration =
        Digest32::of_bytes(b"qualification.inactive-calibration.no-serving-admission");
    let config = NeuronRuntimeConfigV1 {
        config_id: StableId::new("memory.qualification.config")?,
        generation,
        model_id: StableId::new(manifest.model_id)?,
        model_manifest_digest: Digest32::of_bytes(&manifest_bytes),
        encoder_digest: encoder,
        head_digest: artifact.head_digest(),
        weights_digest: artifact.digest(),
        tokenizer_digest: Digest32::of_bytes(b"memory.numeric.no-tokenizer.v1"),
        preprocessor_digest: preprocessing,
        quantization_digest: Digest32::of_bytes(MEMORY_CELL_Q12_PROFILE_V1),
        runtime_digest,
        device_digest,
        normalization_digest: preprocessing,
        native_config_digest: native.digest()?,
        input_feature_dimension: artifact.input_dimension(),
        state_width: native.width,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: inactive_calibration,
            ood_artifact_digest: inactive_calibration,
            generation,
            valid_from_sequence: 1_025,
            expires_after_sequence: 1_026,
            zero_confidence_error_q24: 16 * Q24,
            maximum_in_domain_error_q24: 16 * Q24,
            minimum_confidence_ppm: 1_000_000,
            maximum_ood_ppm: 0,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 256,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 0,
            measured_false_acceptance_ppm: 0,
            maximum_false_acceptance_ppm: 0,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 10_000_000,
            p99_latency_micros: 60_000_000,
            transient_allocation_bytes: 16 << 20,
            checkpoint_bytes: 16 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    let mut port = MemoryCellModelPortV1::from_bytes(&bytes, &manifest_bytes, &config)?;
    // Match the owner's canonical StableId encoding, rather than treating the
    // raw subject string as its already-domain-separated digest.
    let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    scope_bytes.extend_from_slice(&(SUBJECT.len() as u32).to_be_bytes());
    scope_bytes.extend_from_slice(SUBJECT.as_bytes());
    let objective = Digest32::of_bytes(b"memory.qualification.integer-parameter-read.v1");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&scope_bytes),
        objective_digest: objective,
    };
    let directory = Path::new(&args[4]);
    if bootstrap {
        fs::create_dir(directory)?;
    }
    // The host's selected tuple is immutable across recovery. Its durable
    // binding is separate from model-supplied claims; this local driver still
    // relies on the caller to authenticate the initial source selection.
    let selection = serde_json::to_vec(&json!({
        "schema":"hepta.memory.selected-host-binding.v1",
        "manifest_sha256":Digest32::of_bytes(&manifest_bytes).to_string(),
        "runtime_sha256":runtime_digest.to_string(), "device_sha256":device_digest.to_string(),
        "native_config_sha256":native.digest()?.to_string(),
        "quantization_sha256":Digest32::of_bytes(MEMORY_CELL_Q12_PROFILE_V1).to_string(),
    }))?;
    let selection_path = directory.join("selection.json");
    if bootstrap {
        let mut selection_file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&selection_path)?;
        selection_file.write_all(&selection)?;
        selection_file.sync_all()?;
    } else if read_bounded(&selection_path, /*limit*/ 32_768)? != selection {
        return Err("recovery tuple differs from the host's durable selection".into());
    }
    let witness = FileAnchorWitnessStore::open(
        state_file(&directory.join("witness.bin"), bootstrap)?,
        scope,
        generation,
        MAX_RECORDS,
    )?;
    let before = witness.current()?;
    let journal = state_file(&directory.join("journal.bin"), bootstrap)?;
    let mut owner = if bootstrap {
        NeuronRuntime::bootstrap(journal, native, scope, MAX_RECORDS, config, witness)?
    } else {
        let anchor = before.ok_or("recovery requires an independently acknowledged anchor")?;
        NeuronRuntime::recover(journal, native, scope, MAX_RECORDS, config, anchor, witness)?
    };
    let sequence_before = before.map_or(0, |anchor| anchor.sequence);
    if sequence_before + queries.queries_q12.len() as u64 > MAX_RECORDS as u64 {
        return Err("query batch would exceed journal capacity".into());
    }
    let mut checkpoint = before.map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest);
    let mut rows = Vec::with_capacity(queries.queries_q12.len());
    for (offset, features) in queries.queries_q12.iter().enumerate() {
        let raw = port.predict_q12(features)?;
        let sequence = sequence_before + offset as u64 + 1;
        let feature_vector_q24 = features
            .iter()
            .map(|value| i64::from(*value) * 4_096)
            .collect::<Vec<_>>();
        let input = NeuronTickInputV1 {
            tick_id: StableId::new(format!("memory.qualification.tick.{sequence}"))?,
            subject_id: StableId::new(SUBJECT)?,
            logical_sequence: sequence,
            monotonic_time_micros: sequence * 1_000,
            checkpoint_digest: checkpoint,
            input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
            feature_vector_q24,
            objective_digest: objective,
            ndu_snapshot_digest: source_set,
            body_generation: Some(generation.get()),
            modulator_digest: None,
        };
        let output = owner.tick(&mut port, input)?;
        checkpoint = output.tick.checkpoint_after;
        if !output.tick.abstain || output.signal.authority.grants_any() {
            return Err("qualification path unexpectedly produced an admitted signal".into());
        }
        rows.push(json!({
            "sequence":sequence, "raw_parameter_value":raw.value, "raw_logits_q24":raw.logits_q24,
            "checkpoint_before":output.tick.checkpoint_before.to_string(),
            "checkpoint_after":checkpoint.to_string(), "owner_abstain":output.tick.abstain,
            "authority_granted":output.signal.authority.grants_any(),
            "backend_id":output.model_runtime.backend_id.as_str(),
            "weights_sha256":output.model_runtime.weights_digest.to_string(),
            "model_latency_micros":output.model_runtime.latency_micros,
            "model_resident_tensor_and_struct_bytes":output.model_runtime.resident_bytes,
            "owner_execution_micros":output.tick.resource_receipt.execution_micros,
            "journal_bytes_written":output.tick.resource_receipt.journal_bytes_written,
            "checkpoint_bytes":output.tick.resource_receipt.checkpoint_bytes,
            "transient_array_bytes":output.tick.resource_receipt.transient_allocation_bytes,
        }));
    }
    let anchor = owner
        .current_anchor()?
        .ok_or("query batch did not commit")?;
    println!(
        "{}",
        json!({
            "schema":"hepta.memory.native-qualification.v1", "calibration_admitted":false,
            "mode":if bootstrap {"bootstrap"} else {"recover"}, "process_id":std::process::id(),
            "runtime_sha256":runtime_digest.to_string(), "device_profile":device_profile,
            "weights_sha256":artifact.digest().to_string(), "source_set_sha256":source_set.to_string(),
            "manifest_sha256":Digest32::of_bytes(&manifest_bytes).to_string(),
            "sequence_before":sequence_before, "sequence_after":anchor.sequence,
            "checkpoint_after":anchor.checkpoint_digest.to_string(), "diagnostic_parameter_reads":rows.len(),
            "native_owner_executions":rows.len(), "reads":rows,
        })
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("memory_cell_read rejected: {error}");
        std::process::exit(1);
    }
}

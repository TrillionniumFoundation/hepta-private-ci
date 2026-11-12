//! Trained FP64 acquisition MLP through the original native Cell owner/infer API.
//! Input features are extracted by the frozen Python recipe, not by this probe.
//! A local same-principal witness is not independent execution attestation.
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
// The builder substitutes these declarations with the exact sibling sources.
mod control;
mod definition;
mod model;
use control::Control;
use model::Encoder;
use model::Features;
use model::Head;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    boot_sha256: [u8; 32],
    monotonic_micros: u64,
    deadline_micros: u64,
    files: BTreeMap<String, [u8; 32]>,
}
enum Mode {
    Start,
    LoseAck,
    ReadOnly,
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
fn boot() -> Result<Digest32> {
    Ok(Digest32::of_bytes(&read(
        Path::new("/proc/sys/kernel/random/boot_id"),
        128,
    )?))
}

fn initialize(root: &Path, feature_path: &Path, head_path: &Path) -> Result<()> {
    let raw_features = read(feature_path, 65536)?;
    let raw_head = read(head_path, 2 * 1024 * 1024)?;
    let features: Features = serde_json::from_slice(&raw_features)?;
    let head: Head = serde_json::from_slice(&raw_head)?;
    features.validate(&head, &raw_head)?;
    fs::create_dir(root)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
    }
    let mut files = BTreeMap::new();
    for (name, bytes) in [("features.json", raw_features), ("head.json", raw_head)] {
        files.insert(name.to_string(), Digest32::of_bytes(&bytes).into_array());
        write(&root.join(name), &bytes)?;
    }
    let monotonic_micros = clock()?;
    let manifest = Manifest {
        schema: "perc1.trained-native-owner.v1".into(),
        boot_sha256: boot()?.into_array(),
        monotonic_micros,
        deadline_micros: monotonic_micros
            .checked_add(60_000_000)
            .ok_or("deadline overflow")?,
        files,
    };
    write(&root.join("manifest.json"), &serde_json::to_vec(&manifest)?)?;
    write(&root.join("cell.journal"), &[])?;
    write(&root.join("witness.journal"), &[])
}

fn run(root: &Path, output: &Path, mode: Mode) -> Result<()> {
    let manifest: Manifest = serde_json::from_slice(&read(&root.join("manifest.json"), 8192)?)?;
    if manifest.schema != "perc1.trained-native-owner.v1"
        || manifest.boot_sha256 != boot()?.into_array()
        || manifest.monotonic_micros == 0
        || manifest.deadline_micros <= manifest.monotonic_micros
        || manifest.files.len() != 2
    {
        return Err("same-boot manifest binding mismatch".into());
    }
    let mut retained = BTreeMap::new();
    for (name, limit) in [("features.json", 65536), ("head.json", 2 * 1024 * 1024)] {
        let bytes = read(&root.join(name), limit)?;
        if manifest.files.get(name) != Some(&Digest32::of_bytes(&bytes).into_array()) {
            return Err("retained source changed".into());
        }
        retained.insert(name, bytes);
    }
    let features: Features = serde_json::from_slice(&retained["features.json"])?;
    let head: Head = serde_json::from_slice(&retained["head.json"])?;
    let carrier = features.validate(&head, &retained["head.json"])?;
    let frontier = Digest32::of_bytes(&retained["features.json"]);
    let encoder_digest = pin(&format!(
        "{}:{}",
        model::CODEC,
        features.source_bindings["feature_extractor_sha256"]
    ));
    let scope = CellScopeV1 {
        agent_id: id("perc-trained-native-host")?,
        cell_id: id("acquisition-trained-cell")?,
        run_id: id(&format!("source:{frontier}"))?,
        principal_digest: pin("local-advisory-no-authority"),
    };
    let definition = definition::definition(
        &features,
        Digest32::of_bytes(&retained["head.json"]),
        Digest32::from_array(manifest.boot_sha256),
        carrier.len(),
        encoder_digest,
    )?;
    let r = &definition.runtime;
    let encoder = Encoder {
        scope: scope.clone(),
        frontier,
        digest: encoder_digest,
        values: carrier.clone(),
    };
    let input = CellStepInputV1 {
        operation_id: id("trained-acquisition-step-1")?,
        scope: scope.clone(),
        source_frontier: frontier,
        objective_digest: pin("trained-acquisition-native-numeric-durability-qualification"),
        ndu_snapshot_digest: pin("no-ctrl-or-parameter-v3-claim"),
        monotonic_micros: manifest.monotonic_micros,
        deadline_micros: manifest.deadline_micros,
        observation: retained["features.json"].clone(),
        candidates: definition
            .candidates
            .iter()
            .enumerate()
            .map(|(i, candidate)| CellCandidateMaskV1 {
                candidate_id: candidate.candidate_id.clone(),
                allowed: i == features.rows.len()
                    || features.upper_costs[i] <= features.remaining_budget,
            })
            .collect(),
    };
    let mut control = Control {
        root: root.into(),
        head,
        features,
        carrier,
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
        encoder_digest,
        head_digest: r.head_digest,
        retained_bytes: retained.values().map(|b| b.len() as u64).sum(),
        executions: 0,
        reads: 0,
        lose_ack: matches!(mode, Mode::LoseAck),
    };
    // Validate original output before opening the owner on a cold read.
    if matches!(mode, Mode::ReadOnly) {
        control.observed()?;
    }
    for name in ["cell.journal", "witness.journal"] {
        if !fs::symlink_metadata(root.join(name))?.file_type().is_file() {
            return Err("regular owner journal required".into());
        }
    }
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
    let observed = control.observed()?;
    if let Some(value) = &receipt {
        control.verify_committed(&observed, value)?;
    }
    let (_, _, predictions) = control.features.vectors(&control.head, &observed.raw())?;
    let mut native_choice = "abstain";
    let mut best = control.head.threshold;
    for (i, prediction) in predictions.iter().enumerate() {
        if control.features.upper_costs[i] <= control.features.remaining_budget
            && prediction[2] > best
        {
            native_choice = &control.features.candidate_ids[i];
            best = prediction[2];
        }
    }
    let snapshot = owner.snapshot(&scope)?;
    let value = serde_json::json!({
        "schema":"perc1.trained-native-owner-observation.v1", "status":status, "scientific_status":"HOLD",
        "authority_granted":false, "production_daemon_integrated":false, "parameter_v3_exercised":false,
        "native_cell_owner_exercised":true, "trained_head_inference_executions":control.executions,
        "inference_readbacks":control.reads, "encoder_calls":encodings, "native_feature_codec":model::CODEC,
        "output_adapter":model::OUTPUT_ADAPTER, "drive_semantics":"bounded FP64 policy ordinals; not quantized logits",
        "calibration":"hand-authored permissive qualification gate; no empirical OOD qualification",
        "scope_digest":scope.digest().to_string(), "definition_digest":definition.semantic_digest()?.to_string(),
        "source_frontier":frontier.to_string(), "head_sha256":control.head_digest.to_string(),
        "head_canonical_sha256":control.features.head_canonical_sha256, "source_bindings":control.features.source_bindings,
        "feature_rows_sha256":control.features.feature_rows_sha256, "carrier_digest":control.features.carrier_digest,
        "carrier_q24":control.carrier, "raw_outputs_f64":observed.raw(), "raw_bits_u64":observed.raw_bits_u64,
        "gain_cost_net":predictions, "native_fp64_selected_candidate":native_choice,
        "cell_selection_matches_native_fp64":receipt.as_ref().map(|v| v.selected_candidate.as_str() == native_choice),
        "owner_revision":snapshot.revision, "pending":owner.pending_inference(&scope)?.is_some(),
        "drive_q24":observed.drive_q24, "prediction_q24":observed.prediction_q24,
        "prediction_channel":"SHA256 commitment of raw FP64 output bits, not a residual prediction",
        "decision":receipt.as_ref().map(|v| serde_json::json!({
            "operation_id":v.operation_id.to_string(), "request_digest":v.semantic_request_digest.to_string(),
            "model_output_digest":v.model_output_digest.to_string(), "selected_candidate":v.selected_candidate.to_string(),
            "checkpoint_before":v.checkpoint_before.to_string(), "checkpoint_after":v.checkpoint_after.to_string(),
            "policy":v.policy.iter().map(|p| serde_json::json!({"candidate_id":p.candidate_id.to_string(), "allowed":p.allowed,"probability_ppm":p.probability_ppm})).collect::<Vec<_>>(),
            "authority_granted":v.authority.grants_any(), "deadline_exceeded":v.deadline_exceeded,
            "model_latency_micros":v.cost.model_latency_micros,"queue_age_micros":v.cost.queue_age_micros,
            "resident_bytes":v.cost.resident_bytes,"transient_allocation_bytes":v.cost.transient_allocation_bytes,
            "checkpoint_bytes":v.cost.checkpoint_bytes,"consumed_input_bytes":v.cost.consumed_input_bytes,"truncated_input_bytes":v.cost.truncated_input_bytes,
        })),
        "clock":"Linux /proc/uptime centisecond resolution; same boot only",
        "cost_scope":"MLP Instant wall; retained+parameter byte count and bounded scratch estimate, not RSS/CPU/energy/billing",
        "source_scope":"fixed externally extracted public features; hashes bind retained source provenance, not source independence",
    });
    write(output, &serde_json::to_vec_pretty(&value)?)
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    match args.first().and_then(|v| v.to_str()) {
        Some(mode @ ("start" | "lose-ack")) if args.len() == 5 => {
            initialize(
                Path::new(&args[1]),
                Path::new(&args[2]),
                Path::new(&args[3]),
            )?;
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

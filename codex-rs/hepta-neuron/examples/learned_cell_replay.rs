//! Bounded, source-pinned replay of 27 recorded Heads. No reference logits input.

use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::io::Read;
use std::path::Component;
use std::path::Path;
use std::time::Instant;

use codex_hepta_neuron::LearnedCellCalibration770V1;
use codex_hepta_neuron::LearnedCellExecutionMode770V1;
use codex_hepta_neuron::LearnedCellHead770V1;
use codex_hepta_neuron::LearnedFeaturePins770V1;
use codex_hepta_neuron::LearnedHeadPins770V1;
use codex_hepta_neuron::SharedLearnedFeatures770V1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FeatureInput {
    path: String,
    artifact_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HeadInput {
    id: String,
    path: String,
    artifact_digest: String,
    predictor_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReplayRequest {
    schema: String,
    feature_identity: String,
    generation: u64,
    task_digest: String,
    features: FeatureInput,
    heads: Vec<HeadInput>,
}

fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>, Box<dyn Error>> {
    for ancestor in path.ancestors().filter(|p| !p.as_os_str().is_empty()) {
        if fs::symlink_metadata(ancestor)?.file_type().is_symlink() {
            return Err("symlink input is not accepted".into());
        }
    }
    let initial = fs::symlink_metadata(path)?;
    if !initial.is_file() || initial.len() > maximum as u64 {
        return Err("ordinary bounded input file required before open".into());
    }
    let file = fs::File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > maximum as u64 {
        return Err("ordinary bounded input file required".into());
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    file.take(maximum as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err("input grew beyond byte limit".into());
    }
    Ok(bytes)
}

fn leaf(name: &str) -> Result<&Path, Box<dyn Error>> {
    let path = Path::new(name);
    if name.len() > 100 || path.components().count() != 1
        || !matches!(path.components().next(), Some(Component::Normal(_)))
        || name.contains('\\')
    {
        return Err("ordinary relative leaf required".into());
    }
    Ok(path)
}

fn main() -> Result<(), Box<dyn Error>> {
    let began = Instant::now();
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: learned_cell_replay REQUEST_JSON EXPECTED_REQUEST_SHA256".into());
    }
    let request_path = Path::new(&args[1]);
    let expected: Digest32 = args[2].to_str().ok_or("SHA256 must be UTF-8")?.parse()?;
    let bytes = read_bounded(request_path, /*maximum*/ 65_536)?;
    if expected.is_zero() || Digest32::of_bytes(&bytes) != expected {
        return Err("request artifact pin mismatch".into());
    }
    let request: ReplayRequest = serde_json::from_slice(&bytes)?;
    if request.schema != "hepta.native-learned-replay-request.v1" || request.heads.len() != 27 {
        return Err("fixed replay schema and 27 Heads required".into());
    }
    let feature_identity = request.feature_identity.parse()?;
    let generation = Generation::new(request.generation)?;
    let task_digest = request.task_digest.parse()?;
    if task_digest != Digest32::of_bytes(b"action_usefulness") {
        return Err("fixed task required".into());
    }
    let mut ids = BTreeSet::new();
    let mut paths = BTreeSet::from([request.features.path.as_str()]);
    for head in &request.heads {
        if head.id.is_empty() || head.id.len() > 64
            || !head.id.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
            || !ids.insert(head.id.as_str()) || !paths.insert(head.path.as_str())
        {
            return Err("bounded distinct Head IDs and paths required".into());
        }
        leaf(&head.path)?;
    }
    let directory = request_path.parent().ok_or("request parent required")?;
    let load_started = Instant::now();
    let batch = SharedLearnedFeatures770V1::import(
        &read_bounded(&directory.join(leaf(&request.features.path)?), /*maximum*/ 400_000)?,
        &LearnedFeaturePins770V1 {
            artifact_digest: request.features.artifact_digest.parse()?,
            feature_identity_digest: feature_identity,
            generation,
        },
    )?;
    if batch.rows() != 64 { return Err("fixed 64-row batch required".into()); }
    let feature_import_ns = load_started.elapsed().as_nanos();
    let mut results = Vec::with_capacity(request.heads.len());
    let mut parameter_bytes = 0;
    let mut peak_head_bytes = 0;
    for input in request.heads {
        let head_started = Instant::now();
        let head = LearnedCellHead770V1::import(
            &read_bounded(&directory.join(leaf(&input.path)?), /*maximum*/ 80_000)?,
            &LearnedHeadPins770V1 {
                artifact_digest: input.artifact_digest.parse()?,
                feature_identity_digest: feature_identity,
                generation,
                task_digest,
                predictor_digest: input.predictor_digest.parse()?,
            },
        )?;
        let head_import_ns = head_started.elapsed().as_nanos();
        let eval_started = Instant::now();
        let output = head.evaluate(&batch)?;
        let evaluate_ns = eval_started.elapsed().as_nanos();
        if output.calibration != LearnedCellCalibration770V1::Unavailable
            || output.mode != LearnedCellExecutionMode770V1::ShadowOnly
            || output.quality_qualified || output.authority != AuthorityPosture::DENY_ALL
        { return Err("raw shadow output posture changed".into()); }
        let argmax: Vec<_> = output.raw_logits.iter().map(|row| usize::from(row[1] > row[0])).collect();
        parameter_bytes += head.tensor_bytes();
        peak_head_bytes = peak_head_bytes.max(head.tensor_bytes());
        results.push(json!({"id": input.id, "mode": head.mode().name(),
            "predictor_digest": output.predictor_digest.to_string(),
            "feature_identity": output.feature_identity_digest.to_string(),
            "feature_batch_digest": output.feature_batch_digest.to_string(),
            "task_digest": output.task_digest.to_string(), "generation": output.generation.get(),
            "raw_logits": output.raw_logits, "argmax": argmax,
            "parameter_bytes": head.tensor_bytes(), "import_ns": head_import_ns,
            "evaluate_ns": evaluate_ns}));
    }
    println!("{}", json!({"schema": "hepta.native-learned-replay.v1",
        "request_sha256": expected.to_string(), "heads": results,
        "rows": batch.rows(), "feature_imports": 1, "feature_import_ns": feature_import_ns,
        "feature_tensor_bytes": batch.tensor_bytes(),
        "ordered_source_record_digests": batch.source_record_digests().iter().map(ToString::to_string).collect::<Vec<_>>(),
        "total_parameter_bytes_read": parameter_bytes, "peak_owned_head_parameter_bytes": peak_head_bytes,
        "wall_ns_before_serialization": began.elapsed().as_nanos(),
        "encoder_calls": 0, "parameter_updates": 0, "calibration": null,
        "execution_mode": "SHADOW_ONLY", "quality_qualified": false, "authority": "DENY_ALL"}));
    Ok(())
}

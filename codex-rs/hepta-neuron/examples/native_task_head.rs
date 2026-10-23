//! Bounded JSONL driver for the actual native research task Head.
//! Each process loads one immutable artifact once. It has no policy/effect API.

use std::error::Error;
use std::fs::File;
use std::io;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_neuron::LoadedTaskHeadV1;
use codex_hepta_neuron::TaskFeatureIdentityV1;
use codex_hepta_neuron::TaskHeadError;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::json;

const MAX_REQUEST_BYTES: u64 = 256 * 1024;
const MAX_ROWS: usize = 8192;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    identity: TaskFeatureIdentityV1,
    features: Vec<f32>,
    present_mask: u8,
    source_record_digest: String,
}

fn read_bounded(path: &Path, limit: u64) -> io::Result<Vec<u8>> {
    let file = File::open(path)?;
    if !file.metadata()?.is_file() {
        return Err(io::Error::other("regular artifact file required"));
    }
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(io::Error::other("artifact file byte limit"));
    }
    Ok(bytes)
}

fn run() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().collect();
    let [_, manifest_path, weights_path, expected_digest] = arguments.as_slice() else {
        return Err("usage: native_task_head MANIFEST WEIGHTS EXPECTED_MANIFEST_SHA256".into());
    };
    let expected_digest: Digest32 = expected_digest.parse()?;
    let manifest = read_bounded(Path::new(manifest_path), /*limit*/ 65536)?;
    let weights = read_bounded(Path::new(weights_path), /*limit*/ 1024 * 1024)?;
    let head = LoadedTaskHeadV1::from_artifact(&manifest, &weights, expected_digest)?;
    drop(weights);
    drop(manifest);
    let input = io::stdin();
    let mut input = input.lock();
    let output = io::stdout();
    let mut output = output.lock();
    let mut row_index = 0;
    loop {
        let mut line = Vec::new();
        let read = input
            .by_ref()
            .take(MAX_REQUEST_BYTES + 1)
            .read_until(b'\n', &mut line)?;
        if read == 0 {
            break;
        }
        if read as u64 > MAX_REQUEST_BYTES || row_index >= MAX_ROWS || !line.ends_with(b"\n") {
            return Err("bounded newline-terminated request required".into());
        }
        let request: Request = serde_json::from_slice(&line)?;
        let source: Digest32 = request.source_record_digest.parse()?;
        if source.is_zero() {
            return Err("source record digest required".into());
        }
        let result = head.predict(&request.features, &request.identity, request.present_mask);
        let (status, prediction) = match result {
            Ok(prediction) => ("SCORED_RESEARCH_ONLY", Some(prediction)),
            Err(TaskHeadError::MissingRequiredModality) => {
                ("REJECTED_MISSING_REQUIRED_MODALITY", None)
            }
            Err(error) => return Err(error.into()),
        };
        let response = json!({
            "row_index": row_index,
            "request_sha256": Digest32::of_bytes(&line).to_string(),
            "source_record_digest": source.to_string(),
            "artifact_sha256": expected_digest.to_string(),
            "status": status,
            "prediction": prediction,
            "task_admission_allowed": false,
            "action_execution_allowed": false,
        });
        serde_json::to_writer(&mut output, &response)?;
        output.write_all(b"\n")?;
        output.flush()?;
        row_index += 1;
    }
    if row_index == 0 {
        return Err("at least one request required".into());
    }
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    run()
}

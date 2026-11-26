//! Original fixed scorer execution, retained before every external invocation.
//! Only the custody provider calls this after its held-CAS consumption check.
use crate::fixed_holdout_custody::create_private;
use crate::fixed_holdout_custody::private_directory;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use std::fs::File;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

const MAX_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Model {
    pub manifest: Source,
    pub weights: Source,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Observation {
    schema: String,
    pub request_id: String,
    pub input_line_digest: String,
    model_manifest_digest: String,
    input_digest: String,
    pub executed_at_ms: u64,
    terminal_observed: bool,
    succeeded: bool,
    runtime_digest: String,
    weights_digest: String,
    encoder_digest: String,
    head_digest: String,
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
    pub latency_micros: u64,
    resident_bytes: u64,
    transient_allocation_bytes: u64,
    qualified: bool,
    authority_grants_any: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    request_id: String,
    feature_vector_q24: Vec<i64>,
    expected_output_width: usize,
}

impl Model {
    pub fn verify(&self) -> HostResult<serde_json::Value> {
        let value: serde_json::Value = serde_json::from_slice(&self.manifest.read(16 * 1024)?)?;
        self.weights.read(8 * 1024 * 1024)?;
        if value["weights_digest"] != self.weights.digest {
            return Err("actual model weights differ from original manifest".into());
        }
        let filename = value["weights_filename"]
            .as_str()
            .ok_or("original weights filename")?;
        let filename = Path::new(filename);
        if filename.components().count() != 1
            || !matches!(
                filename.components().next(),
                Some(std::path::Component::Normal(_))
            )
            || self
                .manifest
                .path
                .parent()
                .ok_or("original manifest parent")?
                .join(filename)
                != self.weights.path
        {
            return Err("pinned weights are not the file the original scorer loads".into());
        }
        for field in ["runtime_digest", "encoder_digest", "head_digest"] {
            if value[field]
                .as_str()
                .ok_or("model tuple")?
                .parse::<Digest32>()?
                .is_zero()
            {
                return Err("empty original numeric model tuple".into());
            }
        }
        Ok(value)
    }
}

pub(super) struct Execution {
    pub rows: Vec<(Vec<u8>, Observation)>,
    pub started_ms: u64,
}

/// An existing intent is never dispatched again, even if no status survived.
/// Only an already FULL completed output may be read on recovery.
pub(super) fn execute(
    scorer: &Source,
    model: &Model,
    inputs: &[Vec<u8>],
    directory: &Path,
    deadline: Instant,
) -> HostResult<Execution> {
    private_directory(directory)?;
    let scorer_bytes = scorer.read(128 * 1024 * 1024)?;
    let manifest = model.verify()?;
    let input_bytes = inputs.concat();
    if inputs.is_empty() || inputs.len() > 2048 || input_bytes.len() as u64 > MAX_BYTES {
        return Err("bounded original paired numeric batch".into());
    }
    let intent = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.fixed-paired-numeric-intent.v1", "scorer_digest":scorer.digest,
        "manifest_digest":model.manifest.digest,"weights_digest":model.weights.digest,
        "inputs_digest":Digest32::of_bytes(&input_bytes).to_string(),"rows":inputs.len()
    }))?;
    let intent_path = directory.join("intent.json");
    let status_path = directory.join("status.json");
    let output_path = directory.join("observations.jsonl");
    if intent_path.exists() {
        if read_root_review_input(&intent_path, 4096)? != intent {
            return Err("original numeric intent conflicts".into());
        }
        let status: serde_json::Value =
            serde_json::from_slice(&read_root_review_input(&status_path, 4096)?)?;
        let bytes = read_root_review_input(&output_path, MAX_BYTES)?;
        if status["schema"] != "hepta.fixed-paired-numeric-completed.v1"
            || status["intent_digest"] != Digest32::of_bytes(&intent).to_string()
            || status["output_digest"] != Digest32::of_bytes(&bytes).to_string()
        {
            return Err("original numeric completion is unknown; no new effect".into());
        }
        return parse(&bytes, inputs, model, &manifest, &status);
    }
    if status_path.exists() || output_path.exists() || Instant::now() >= deadline {
        return Err("numeric operation exists or its absolute budget expired".into());
    }
    // Durable intent precedes spawn. A failed spawn remains the original intent.
    create_private(&intent_path, &intent)?;
    let input_path = directory.join("inputs.jsonl");
    let input = create_private(&input_path, &input_bytes)?;
    // Newly created input's shared cursor is at EOF; reopen its verified path.
    drop(input);
    let output = create_private(&output_path, &[])?;
    let stderr = create_private(&directory.join("stderr.log"), &[])?;
    let started_ms = crate::fixed_calibration_host::now_ms()?;
    let started = Instant::now();
    if started >= deadline {
        return Err("original numeric budget expired before spawn".into());
    }
    let mut child = JoinedChild(
        Command::new(&scorer.path)
            .env_clear()
            .arg(&model.manifest.path)
            .arg(&model.manifest.digest)
            .stdin(Stdio::from(File::open(&input_path)?))
            .stdout(Stdio::from(output))
            .stderr(Stdio::from(stderr))
            .spawn()?,
    );
    let success = loop {
        if let Some(status) = child.0.try_wait()? {
            break status.success();
        }
        if Instant::now() >= deadline {
            // This is our fixed numeric child, not an unrelated Rust compiler.
            // No slot/receipt escapes until physical process join has completed.
            let _ = child.0.kill();
            child.0.wait()?;
            return Err("original numeric operation timed out; retained Unknown".into());
        }
        std::thread::sleep(Duration::from_millis(2));
    };
    let elapsed_micros = u64::try_from(started.elapsed().as_micros())?;
    let finished_ms = crate::fixed_calibration_host::now_ms()?;
    if !success || finished_ms < started_ms || scorer.read(128 * 1024 * 1024)? != scorer_bytes {
        return Err("original numeric execution failed or immutable program changed".into());
    }
    model.verify()?;
    File::open(&output_path)?.sync_all()?;
    File::open(directory)?.sync_all()?;
    let bytes = read_root_review_input(&output_path, MAX_BYTES)?;
    let status = serde_json::json!({"schema":"hepta.fixed-paired-numeric-completed.v1",
        "intent_digest":Digest32::of_bytes(&intent).to_string(),
        "output_digest":Digest32::of_bytes(&bytes).to_string(),
        "started_ms":started_ms,"finished_ms":finished_ms,"elapsed_micros":elapsed_micros});
    let result = parse(&bytes, inputs, model, &manifest, &status)?;
    create_private(&status_path, &serde_json::to_vec(&status)?)?;
    Ok(result)
}

struct JoinedChild(std::process::Child);
impl Drop for JoinedChild {
    fn drop(&mut self) {
        // Covers I/O errors in try_wait too; std Child alone has no join on drop.
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

fn parse(
    bytes: &[u8],
    inputs: &[Vec<u8>],
    model: &Model,
    manifest: &serde_json::Value,
    status: &serde_json::Value,
) -> HostResult<Execution> {
    let started_ms = status["started_ms"].as_u64().ok_or("actual start")?;
    let finished_ms = status["finished_ms"].as_u64().ok_or("actual finish")?;
    let elapsed_micros = status["elapsed_micros"]
        .as_u64()
        .ok_or("actual monotonic cost")?;
    if finished_ms < started_ms || elapsed_micros == 0 || !bytes.ends_with(b"\n") {
        return Err("original numeric execution clock or complete frame".into());
    }
    let lines = bytes
        .split_inclusive(|byte| *byte == b'\n')
        .collect::<Vec<_>>();
    if lines.len() != inputs.len() {
        return Err("all original numeric tasks must retain one actual observation".into());
    }
    let mut rows = Vec::new();
    for (line, original) in lines.into_iter().zip(inputs) {
        if line.len() > 16 * 1024 || !original.ends_with(b"\n") || original.len() > 16 * 1024 {
            return Err("bounded complete original numeric line".into());
        }
        let input: Input = serde_json::from_slice(original)?;
        let value: Observation = serde_json::from_slice(line)?;
        let feature_bytes = input
            .feature_vector_q24
            .iter()
            .flat_map(|v| v.to_be_bytes())
            .collect::<Vec<_>>();
        if value.schema != "hepta.cpu-neuron.offline-observation.v1"
            || input.request_id.is_empty()
            || input.request_id.len() > 128
            || input.feature_vector_q24.len() != 512
            || input.expected_output_width != 10
            || value.request_id != input.request_id
            || value.input_line_digest != Digest32::of_bytes(original).to_string()
            || value.input_digest != Digest32::of_bytes(&feature_bytes).to_string()
            || value.model_manifest_digest != model.manifest.digest
            || value.weights_digest != model.weights.digest
            || value.runtime_digest != manifest["runtime_digest"]
            || value.encoder_digest != manifest["encoder_digest"]
            || value.head_digest != manifest["head_digest"]
            || !value.terminal_observed
            || !value.succeeded
            || value.qualified
            || value.authority_grants_any
            || value.executed_at_ms < started_ms
            || value.executed_at_ms > finished_ms
            || value.drive_q24.len() != 10
            || value.prediction_q24.len() != 10
            || value.resident_bytes == 0
            || value.transient_allocation_bytes > 512 * 1024 * 1024
            || value.latency_micros > elapsed_micros
        {
            return Err(
                "actual numeric observation identity, model, budget or authority mismatch".into(),
            );
        }
        rows.push((line.to_vec(), value));
    }
    Ok(Execution { rows, started_ms })
}

impl Observation {
    pub fn class(&self) -> usize {
        let mut selected = 0;
        for index in 1..self.drive_q24.len() {
            if self.drive_q24[index] > self.drive_q24[selected] {
                selected = index;
            }
        }
        selected
    }
}

#[cfg(test)]
#[path = "paired_custody_numeric_tests.rs"]
mod tests;

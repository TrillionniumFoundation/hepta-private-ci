//! Match original calibration labels to complete frozen numeric executions.
//! Unjudged pairs are excluded, and no public development holdout is read.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::files::Access;
use super::files::ReviewResult;
use super::files::read_root;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NativeObservation {
    schema: String,
    pub(super) request_id: String,
    input_line_digest: String,
    model_manifest_digest: String,
    pub(super) input_digest: String,
    pub(super) executed_at_ms: u64,
    terminal_observed: bool,
    succeeded: bool,
    runtime_digest: String,
    weights_digest: String,
    encoder_digest: String,
    head_digest: String,
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
    latency_micros: u64,
    resident_bytes: u64,
    transient_allocation_bytes: u64,
    qualified: bool,
    authority_grants_any: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeInput {
    request_id: String,
    feature_vector_q24: Vec<i64>,
    expected_output_width: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceMapping {
    request_id: String,
    claim_id: u64,
    doc_id: u64,
    source_record_sha256: String,
}

pub(super) struct CalibrationExecution {
    pub(super) candidate: NativeObservation,
    pub(super) baseline: NativeObservation,
    pub(super) candidate_class: usize,
    pub(super) baseline_class: usize,
    pub(super) gold_class: usize,
    pub(super) source_digest: Digest32,
    pub(super) candidate_support: Digest32,
    pub(super) baseline_support: Digest32,
}

#[derive(Eq, PartialEq)]
pub(super) struct PinnedModel {
    pub(super) manifest: Digest32,
    pub(super) weights: Digest32,
    runtime: Digest32,
    encoder: Digest32,
    head: Digest32,
}

impl PinnedModel {
    pub(super) fn open(manifest: &Path, weights: &Path) -> ReviewResult<Self> {
        let bytes = read_root(manifest, 16 * 1024, Access::Immutable)?;
        let json: serde_json::Value = serde_json::from_slice(&bytes)?;
        let declared_weights: Digest32 = json["weights_digest"]
            .as_str()
            .ok_or("manifest weights missing")?
            .parse()?;
        let actual_weights =
            Digest32::of_bytes(&read_root(weights, 8 * 1024 * 1024, Access::Immutable)?);
        if declared_weights != actual_weights {
            return Err("immutable candidate weights do not match the manifest".into());
        }
        Ok(Self {
            manifest: Digest32::of_bytes(&bytes),
            weights: actual_weights,
            runtime: json["runtime_digest"]
                .as_str()
                .ok_or("runtime missing")?
                .parse()?,
            encoder: json["encoder_digest"]
                .as_str()
                .ok_or("encoder missing")?
                .parse()?,
            head: json["head_digest"]
                .as_str()
                .ok_or("head missing")?
                .parse()?,
        })
    }
}

pub(super) struct ModelExecutionFile<'a> {
    pub(super) model: &'a PinnedModel,
    pub(super) path: &'a Path,
}

pub(super) fn load_calibration(
    source: &Path,
    mapping: &Path,
    inputs: &Path,
    candidate_file: ModelExecutionFile<'_>,
    baseline_file: ModelExecutionFile<'_>,
    now: u64,
) -> ReviewResult<(Digest32, Vec<CalibrationExecution>)> {
    let source_bytes = read_root(source, 4 * 1024 * 1024, Access::Private)?;
    let source_digest = Digest32::of_bytes(&source_bytes);
    let mut gold = BTreeMap::new();
    for line in std::str::from_utf8(&source_bytes)?.lines() {
        if line.len() > 32 * 1024 {
            return Err("calibration source row exceeds bound".into());
        }
        let mut row: serde_json::Value = serde_json::from_str(line)?;
        if row["partition"] != "calibration" {
            return Err("only the frozen calibration partition may be read".into());
        }
        let class = match row["gold"].as_str() {
            Some("SUPPORT") => 0,
            Some("CONTRADICT") => 1,
            Some("unjudged") => continue,
            _ => return Err("unknown original source judgment".into()),
        };
        let digest: Digest32 = row["row_sha256"]
            .as_str()
            .ok_or("source row digest missing")?
            .parse()?;
        row.as_object_mut()
            .ok_or("source row must be an object")?
            .remove("row_sha256");
        if Digest32::of_bytes(&serde_json::to_vec(&row)?) != digest {
            return Err("original canonical source row digest mismatch".into());
        }
        let claim = row["claim_id"].as_u64().ok_or("claim identity missing")?;
        let doc = row["doc_id"].as_u64().ok_or("document identity missing")?;
        if gold.insert(digest, (claim, doc, class)).is_some() {
            return Err("duplicate labeled source pair".into());
        }
    }
    if gold.is_empty() || gold.len() > 2048 {
        return Err("calibration labeled source bound".into());
    }
    let mappings = parse_lines::<SourceMapping>(mapping, 1024)?;
    let frozen_inputs = parse_lines::<NativeInput>(inputs, 16 * 1024)?;
    let candidate = parse_lines::<NativeObservation>(candidate_file.path, 16 * 1024)?;
    let baseline = parse_lines::<NativeObservation>(baseline_file.path, 16 * 1024)?;
    if [
        mappings.len(),
        frozen_inputs.len(),
        candidate.len(),
        baseline.len(),
    ]
    .iter()
    .any(|len| *len != gold.len())
    {
        return Err(
            "all and only labeled calibration pairs require both actual model executions".into(),
        );
    }
    let mut seen_source = BTreeSet::new();
    let mut seen_request = BTreeSet::new();
    let mut executions = Vec::new();
    for (
        (((_, mapping), (input_bytes, input)), (candidate_bytes, candidate)),
        (baseline_bytes, baseline),
    ) in mappings
        .into_iter()
        .zip(frozen_inputs)
        .zip(candidate)
        .zip(baseline)
    {
        let source: Digest32 = mapping.source_record_sha256.parse()?;
        let (claim, doc, gold_class) = gold
            .get(&source)
            .copied()
            .ok_or("execution source is not a labeled calibration pair")?;
        if !seen_source.insert(source)
            || !seen_request.insert(mapping.request_id.clone())
            || (claim, doc) != (mapping.claim_id, mapping.doc_id)
            || mapping.request_id != input.request_id
            || input.feature_vector_q24.len() != 512
            || input.expected_output_width != 10
        {
            return Err("calibration source/input identity or dimensions mismatch".into());
        }
        let feature_bytes: Vec<u8> = input
            .feature_vector_q24
            .iter()
            .flat_map(|value| value.to_be_bytes())
            .collect();
        let feature_digest = Digest32::of_bytes(&feature_bytes);
        let input_line_digest = Digest32::of_bytes(&input_bytes);
        let candidate_class = validate_observation(
            &candidate,
            candidate_file.model,
            &input.request_id,
            input_line_digest,
            feature_digest,
            now,
        )?;
        let baseline_class = validate_observation(
            &baseline,
            baseline_file.model,
            &input.request_id,
            input_line_digest,
            feature_digest,
            now,
        )?;
        if baseline_class != 0 {
            return Err("the frozen training-majority SUPPORT baseline changed its policy".into());
        }
        executions.push(CalibrationExecution {
            candidate,
            baseline,
            candidate_class,
            baseline_class,
            gold_class,
            source_digest: source,
            candidate_support: Digest32::of_bytes(&candidate_bytes),
            baseline_support: Digest32::of_bytes(&baseline_bytes),
        });
    }
    Ok((source_digest, executions))
}

fn parse_lines<T: serde::de::DeserializeOwned>(
    path: &Path,
    row_maximum: usize,
) -> ReviewResult<Vec<(Vec<u8>, T)>> {
    let bytes = read_root(path, 4 * 1024 * 1024, Access::Private)?;
    if !bytes.ends_with(b"\n") {
        return Err("a complete terminated execution stream is required".into());
    }
    let mut values = Vec::new();
    for line in bytes.split_inclusive(|byte| *byte == b'\n') {
        if line.len() > row_maximum || values.len() >= 2048 {
            return Err("execution row or count bound".into());
        }
        values.push((line.to_vec(), serde_json::from_slice(line)?));
    }
    Ok(values)
}

fn validate_observation(
    value: &NativeObservation,
    model: &PinnedModel,
    request: &str,
    input_line: Digest32,
    input: Digest32,
    now: u64,
) -> ReviewResult<usize> {
    if value.schema != "hepta.cpu-neuron.offline-observation.v1"
        || value.request_id != request
        || value.model_manifest_digest.parse::<Digest32>()? != model.manifest
        || value.weights_digest.parse::<Digest32>()? != model.weights
        || value.runtime_digest.parse::<Digest32>()? != model.runtime
        || value.encoder_digest.parse::<Digest32>()? != model.encoder
        || value.head_digest.parse::<Digest32>()? != model.head
        || value.input_line_digest.parse::<Digest32>()? != input_line
        || value.input_digest.parse::<Digest32>()? != input
        || !value.terminal_observed
        || !value.succeeded
        || value.qualified
        || value.authority_grants_any
        || value.executed_at_ms > now
        || now - value.executed_at_ms > 60 * 60 * 1000
        || value.drive_q24.len() != 10
        || value.prediction_q24.len() != 10
        || value.resident_bytes == 0
        || value.latency_micros > 60 * 60 * 1_000_000
        || value.transient_allocation_bytes > 512 * 1024 * 1024
    {
        return Err("native execution is incomplete, stale, mismatched or claims authority".into());
    }
    let mut selected = 0;
    for index in 1..10 {
        if value.drive_q24[index] > value.drive_q24[selected] {
            selected = index;
        }
    }
    Ok(selected)
}

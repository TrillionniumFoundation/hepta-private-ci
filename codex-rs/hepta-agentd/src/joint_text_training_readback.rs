//! Validate bounded unsigned output bytes before their original owner accepts them.
use serde::Deserialize;

use super::JointTextTrainingErrorV1 as Error;
use super::JointTextTrainingOutputBytesV1;
use super::wire;
use super::wire::RequestWire;
use super::wire::SourceFileWire;
use codex_hepta_types::Digest32;

pub(super) const COST_SCOPE: &str = "worker request/checkpoint validation through candidate fsync and reload; excludes observation/marker fsync, host admission/queue/transfer/publication";
const GROUPS: [&str; 5] = [
    "core",
    "encoder",
    "transition_and_adapters",
    "text_head",
    "other_heads",
];

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Started {
    schema: String,
    profile: String,
    status: String,
    request_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Completed {
    schema: String,
    profile: String,
    status: String,
    request_sha256: String,
    observation_sha256: String,
    candidate_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Observation {
    schema: String,
    profile: String,
    status: String,
    authority: String,
    request_sha256: String,
    request_binding_digest: String,
    training_profile_digest: String,
    update_rule_digest: String,
    execution_source_digest: String,
    execution_sources: Vec<SourceFileWire>,
    absent_source_paths: Vec<String>,
    predecessor: Predecessor,
    candidate: Candidate,
    pub(super) training: Training,
    runtime: Runtime,
    pub(super) cost: Cost,
    claims: Claims,
    input_files_unchanged: bool,
    source_files_unchanged: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Predecessor {
    sha256: String,
    bytes: u64,
    after_sha256: String,
    roundtrip: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate {
    sha256: String,
    bytes: u64,
    roundtrip: bool,
    changed: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Training {
    requested_steps: u64,
    pub(super) completed_steps: u64,
    source_samples: u64,
    source_record_count: u64,
    dataset_observed_rows: u64,
    dataset_observed_bytes: u64,
    prefix_bytes: u64,
    continuation_bytes: u64,
    continuation_scalars: u64,
    losses_f64_be: Vec<String>,
    pub(super) parameter_groups: Vec<ParameterGroup>,
    core_gradient_nonzero: bool,
    pub(super) core_changed_parameters: u64,
    effective_wall_limit_milliseconds: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ParameterGroup {
    group: String,
    pub(super) parameters: u64,
    gradient_present_parameters: u64,
    gradient_nonzero_parameters: u64,
    changed_parameters: u64,
    max_abs_gradient_f64_be: String,
    max_abs_delta_f64_be: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Runtime {
    python_version: String,
    torch_version: String,
    platform: String,
    device: String,
    dtype: String,
    threads: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Cost {
    pub(super) wall_nanoseconds: u64,
    pub(super) cpu_nanoseconds: u64,
    scope: String,
    // Required explicit nulls: Option would also accept an omitted JSON field.
    physical_energy_joules: serde_json::Value,
    full_history_cost: serde_json::Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Claims {
    content_loss_training: bool,
    ndu_training: bool,
    evaluation: bool,
    product_loading: bool,
    selection: bool,
    stage_advanced: bool,
}

pub(super) fn validate(
    request: &RequestWire,
    request_bytes: &[u8],
    files: &JointTextTrainingOutputBytesV1<'_>,
) -> Result<Observation, Error> {
    request.validate()?;
    if files.failed.is_some() {
        return Err(Error::Binding("failed worker output"));
    }
    if files.candidate.is_empty()
        || files.candidate.len() > wire::MAX_PACKET_BYTES
        || files.candidate.len() as u64 > request.maximum_artifact_bytes
    {
        return Err(Error::Capacity);
    }
    let started: Started = wire::parse_json(files.started)?;
    let completed: Completed = wire::parse_json(files.completed)?;
    let observation: Observation = wire::parse_json(files.observation)?;
    let request_sha = Digest32::of_bytes(request_bytes);
    let candidate_sha = Digest32::of_bytes(files.candidate);
    if started.schema != "hepta.joint-text-worker.started.v1"
        || started.profile != wire::PROFILE
        || started.status != "started"
        || wire::digest(&started.request_sha256)? != request_sha
        || completed.schema != "hepta.joint-text-worker.completed.v1"
        || completed.profile != wire::PROFILE
        || completed.status != "complete"
        || wire::digest(&completed.request_sha256)? != request_sha
        || wire::digest(&completed.observation_sha256)? != Digest32::of_bytes(files.observation)
        || wire::digest(&completed.candidate_sha256)? != candidate_sha
    {
        return Err(Error::Binding("original completed byte closure"));
    }
    if observation.schema != "hepta.joint-text-worker.observation.v1"
        || observation.profile != wire::PROFILE
        || observation.status != "candidate"
        || observation.authority != "DENY_ALL"
        || wire::digest(&observation.request_sha256)? != request_sha
        || wire::digest(&observation.request_binding_digest)? != request.binding_digest()?
        || wire::digest(&observation.training_profile_digest)?
            != Digest32::of_bytes(wire::PROFILE_BYTES)
        || wire::digest(&observation.update_rule_digest)? != request.update_rule()?
        || wire::digest(&observation.execution_source_digest)?
            != wire::digest(&request.execution_source_digest)?
        || wire::source_digest(
            &observation.execution_sources,
            &observation.absent_source_paths,
        )? != wire::digest(&request.execution_source_digest)?
        || !observation.input_files_unchanged
        || !observation.source_files_unchanged
    {
        return Err(Error::Binding("request or execution source"));
    }
    let predecessor = &observation.predecessor;
    let candidate = &observation.candidate;
    if predecessor.sha256 != request.predecessor_sha256
        || predecessor.after_sha256 != request.predecessor_sha256
        || predecessor.bytes != request.predecessor_bytes
        || !predecessor.roundtrip
        || wire::digest(&candidate.sha256)? != candidate_sha
        || candidate.bytes != files.candidate.len() as u64
        || !candidate.roundtrip
        || !candidate.changed
        || candidate_sha == wire::digest(&request.predecessor_sha256)?
    {
        return Err(Error::Binding("physical predecessor or candidate"));
    }
    let training = &observation.training;
    let limit = request.maximum_training_milliseconds.min(wire::MAX_WALL_MS);
    if training.requested_steps != request.steps
        || training.completed_steps != request.steps
        || training.source_samples != 1
        || training.source_record_count != request.source_record_count
        || training.dataset_observed_rows != request.dataset_observed_rows
        || training.dataset_observed_bytes != request.dataset_observed_bytes
        || training.prefix_bytes != request.prefix.len() as u64
        || training.continuation_bytes != request.continuation.len() as u64
        || training.continuation_scalars != request.continuation.chars().count() as u64
        || training.effective_wall_limit_milliseconds != limit
        || training.losses_f64_be.len() as u64 != request.steps + 1
    {
        return Err(Error::Binding("actual training counters"));
    }
    for loss in &training.losses_f64_be {
        if wire::finite_f64(loss)? < 0.0 {
            return Err(Error::Binding("negative content loss"));
        }
    }
    if training.parameter_groups.len() != GROUPS.len() {
        return Err(Error::Binding("parameter group inventory"));
    }
    for (group, expected) in training.parameter_groups.iter().zip(GROUPS) {
        let gradient = wire::finite_f64(&group.max_abs_gradient_f64_be)?;
        let delta = wire::finite_f64(&group.max_abs_delta_f64_be)?;
        if group.group != expected
            || group.parameters == 0
            || group.parameters > wire::MAX_PACKET_BYTES as u64 / 8
            || group.gradient_present_parameters > group.parameters
            || group.gradient_nonzero_parameters > group.gradient_present_parameters
            || group.changed_parameters > group.gradient_nonzero_parameters
            || gradient < 0.0
            || delta < 0.0
            || (gradient == 0.0) != (group.gradient_nonzero_parameters == 0)
            || (delta == 0.0) != (group.changed_parameters == 0)
        {
            return Err(Error::Binding("unique scalar parameter accounting"));
        }
    }
    let core = &training.parameter_groups[0];
    if !training.core_gradient_nonzero
        || core.gradient_nonzero_parameters == 0
        || core.changed_parameters == 0
        || training.core_changed_parameters != core.changed_parameters
    {
        return Err(Error::Binding("core gradient and update observation"));
    }
    let runtime = &observation.runtime;
    if runtime.device != "cpu"
        || runtime.dtype != "float64"
        || runtime.threads != 1
        || [
            &runtime.python_version,
            &runtime.torch_version,
            &runtime.platform,
        ]
        .iter()
        .any(|value| value.is_empty() || value.len() > 256)
    {
        return Err(Error::Binding("worker numerical runtime"));
    }
    let cost = &observation.cost;
    if cost.scope != COST_SCOPE
        || !cost.physical_energy_joules.is_null()
        || !cost.full_history_cost.is_null()
        || cost.wall_nanoseconds == 0
        || cost.wall_nanoseconds > limit * 1_000_000
    {
        return Err(Error::Binding("measured worker cost scope"));
    }
    let claims = &observation.claims;
    if !claims.content_loss_training
        || claims.ndu_training
        || claims.evaluation
        || claims.product_loading
        || claims.selection
        || claims.stage_advanced
    {
        return Err(Error::Binding("unsupported worker claim"));
    }
    Ok(observation)
}

//! V13 process messages bind one new caller input and an already named learning
//! closure. They carry no journal path, training command or adoption authority.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::CellGenerationDispositionV2;
use crate::CellGenerationErrorV2;
use crate::CellLearningBindingV2;
use crate::cell_v13_process::ProcessStatus;

pub(crate) const MAX_PROCESS_RESULT_BYTES: usize = 131_072;
pub(crate) const MAX_ASSET_BYTES: usize = 512 * 1024 * 1024;
pub(crate) const MAX_TASK_BYTES: usize = 8192;
const MAX_HEADER_BYTES: usize = 32_768;
const SKILLS: [&str; 12] = [
    "unique_stable",
    "sort_numeric",
    "sort_casefold",
    "count_items",
    "normalize_nfc",
    "normalize_nfkc",
    "casefold",
    "collapse_whitespace",
    "csv_parse",
    "csv_write",
    "json_parse",
    "json_compact",
];

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct V13LearningClosureV1 {
    pub checkpoint_digest: [u8; 32],
    pub state_digest: [u8; 32],
    pub encoder_digest: [u8; 32],
    pub source_version: [u8; 32],
    pub data_identity: [u8; 32],
    pub learning: CellLearningBindingV2,
}

impl V13LearningClosureV1 {
    pub(crate) fn binding(&self) -> Result<Value, CellGenerationErrorV2> {
        let CellLearningBindingV2::Resumable {
            weights,
            optimizer,
            rng,
            sampler,
            training_cursor,
        } = &self.learning
        else {
            return Err(CellGenerationErrorV2::InvalidBinding);
        };
        let members = [
            ("weights", weights),
            ("optimizer", optimizer),
            ("rng", rng),
            ("sampler", sampler),
            ("training_cursor", training_cursor),
        ];
        if [
            self.checkpoint_digest,
            self.state_digest,
            self.encoder_digest,
            self.source_version,
            self.data_identity,
        ]
        .contains(&[0; 32])
            || members.iter().any(|(_, digest)| **digest == [0; 32])
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let learning: BTreeMap<_, _> = members
            .into_iter()
            .map(|(name, value)| (name, hex(*value)))
            .collect();
        Ok(serde_json::json!({
            "checkpoint_sha256": hex(self.checkpoint_digest),
            "state_sha256": hex(self.state_digest),
            "encoder_hash": hex(self.encoder_digest),
            "source_version": hex(self.source_version),
            "data_id": hex(self.data_identity), "learning": learning,
        }))
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct V13TaskInputV1 {
    pub schema: String,
    pub text: String,
    pub payload: Value,
}

impl V13TaskInputV1 {
    pub fn encode(&self) -> Result<Vec<u8>, CellGenerationErrorV2> {
        let bytes = serde_json::to_vec(self).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        if self.schema != "hepta.v13.task-input.v1"
            || self.text.is_empty()
            || self.text.len() > 4096
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if bytes.len() > MAX_TASK_BYTES {
            return Err(CellGenerationErrorV2::Capacity);
        }
        Ok(bytes)
    }
}

pub(crate) struct AssetBytes {
    pub(crate) bytes: Vec<u8>,
    pub(crate) digest: [u8; 32],
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(crate) enum Phase {
    Verify,
    Infer,
}

impl Phase {
    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Verify => "verify",
            Self::Infer => "infer",
        }
    }

    fn uses(self, name: &str) -> bool {
        match self {
            Self::Verify => name != "vendor/reference/tasks.py.source",
            Self::Infer => {
                name == "model.npz"
                    || name == "encoder.json"
                    || name.starts_with("encoder/")
                    || [
                        "vendor/reference/adapter.py.source",
                        "vendor/reference/backend.py.source",
                        "vendor/reference/download_model.py.source",
                        "vendor/reference/tasks.py.source",
                    ]
                    .contains(&name)
            }
        }
    }
}

pub(crate) struct PhasePayload<'a> {
    pub(crate) phase: Phase,
    pub(crate) request_digest: [u8; 32],
    pub(crate) admitted_at_micros: u64,
    pub(crate) deadline_micros: u64,
    pub(crate) closure: &'a V13LearningClosureV1,
    pub(crate) task: Option<&'a V13TaskInputV1>,
    pub(crate) cpu_seconds: u64,
    pub(crate) address_space_bytes: u64,
    pub(crate) assets: &'a BTreeMap<String, AssetBytes>,
}

pub(crate) fn payload(input: PhasePayload<'_>) -> Result<Vec<u8>, CellGenerationErrorV2> {
    let mut total = 0_usize;
    let mut descriptions = Vec::new();
    for (name, asset) in input
        .assets
        .iter()
        .filter(|(name, _)| input.phase.uses(name))
    {
        total = total
            .checked_add(asset.bytes.len())
            .ok_or(CellGenerationErrorV2::Capacity)?;
        descriptions.push(serde_json::json!({"name": name, "bytes": asset.bytes.len(),
            "sha256": hex(asset.digest)}));
    }
    let header = serde_json::to_vec(&serde_json::json!({
        "schema": "hepta.v13.process.v1", "mode": input.phase.name(),
        "request_digest": hex(input.request_digest), "binding": input.closure.binding()?,
        "task": input.task, "assets": descriptions,
        "clock": {"admitted_at_micros": input.admitted_at_micros, "deadline_micros": input.deadline_micros},
        "limits": {"cpu_seconds": input.cpu_seconds, "address_space_bytes": input.address_space_bytes},
    })).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    if header.len() > MAX_HEADER_BYTES || total > MAX_ASSET_BYTES {
        return Err(CellGenerationErrorV2::Capacity);
    }
    let mut bytes = Vec::with_capacity(4 + header.len() + total);
    bytes.extend_from_slice(&(header.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&header);
    for (_, asset) in input
        .assets
        .iter()
        .filter(|(name, _)| input.phase.uses(name))
    {
        bytes.extend_from_slice(&asset.bytes);
    }
    Ok(bytes)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseCost {
    pub(crate) stage: String,
    pub(crate) wall_micros: u64,
    pub(crate) cpu_micros: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseProgress {
    pub(crate) staged_bytes: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseResponse {
    schema: String,
    authority: String,
    pub(crate) status: String,
    mode: Option<String>,
    request_digest: Option<String>,
    pub(crate) wall_micros: u64,
    pub(crate) cpu_micros: u64,
    pub(crate) phases: Vec<PhaseCost>,
    pub(crate) enforced_resources: BTreeMap<String, [u64; 2]>,
    pub(crate) progress: PhaseProgress,
    pub(crate) details: Value,
}

impl PhaseResponse {
    pub(crate) fn limits_within(&self, cpu_seconds: u64, address_space_bytes: u64) -> bool {
        self.enforced_resources.len() == 4
            && [
                ("cpu_seconds", cpu_seconds),
                ("address_space_bytes", address_space_bytes),
                ("file_bytes", 128 * 1024 * 1024),
                ("core_bytes", 0),
            ]
            .into_iter()
            .all(|(name, maximum)| {
                self.enforced_resources
                    .get(name)
                    .is_some_and(|[soft, hard]| soft <= hard && *hard <= maximum)
            })
    }
}

pub(crate) fn response(
    bytes: &[u8],
    phase: Phase,
    request: [u8; 32],
) -> Result<PhaseResponse, CellGenerationErrorV2> {
    let result: PhaseResponse =
        serde_json::from_slice(bytes).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    if result.schema != "hepta.v13.process-result.v1"
        || result.authority != "DENY_ALL"
        || result.mode.as_deref() != Some(phase.name())
        || result.request_digest.as_deref() != Some(hex(request).as_str())
        || result.progress.staged_bytes > MAX_ASSET_BYTES as u64
        || result.phases.len() > 3
        || (phase == Phase::Infer && result.status == "succeeded" && result.phases.len() != 3)
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let expected_stages = ["encoder", "inference", "codec"];
    let (mut wall, mut cpu) = (0_u64, 0_u64);
    for (index, item) in result.phases.iter().enumerate() {
        if phase == Phase::Verify || item.stage != expected_stages[index] {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        wall = wall
            .checked_add(item.wall_micros)
            .ok_or(CellGenerationErrorV2::Capacity)?;
        cpu = cpu
            .checked_add(item.cpu_micros)
            .ok_or(CellGenerationErrorV2::Capacity)?;
    }
    if wall > result.wall_micros || cpu > result.cpu_micros {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(result)
}

pub(crate) fn terminal_status(
    status: &ProcessStatus,
    response: Option<&PhaseResponse>,
    phase: Phase,
) -> Option<CellGenerationDispositionV2> {
    match status {
        ProcessStatus::Cancelled => Some(CellGenerationDispositionV2::Cancelled),
        ProcessStatus::Deadline => Some(CellGenerationDispositionV2::DeadlineExceeded),
        ProcessStatus::Succeeded | ProcessStatus::Failed => {
            // A bound negative receipt may close stdin early. Broken input is
            // never promoted to successful verification or model output.
            match response.map(|value| value.status.as_str()) {
                Some("deadline") => Some(CellGenerationDispositionV2::DeadlineExceeded),
                Some("rejected") if phase == Phase::Verify => {
                    Some(CellGenerationDispositionV2::Rejected)
                }
                _ if matches!(status, ProcessStatus::Failed) => {
                    Some(CellGenerationDispositionV2::Failed)
                }
                _ => None,
            }
        }
    }
}

pub(crate) fn verified(
    result: &PhaseResponse,
    expected: &V13LearningClosureV1,
) -> Result<(), CellGenerationErrorV2> {
    let closure = &result.details["closure"];
    let actual = serde_json::json!({
        "checkpoint_sha256": closure["checkpoint"]["sha256"],
        "state_sha256": closure["checkpoint"]["legacy_state_sha256"],
        "encoder_hash": closure["context"]["encoder_hash"],
        "source_version": closure["context"]["source_version"],
        "data_id": closure["context"]["data_id"], "learning": closure["member_sha256"],
    });
    if result.status != "verified"
        || result.details["closure_validation_performed"] != true
        || actual != expected.binding()?
        || closure["authority"] != "DENY_ALL"
        || closure["verification_mode"] != "reference"
        || closure["synthetic"] != false
        || closure["training_executed"] != false
        || closure["inference_executed"] != false
        || closure["adoption_performed"] != false
        || closure["binding"]
            != serde_json::to_value(&expected.learning)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TaskOutput {
    schema: String,
    request_digest: String,
    skill_index: usize,
    skill: String,
    value: Value,
}

pub(crate) fn output(
    result: &PhaseResponse,
    request: [u8; 32],
    closure: &V13LearningClosureV1,
) -> Result<Vec<u8>, CellGenerationErrorV2> {
    let details = &result.details;
    let output: TaskOutput = serde_json::from_value(details["result"].clone())
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    if result.status != "succeeded"
        || output.schema != "hepta.v13.task-output.v1"
        || output.request_digest != hex(request)
        || SKILLS.get(output.skill_index).copied() != Some(output.skill.as_str())
        || details["state_before"] != hex(closure.state_digest)
        || details["state_after"] != hex(closure.state_digest)
        || details["closure_validation_performed"] != false
        || details["training_data_received"] != false
        || details["task_rows_received"] != false
        || details["features"]["shape"] != serde_json::json!([1, 384])
        || details["features"]["dtype"] != "<f4"
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let mut bytes =
        serde_json::to_vec(&output).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    bytes.push(b'\n');
    if bytes.len() > 65_536 {
        return Err(CellGenerationErrorV2::Capacity);
    }
    Ok(bytes)
}

pub(crate) fn hex(value: [u8; 32]) -> String {
    Digest32::from_array(value).to_string()
}

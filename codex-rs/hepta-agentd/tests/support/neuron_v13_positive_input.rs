//! Explicit pinned historical inputs for an opt-in real MiniLM qualification.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::neuron_generation_process_identity_digest_v1;
use codex_hepta_agentd::prepare_agentd_v13_generation_worker_v1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

const TEXT: &str = "For the incoming batch in this qualification run, sort these decimal strings by their numeric value, keeping duplicates.";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Pin {
    path: PathBuf,
    #[serde(deserialize_with = "hex_digest")]
    sha256: Digest32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Asset {
    name: String,
    path: PathBuf,
    #[serde(deserialize_with = "hex_digest")]
    sha256: Digest32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Input {
    schema: String,
    authority: String,
    interpreter_argv0: PathBuf,
    interpreter: Pin,
    worker: Pin,
    assets: Vec<Asset>,
    closure: V13LearningClosureV1,
    source_digest: [u8; 32],
    evolution: CellEvolutionBindingV2,
    historical_bootstrap: Pin,
    pub(super) task: V13TaskInputV1,
    pub(super) expected_skill: String,
    pub(super) expected_value: Value,
}

fn hex_digest<'de, D: serde::Deserializer<'de>>(value: D) -> Result<Digest32, D::Error> {
    String::deserialize(value)?
        .parse()
        .map_err(serde::de::Error::custom)
}

fn open(path: &Path) -> Result<File> {
    ensure!(
        path.is_absolute() && path.canonicalize()? == path,
        "noncanonical asset path"
    );
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    ensure!(file.metadata()?.is_file(), "asset is not a regular file");
    Ok(file)
}

fn read_pinned(path: &Path, digest: Digest32, maximum: u64) -> Result<Vec<u8>> {
    let file = open(path)?;
    let size = file.metadata()?.len();
    ensure!(
        size > 0 && size <= maximum && !digest.is_zero(),
        "unbounded or unpinned input"
    );
    let mut raw = Vec::new();
    file.take(maximum + 1).read_to_end(&mut raw)?;
    ensure!(
        raw.len() as u64 == size && Digest32::of_bytes(&raw) == digest,
        "input pin differs"
    );
    Ok(raw)
}

pub(super) fn load() -> Result<(Input, Digest32, PathBuf)> {
    let path = PathBuf::from(std::env::var("HEPTA_V13_ORDINARY_QUALIFICATION_INPUT")?);
    let digest: Digest32 = std::env::var("HEPTA_V13_ORDINARY_QUALIFICATION_SHA256")?.parse()?;
    let output = PathBuf::from(std::env::var("HEPTA_V13_ORDINARY_QUALIFICATION_OUTPUT")?);
    let raw = read_pinned(&path, digest, /*maximum*/ 262_144)?;
    let input: Input = serde_json::from_slice(&raw)?;
    ensure!(
        input.schema == "hepta.v13.ordinary-qualification.v1"
            && input.authority == "DENY_ALL"
            && input.assets.len() == 24
            && input.source_digest != [0; 32],
        "unsupported qualification input"
    );
    ensure!(
        input.task.text == TEXT
            && input.task.payload == json!(["17.5", "-6.25", "17.5", "0.03125"])
            && input.expected_skill == "sort_numeric"
            && input.expected_value == json!(["-6.25", "0.03125", "17.5", "17.5"]),
        "fixed task or expected result changed"
    );
    input.task.encode()?;
    ensure!(
        input.worker.sha256
            == Digest32::of_bytes(include_bytes!(
                "../../../../qualification/neuron-v13-generation/proposal_worker.py"
            )),
        "qualification requires the actual compiled-source worker"
    );
    let parent: Value = serde_json::from_slice(&read_pinned(
        &input.historical_bootstrap.path,
        input.historical_bootstrap.sha256,
        /*maximum*/ 131_072,
    )?)?;
    let receipt = &parent["result"]["closure"];
    ensure!(
        parent["phase"] == "bootstrap"
            && parent["status"] == "completed"
            && parent["result"]["engineering_passed"] == true
            && parent["result"]["epoch"] == 1
            && parent["result"]["artifact"] == receipt["release"]["artifact_id"]
            && receipt["schema"] == "hepta.cell-learning.v13.content-binding.v1"
            && receipt["authority"] == "DENY_ALL"
            && receipt["verification_mode"] == "reference",
        "historical parent receipt differs"
    );
    for name in [
        "synthetic",
        "training_executed",
        "inference_executed",
        "adoption_performed",
    ] {
        ensure!(
            receipt[name] == false,
            "unsupported parent content receipt: {name}"
        );
    }
    for (observed, expected) in [
        (
            &receipt["checkpoint"]["sha256"],
            input.closure.checkpoint_digest,
        ),
        (
            &receipt["checkpoint"]["legacy_state_sha256"],
            input.closure.state_digest,
        ),
        (
            &receipt["context"]["encoder_hash"],
            input.closure.encoder_digest,
        ),
        (
            &receipt["context"]["source_version"],
            input.closure.source_version,
        ),
        (&receipt["context"]["data_id"], input.closure.data_identity),
    ] {
        ensure!(
            observed
                .as_str()
                .and_then(|value| value.parse::<Digest32>().ok())
                == Some(Digest32::from_array(expected)),
            "parent closure differs"
        );
    }
    ensure!(
        receipt["binding"] == serde_json::to_value(&input.closure.learning)?
            && input.evolution.source_dependencies == input.closure.source_version
            && input.evolution.adoption_receipt
                == Digest32::of_parts(&[
                    b"hepta.v13.deny-all-parent-fixture.v1\0",
                    input.historical_bootstrap.sha256.as_array()
                ])
                .into_array(),
        "historical fixture binding differs"
    );
    ensure!(
        output.is_absolute()
            && output.file_name().is_some()
            && output
                .parent()
                .is_some_and(|parent| parent.canonicalize().is_ok_and(|actual| actual == parent)),
        "qualification output parent must be canonical"
    );
    fs::create_dir(&output)?;
    Ok((input, digest, output))
}

impl Input {
    pub(super) fn descriptor(&self, root: &Path, identity: &AgentdIdentity) -> Result<Value> {
        let device_digest = V13GenerationProcessWorkerV1::observed_device_digest()?;
        let prepared = prepare_agentd_v13_generation_worker_v1(
            V13GenerationProcessConfigV1 {
                interpreter_argv0: self.interpreter_argv0.clone(),
                interpreter_digest: self.interpreter.sha256.into_array(),
                worker_digest: self.worker.sha256.into_array(),
                source_digest: self.source_digest,
                device_digest,
                closure: self.closure.clone(),
                phase_cpu_seconds: 30,
                address_space_bytes: 4 * 1024_u64.pow(3),
                wall_limit: Duration::from_secs(90),
            },
            V13GenerationProcessFilesV1 {
                interpreter: open(&self.interpreter.path)?,
                worker: open(&self.worker.path)?,
                assets: self
                    .assets
                    .iter()
                    .map(|asset| {
                        Ok(V13GenerationAssetFileV1 {
                            name: asset.name.clone(),
                            digest: asset.sha256.into_array(),
                            file: open(&asset.path)?,
                        })
                    })
                    .collect::<Result<_>>()?,
            },
        )?;
        let CellLearningBindingV2::Resumable { weights, .. } = &self.closure.learning else {
            anyhow::bail!("complete resumable parent is required")
        };
        let manifest = CellBackendManifestV2 {
            profile: V13GenerationProcessWorkerV1::PROFILE.into(),
            source_digest: self.source_digest,
            bundle_digest: prepared.worker().bundle_digest(),
            runtime_digest: prepared.worker().runtime_digest(),
            device_digest,
            encoder: Some(self.closure.encoder_digest),
            head: Some(*weights),
            memory: None,
            world_model: None,
            decoder: None,
            input_schema: V13GenerationProcessWorkerV1::input_schema_digest(),
            state_schema: V13GenerationProcessWorkerV1::state_schema_digest(),
            output_schema: V13GenerationProcessWorkerV1::output_schema_digest(),
            learning: self.closure.learning.clone(),
            evolution: self.evolution.clone(),
            max_input_bytes: 8192,
            max_state_bytes: 1,
            max_delta_bytes: 65_536,
            max_prefix_bytes: 65_536,
            max_step_cost_entries: 8,
            max_ack_cost_entries: 1,
        };
        let task_digest = Digest32::of_bytes(&self.task.encode()?).into_array();
        let config = CellGenerationConfigV2 {
            initial: CellRuntimeSnapshotV2 {
                scope: CellGenerationScopeV2 {
                    principal_digest: Digest32::of_bytes(b"deny-all historical V13 parent fixture")
                        .into_array(),
                    agent_id: identity.agent_id.to_string(),
                    cell_id: "v13-frozen-parent".into(),
                    run_id: Digest32::from_array(task_digest).to_string(),
                },
                manifest_digest: manifest.digest()?,
                generation: 1,
                writer_epoch: 1,
                revision: 0,
                state: Vec::new(),
                prefix: Vec::new(),
                stopped: false,
            },
            manifest,
            source_frontier: self.closure.source_version,
            task_digest,
        };
        let assets: Vec<_> = self.assets.iter().map(|asset| json!({"name": asset.name, "path": asset.path, "digest": asset.sha256.to_string()})).collect();
        Ok(json!({
            "schema": "hepta.agentd.neuron-v13-generation-bootstrap.v1",
            "identity_digest": neuron_generation_process_identity_digest_v1(identity)?.to_string(),
            "boot_id": fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim(),
            "mode": "create", "journal_path": root.join("cell.journal"),
            "witness_path": root.join("independent.witness"), "control_path": root.join("control.journal"),
            "max_records": 128, "control_capacity": 32, "queue_capacity": 4,
            "rpc_timeout_millis": 1000, "config": config,
            "interpreter_argv0": self.interpreter_argv0,
            "interpreter": {"path": self.interpreter.path, "digest": self.interpreter.sha256.to_string()},
            "worker": {"path": self.worker.path, "digest": self.worker.sha256.to_string()},
            "assets": assets, "closure": self.closure, "phase_cpu_seconds": 30,
            "address_space_bytes": 4 * 1024_u64.pow(3), "wall_limit_millis": 90000,
        }))
    }
}

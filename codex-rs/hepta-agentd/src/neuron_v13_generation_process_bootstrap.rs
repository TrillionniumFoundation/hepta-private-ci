//! Strict ordinary-entry V13 descriptor assembly. Pins identify host-selected
//! assets; they grant no training, publication or source-adoption authority.

use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::V13GenerationAssetFileV1;
use codex_hepta_neuron::V13GenerationProcessConfigV1;
use codex_hepta_neuron::V13GenerationProcessFilesV1;
use codex_hepta_neuron::V13GenerationProcessWorkerV1;
use codex_hepta_neuron::V13LearningClosureV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::files;
use super::linux::Asset;
use super::linux::OpenMode;
use super::linux::boot_id;
use super::linux::invalid;
use super::linux::parse_digest;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdV13GenerationBootstrapConfigV1;
use crate::NeuronGenerationRuntimeBootstrapV2;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::V13GenerationOwnerFilesV1;
use crate::V13GenerationOwnerModeV1;
use crate::bootstrap_agentd_v13_generation_v1;
use crate::neuron_generation_process_identity_digest_v1;
use crate::neuron_v13_generation_bootstrap::validate_bootstrap;
use crate::prepare_agentd_v13_generation_worker_v1;

pub(super) const SCHEMA: &str = "hepta.agentd.neuron-v13-generation-bootstrap.v1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NamedAsset {
    name: String,
    path: PathBuf,
    digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    schema: String,
    identity_digest: String,
    boot_id: String,
    mode: OpenMode,
    journal_path: PathBuf,
    witness_path: PathBuf,
    control_path: PathBuf,
    max_records: u64,
    control_capacity: usize,
    queue_capacity: usize,
    rpc_timeout_millis: u64,
    config: CellGenerationConfigV2,
    interpreter_argv0: PathBuf,
    interpreter: Asset,
    worker: Asset,
    assets: Vec<NamedAsset>,
    closure: V13LearningClosureV1,
    phase_cpu_seconds: u64,
    address_space_bytes: u64,
    wall_limit_millis: u64,
}

pub(super) fn load(
    path: &Path,
    bytes: &[u8],
    descriptor_file: File,
    identity: &AgentdIdentity,
) -> Result<
    (
        NeuronGenerationRuntimeHandleV2,
        NeuronGenerationRuntimeBootstrapV2,
    ),
    AgentdError,
> {
    let d: Descriptor = serde_json::from_slice(bytes)?;
    let expected_identity_digest = parse_digest(&d.identity_digest)?;
    if identity.spawn_generation == 0
        || d.schema != SCHEMA
        || expected_identity_digest != neuron_generation_process_identity_digest_v1(identity)?
        || d.boot_id != boot_id()?
        || d.config.initial.scope.agent_id != identity.agent_id.as_str()
    {
        return Err(AgentdError::GenerationFenced(
            "V13 generation descriptor identity or clock epoch differs".into(),
        ));
    }
    if d.config.manifest.profile != V13GenerationProcessWorkerV1::PROFILE || d.assets.len() != 24 {
        return Err(invalid(
            "unsupported V13 profile or incomplete asset catalog",
        ));
    }
    let immutable_paths: Vec<_> = [path, d.interpreter.path.as_path(), &d.worker.path]
        .into_iter()
        .chain(d.assets.iter().map(|asset| asset.path.as_path()))
        .collect();
    let owner_paths = [d.journal_path.as_path(), &d.witness_path, &d.control_path];
    files::validate_paths(d.mode, &immutable_paths, owner_paths)?;
    let assets = V13GenerationProcessFilesV1 {
        interpreter: files::open_immutable(&d.interpreter.path)?,
        worker: files::open_immutable(&d.worker.path)?,
        assets: d
            .assets
            .iter()
            .map(|asset| {
                Ok(V13GenerationAssetFileV1 {
                    name: asset.name.clone(),
                    digest: parse_digest(&asset.digest)?.into_array(),
                    file: files::open_immutable(&asset.path)?,
                })
            })
            .collect::<Result<_, AgentdError>>()?,
    };
    // Retain the exact opened descriptors across preparation and owner opening.
    // Path substitution cannot hide an asset/owner inode alias from this check.
    let retained = [&descriptor_file, &assets.interpreter, &assets.worker]
        .into_iter()
        .chain(assets.assets.iter().map(|asset| &asset.file))
        .map(File::try_clone)
        .collect::<Result<Vec<_>, _>>()?;
    let prepared = prepare_agentd_v13_generation_worker_v1(
        V13GenerationProcessConfigV1 {
            interpreter_argv0: d.interpreter_argv0,
            interpreter_digest: parse_digest(&d.interpreter.digest)?.into_array(),
            worker_digest: parse_digest(&d.worker.digest)?.into_array(),
            source_digest: d.config.manifest.source_digest,
            device_digest: d.config.manifest.device_digest,
            closure: d.closure,
            phase_cpu_seconds: d.phase_cpu_seconds,
            address_space_bytes: d.address_space_bytes,
            wall_limit: Duration::from_millis(d.wall_limit_millis),
        },
        assets,
    )?;
    let config = AgentdV13GenerationBootstrapConfigV1 {
        expected_identity_digest,
        expected_boot_id_digest: Digest32::of_parts(&[
            b"hepta.agentd.v13-generation-clock.v1\0",
            d.boot_id.as_bytes(),
        ]),
        generation: d.config,
        max_records: d.max_records,
        control_capacity: d.control_capacity,
        queue_capacity: d.queue_capacity,
        rpc_timeout: Duration::from_millis(d.rpc_timeout_millis),
    };
    validate_bootstrap(identity, &config, &prepared)?;
    let owners = files::open_owners(d.mode, owner_paths, &retained.iter().collect::<Vec<_>>())?;
    bootstrap_agentd_v13_generation_v1(
        identity,
        config,
        V13GenerationOwnerFilesV1 {
            journal: owners.journal,
            witness: owners.witness,
            control: owners.control,
        },
        match d.mode {
            OpenMode::Create => V13GenerationOwnerModeV1::InitializeEmpty,
            OpenMode::Reopen => V13GenerationOwnerModeV1::Reopen,
        },
        &prepared,
    )
}

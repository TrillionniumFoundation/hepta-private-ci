//! Independently pinned host-file decoding for the ordinary neural Agentd.
//! The file carries original owner configuration, not an opaque qualification
//! or selection result. Qualified parameters come only from the descriptor FD.

use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::model_worker::ResourceGrant;
use crate::smollm_cognitive_host::SmolLmCognitiveCellHostInputsV2;
use crate::smollm_cognitive_host::SmolLmCognitiveHostInputsV1;
use crate::smollm_neural_read::ControlledCellInputsV2;
use crate::smollm_neural_read::SmolLmNeuralReadConfigV1;

const MAX_HOST_FILE_BYTES: u64 = 64 * 1024;
const MAX_CONTRACT_BYTES: u64 = 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PinnedFile {
    path: PathBuf,
    sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceGrantFile {
    grant_id: String,
    authority_epoch: u64,
    generation: u64,
    expires_at_ms: u64,
    revoked: bool,
    maximum_models: usize,
    maximum_active_requests: usize,
    maximum_memory_bytes: u64,
    semantic_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerFile {
    python: PathBuf,
    script: PathBuf,
    materials: PathBuf,
    run_directory: PathBuf,
    source_pins: BTreeMap<PathBuf, String>,
    target_contract: PinnedFile,
    wrapped_adapter: PinnedFile,
    contract_digest: String,
    adapter_digest: String,
    backbone_digest: String,
    tokenizer_digest: String,
    action_completions: BTreeMap<String, String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostFile {
    schema: String,
    descriptor: PinnedFile,
    worker: WorkerFile,
    worker_id: String,
    resource_grant: ResourceGrantFile,
    inference_journal: PathBuf,
    inference_journal_capacity: usize,
    final_use_authorizer_config: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CellHostFileV2 {
    schema: String,
    owner: HostFile,
    sidecar: PinnedFile,
    dependency_closure: PinnedFile,
    dependency_closure_id: String,
    operation_id: String,
}

/// Decode a new, explicit schema without making an old host file satisfy Cell
/// admission. Original descriptor/resource/FinalUse fields stay with their owner.
pub fn load_smollm_cognitive_cell_host_inputs_v2(
    path: &Path,
    expected: Digest32,
) -> Result<SmolLmCognitiveCellHostInputsV2, String> {
    let bytes = read_pinned_file(path, expected, MAX_HOST_FILE_BYTES)?;
    let file: CellHostFileV2 = serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
    if file.schema != "hepta-smollm-cognitive-cell-host-v2" {
        return Err("unsupported Cell neural cognitive host schema".to_owned());
    }
    let sidecar_digest = file
        .sidecar
        .sha256
        .parse::<Digest32>()
        .map_err(|e| e.to_string())?;
    let sidecar = read_pinned_file(&file.sidecar.path, sidecar_digest, /*limit*/ 65_536)?;
    let dependency_wire = read_pinned_file(
        &file.dependency_closure.path,
        file.dependency_closure
            .sha256
            .parse::<Digest32>()
            .map_err(|e| e.to_string())?,
        /*limit*/ 1_048_576,
    )?;
    let dependency_id = file
        .dependency_closure_id
        .parse::<Digest32>()
        .map_err(|e| e.to_string())?;
    if dependency_id.is_zero()
        || file.operation_id.is_empty()
        || file.operation_id.len() > 128
        || !file
            .operation_id
            .bytes()
            .all(|byte| byte.is_ascii_graphic())
    {
        return Err("Cell host dependency pin or operation identity".to_owned());
    }
    Ok(SmolLmCognitiveCellHostInputsV2 {
        owner: decode_host(file.owner)?,
        cell: ControlledCellInputsV2 {
            sidecar,
            sidecar_digest,
            dependency_wire,
            dependency_id,
            operation_id: file.operation_id,
        },
    })
}

/// Decode the exact independently authorized host file. No journal is opened,
/// grant issued, qualification accepted or model loaded during this operation.
pub fn load_smollm_cognitive_host_inputs_v1(
    path: &Path,
    expected: Digest32,
) -> Result<SmolLmCognitiveHostInputsV1, String> {
    let bytes = read_pinned_file(path, expected, MAX_HOST_FILE_BYTES)?;
    let file: HostFile = serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
    decode_host(file)
}

fn decode_host(file: HostFile) -> Result<SmolLmCognitiveHostInputsV1, String> {
    if file.schema != "hepta-smollm-cognitive-host-v1" {
        return Err("unsupported neural cognitive host schema".to_owned());
    }
    let raw = file.worker;
    let target_contract = read_pinned_file(
        &raw.target_contract.path,
        raw.target_contract
            .sha256
            .parse::<Digest32>()
            .map_err(|error| error.to_string())?,
        MAX_CONTRACT_BYTES,
    )?;
    let wrapped_adapter = read_pinned_file(
        &raw.wrapped_adapter.path,
        raw.wrapped_adapter
            .sha256
            .parse::<Digest32>()
            .map_err(|error| error.to_string())?,
        MAX_CONTRACT_BYTES,
    )?;
    let source_pins = raw
        .source_pins
        .into_iter()
        .map(|(path, digest)| {
            Ok((
                path,
                digest
                    .parse::<Digest32>()
                    .map_err(|error| error.to_string())?,
            ))
        })
        .collect::<Result<BTreeMap<_, _>, String>>()?;
    let action_completions = raw
        .action_completions
        .into_iter()
        .map(|(id, completion)| {
            Ok((
                StableId::new(id).map_err(|error| error.to_string())?,
                completion,
            ))
        })
        .collect::<Result<BTreeMap<_, _>, String>>()?;
    let grant = file.resource_grant;
    Ok(SmolLmCognitiveHostInputsV1 {
        descriptor: file.descriptor.path,
        descriptor_digest: file
            .descriptor
            .sha256
            .parse::<Digest32>()
            .map_err(|error| error.to_string())?,
        worker: SmolLmNeuralReadConfigV1 {
            python: raw.python,
            script: raw.script,
            materials: raw.materials,
            run_directory: raw.run_directory,
            source_pins,
            target_contract,
            wrapped_adapter,
            contract_digest: raw
                .contract_digest
                .parse::<Digest32>()
                .map_err(|error| error.to_string())?,
            adapter_digest: raw
                .adapter_digest
                .parse::<Digest32>()
                .map_err(|error| error.to_string())?,
            backbone_digest: raw
                .backbone_digest
                .parse::<Digest32>()
                .map_err(|error| error.to_string())?,
            tokenizer_digest: raw
                .tokenizer_digest
                .parse::<Digest32>()
                .map_err(|error| error.to_string())?,
            action_completions,
        },
        worker_id: file.worker_id,
        resource_grant: ResourceGrant {
            grant_id: grant.grant_id,
            authority_epoch: grant.authority_epoch,
            generation: grant.generation,
            expires_at_ms: grant.expires_at_ms,
            revoked: grant.revoked,
            maximum_models: grant.maximum_models,
            maximum_active_requests: grant.maximum_active_requests,
            maximum_memory_bytes: grant.maximum_memory_bytes,
            semantic_digest: grant.semantic_digest,
        },
        inference_journal: file.inference_journal,
        inference_journal_capacity: file.inference_journal_capacity,
        final_use_authorizer_config: file.final_use_authorizer_config,
    })
}

fn read_pinned_file(path: &Path, expected: Digest32, limit: u64) -> Result<Vec<u8>, String> {
    if !path.is_absolute()
        || expected.is_zero()
        || path.canonicalize().map_err(|error| error.to_string())? != path
    {
        return Err("neural host material requires an exact canonical path and digest".to_owned());
    }
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|error| error.to_string())?;
    let metadata = file.metadata().map_err(|error| error.to_string())?;
    let uid = rustix::process::geteuid().as_raw();
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.mode() & 0o022 != 0
        || (metadata.uid() != 0 && metadata.uid() != uid)
        || metadata.len() == 0
        || metadata.len() > limit
    {
        return Err("neural host material must be bounded, protected and unaliased".to_owned());
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.len() as u64 > limit || Digest32::of_bytes(&bytes) != expected {
        return Err("neural host material differs from its independently pinned digest".to_owned());
    }
    Ok(bytes)
}

#[cfg(test)]
#[path = "smollm_cognitive_process_tests.rs"]
mod tests;

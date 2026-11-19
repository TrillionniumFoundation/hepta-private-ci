//! Strict first-A data from the original sealed launch descriptor. Actual
//! model bytes and the full Root target are checked before any Initial effect.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::files::OriginalFiles;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CellQ24ModelFilesV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalRootInitialLaunchDataV1;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::RootGenerationInitialModeV1;

pub(super) struct OriginalDeployment {
    pub(super) ledger: Option<super::ledger_data::LedgerDeploymentData>,
    pub(super) initial: OriginalRootInitialLaunchDataV1,
    pub(super) source: OriginalSingleQ24SourceConfigurationV1,
    pub(super) model: Arc<LoadedCellQ24ModelV1>,
    pub(super) bundle: CellCompatibilityBundleV1,
    pub(super) cell: CellFiles,
    pub(super) inference_control: PathBuf,
    pub(super) inference_capacity: usize,
    pub(super) worker_generation: u64,
    pub(super) maximum_cell_records: usize,
    pub(super) queue_capacity: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    #[serde(default)]
    ledger: Option<super::ledger_data::LedgerDeploymentData>,
    schema: String,
    identity_digest: String,
    clock: String,
    initial: serde_json::Value,
    source: serde_json::Value,
    model: ModelFiles,
    bundle: BundleData,
    cell: CellFiles,
    inference_control: PathBuf,
    inference_capacity: usize,
    worker_generation: u64,
    maximum_cell_records: usize,
    queue_capacity: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ModelFiles {
    base: PathBuf,
    organ_adapter: Option<PathBuf>,
    cell_adapter: Option<PathBuf>,
    encoder: PathBuf,
    heads: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BundleData {
    artifact_id: String,
    generation: u64,
    training_lineage: Option<LineageData>,
    rollback_predecessor: Option<[u8; 32]>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LineageData {
    source_bundle: [u8; 32],
    dataset: [u8; 32],
    update_rule: [u8; 32],
    evaluation_profile: [u8; 32],
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CellFiles {
    pub(super) journal: PathBuf,
    pub(super) witness: PathBuf,
    pub(super) witness_scope: [u8; 32],
    pub(super) witness_objective: [u8; 32],
    pub(super) witness_generation: u64,
    pub(super) witness_records: usize,
}

pub(super) fn read(
    mut file: File,
    identity: &AgentdIdentity,
    files: &mut OriginalFiles,
) -> Result<OriginalDeployment, AgentdError> {
    let size = file.metadata()?.len();
    if size == 0 || size > 1_048_576 {
        return Err(invalid("bounded original sealed deployment required"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    file.rewind()?;
    let mut bytes = Vec::with_capacity(size as usize);
    Read::by_ref(&mut file)
        .take(size + 1)
        .read_to_end(&mut bytes)?;
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    if bytes.len() as u64 != size {
        return Err(invalid("original sealed deployment length changed"));
    }
    let data: Deployment = serde_json::from_slice(&bytes)?;
    if data.schema != "hepta.agentd.original_initial_q24_launch.v1"
        || data.clock != super::clock::DOMAIN
        || data.identity_digest.parse::<Digest32>().map_err(invalid)?
            != crate::neuron_generation_process_identity_digest_v1(identity)?
        || !(1..=16_384).contains(&data.inference_capacity)
        || data.worker_generation == 0
        || !(3..=16).contains(&data.maximum_cell_records)
        || !(1..=64).contains(&data.queue_capacity)
    {
        return Err(invalid(
            "original identity, clock or bounded capacity differs",
        ));
    }
    let initial = OriginalRootInitialLaunchDataV1::from_original_deployment_value(data.initial)?;
    let source = OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
        &serde_json::to_vec(&data.source)?,
        identity,
    )?;
    if initial.mode != RootGenerationInitialModeV1::Reserve
        || source.fence.owner_agent_id != identity.agent_id
        || identity.spawn_generation.checked_add(1) != Some(source.fence.generation)
    {
        return Err(invalid(
            "first-A requires its original Reserve and Circuit owner fence",
        ));
    }
    super::clock::require_source_deadline(&source.source)?;
    let paths = data.model;
    let model = Arc::new(
        LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
            base: files.read(&paths.base)?,
            organ_adapter: paths
                .organ_adapter
                .as_deref()
                .map(|path| files.read(path))
                .transpose()?,
            cell_adapter: paths
                .cell_adapter
                .as_deref()
                .map(|path| files.read(path))
                .transpose()?,
            encoder: files.read(&paths.encoder)?,
            heads: files.read(&paths.heads)?,
        })
        .map_err(invalid)?,
    );
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: StableId::new(data.bundle.artifact_id).map_err(invalid)?,
        generation: Generation::new(data.bundle.generation).map_err(invalid)?,
        components: model.components().clone(),
        training_lineage: data
            .bundle
            .training_lineage
            .map(|lineage| CellTrainingLineageV1 {
                source_bundle: Digest32::from_array(lineage.source_bundle),
                dataset: Digest32::from_array(lineage.dataset),
                update_rule: Digest32::from_array(lineage.update_rule),
                evaluation_profile: Digest32::from_array(lineage.evaluation_profile),
            }),
        rollback_predecessor: data.bundle.rollback_predecessor.map(Digest32::from_array),
    };
    bundle.digest().map_err(invalid)?;
    crate::circuit_feature_initial_root::require_feature(
        &initial.target.generation,
        &bundle,
        &model,
        &source.definition,
        &source.source,
    )?;
    Ok(OriginalDeployment {
        ledger: data.ledger,
        initial,
        source,
        model,
        bundle,
        cell: data.cell,
        inference_control: data.inference_control,
        inference_capacity: data.inference_capacity,
        worker_generation: data.worker_generation,
        maximum_cell_records: data.maximum_cell_records,
        queue_capacity: data.queue_capacity,
    })
}

fn invalid(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original Initial Q24 deployment: {message}"))
}

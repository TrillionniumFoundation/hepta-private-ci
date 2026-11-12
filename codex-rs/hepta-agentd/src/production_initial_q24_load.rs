//! Resolve the sealed first-A data to the actual pre-existing owner files.
//! Read-only Artifact discovery is checked again by the same Root Initial client.

use std::fs::File;

use codex_hepta_learning_artifacts::LearningArtifactReadViewV1;
use codex_hepta_learning_artifacts::read_dataset_withdrawal_snapshot;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::DurableInferenceControl;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use super::deployment::OriginalDeployment;
use super::files::OriginalFiles;
use super::files::require_unwritten;
use crate::AgentdError;
use crate::AgentdGenerationSelectionFilesV1;
use crate::AgentdIdentity;
use crate::CircuitQ24TaskFilesV1;
use crate::RootArtifactPublicationInputsV1;
use crate::RootGenerationJournalInputsV1;

pub(super) struct OriginalInputs {
    pub(super) data: OriginalDeployment,
    pub(super) target: RootGenerationJournalInputsV1,
    pub(super) artifacts: RootArtifactPublicationInputsV1,
    pub(super) task: CircuitQ24TaskFilesV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
}

pub(super) fn open(
    deployment: File,
    identity: &AgentdIdentity,
    now: u64,
) -> Result<OriginalInputs, AgentdError> {
    let mut files = OriginalFiles::new()?;
    let data = super::deployment::read(deployment, identity, &mut files)?;
    super::clock::require_source_deadline(&data.source.source)?;
    let initial = &data.initial;
    let withdrawal_floor = read_dataset_withdrawal_snapshot(
        files.read(&initial.withdrawal_file)?,
        initial.withdrawal_receipt,
    )
    .map_err(invalid)?;
    // Public metadata alone grants nothing. This temporary read view only
    // locates the original immutable selected bytes for the real client below.
    let reader = LearningArtifactReadViewV1::open_original(
        initial.artifact_root.clone(),
        // SAFETY: geteuid only reads this process's actual kernel credential.
        unsafe { libc::geteuid() },
        initial.trust.clone(),
        initial.retained_current.clone(),
        now,
    )
    .map_err(invalid)?
    .with_original_withdrawal_floor(initial.storage_binding, withdrawal_floor.clone())
    .map_err(invalid)?;
    let selected_paths = reader
        .locate_selected_original_files(&initial.selector, &initial.selection, now)
        .map_err(invalid)?;
    let artifacts = RootArtifactPublicationInputsV1 {
        root: initial.artifact_root.clone(),
        trust: initial.trust.clone(),
        retained_current: initial.retained_current.clone(),
        storage_binding: initial.storage_binding,
        withdrawal_floor,
        selector: initial.selector.clone(),
        signed_selection: initial.selection.clone(),
        files: AgentdGenerationSelectionFilesV1 {
            registry_snapshot: files.read(&selected_paths.0)?,
            payload: files.read(&selected_paths.1)?,
        },
    };
    if reader
        .locate_selected_original_files(&initial.selector, &initial.selection, now)
        .map_err(invalid)?
        != selected_paths
    {
        return Err(invalid("original selected files changed"));
    }
    let target = RootGenerationJournalInputsV1 {
        journal: files.write(&initial.target_journal)?,
        witness: files.write(&initial.target_witness)?,
        config: initial.target.clone(),
    };
    require_unwritten(&target.journal)?;
    if target.witness.metadata()?.len() == 0 {
        return Err(invalid("original Root Initial target witness is absent"));
    }
    let source_journal = files.write(&data.source.source_journal)?;
    let cell_journal = files.write(&data.cell.journal)?;
    let inference_file = files.append(&data.inference_control)?;
    for journal in [&source_journal, &cell_journal, &inference_file] {
        require_unwritten(journal)?;
    }
    let source_witness = FileAnchorWitnessStore::open(
        files.write(&data.source.source_witness)?,
        data.source.witness_scope,
        data.source.witness_generation,
        data.source.witness_records,
    )
    .map_err(invalid)?;
    let cell_witness = FileAnchorWitnessStore::open(
        files.write(&data.cell.witness)?,
        JournalScope {
            scope_digest: Digest32::from_array(data.cell.witness_scope),
            objective_digest: Digest32::from_array(data.cell.witness_objective),
        },
        Generation::new(data.cell.witness_generation).map_err(invalid)?,
        data.cell.witness_records,
    )
    .map_err(invalid)?;
    if source_witness.current().map_err(invalid)?.is_some()
        || cell_witness.current().map_err(invalid)?.is_some()
    {
        return Err(invalid(
            "Initial A cannot reopen earlier Source or Cell history",
        ));
    }
    let inference_control = DurableInferenceControl::open_file(
        inference_file,
        &data.inference_control,
        data.inference_capacity,
    )
    .map_err(invalid)?;
    super::clock::require_source_deadline(&data.source.source)?;
    Ok(OriginalInputs {
        data,
        target,
        artifacts,
        task: CircuitQ24TaskFilesV1 {
            source_journal,
            source_witness,
            cell_journal,
            cell_witness,
            inference_control,
        },
    })
}

fn invalid(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original Initial Q24 inputs: {message}"))
}

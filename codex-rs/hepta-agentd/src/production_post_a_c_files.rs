//! All C files must exist before opening their explicit new owners. The
//! predecessor and target locations come only from the same sealed Root offer.

use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationObserverConfigV1;
use codex_hepta_neuron::DurableInferenceControl;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;

use super::super::OriginalFiles;
use super::super::refused;
use crate::AgentdError;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdGenerationUpdateTargetV1;
use crate::CircuitQ24TaskFilesV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::OriginalQ24SuccessorExecutionInputsV1;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::authority_host_runtime::PreparedPublicationData;
use crate::authority_host_runtime::publication_data::Mode;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ExecutionFilesData {
    cell_journal: PathBuf,
    cell_witness: PathBuf,
    cell_witness_scope: [u8; 32],
    cell_witness_objective: [u8; 32],
    cell_witness_generation: u64,
    cell_witness_records: usize,
    maximum_cell_records: usize,
    inference_control: PathBuf,
    inference_capacity: usize,
    worker_generation: u64,
}

impl ExecutionFilesData {
    pub(super) fn require_bounds(&self) -> Result<(), AgentdError> {
        if !(3..=16).contains(&self.maximum_cell_records)
            || !(3..=4096).contains(&self.cell_witness_records)
            || !(1..=64).contains(&self.inference_capacity)
            || self.worker_generation == 0
        {
            return Err(refused("original C resource bounds differ"));
        }
        Ok(())
    }
}

pub(super) fn open_original_new_files(
    prepared: &PreparedPublicationData,
    target: &CellGenerationObserverConfigV1,
    source: &OriginalSingleQ24SourceConfigurationV1,
    data: &ExecutionFilesData,
    files: &mut OriginalFiles,
) -> Result<
    (
        AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
        OriginalQ24SuccessorExecutionInputsV1,
    ),
    AgentdError,
> {
    data.require_bounds()?;
    require_original_paths(prepared, source, data)?;
    let fixed = &prepared.inputs;
    if !matches!(fixed.mode, Mode::Reserve) {
        return Err(refused(
            "original new C requires the explicit Root Reserve route",
        ));
    }
    let old = fixed.previous.original_observer_config()?;
    let previous = files.write(&fixed.previous_journal)?;
    let previous_witness = files.write(&fixed.previous_witness)?;
    let next = files.write(&fixed.target_journal)?;
    let next_witness = files.write(&fixed.target_witness)?;
    let source_journal = files.write(&source.source_journal)?;
    let source_witness = files.write(&source.source_witness)?;
    let cell_journal = files.write(&data.cell_journal)?;
    let cell_witness = files.write(&data.cell_witness)?;
    let inference_file = files.append(&data.inference_control)?;
    for (file, expected) in [
        (&source_journal, &prepared.successor.source_journal),
        (&source_witness, &prepared.successor.source_witness),
        (&cell_journal, &prepared.successor.cell_journal),
        (&cell_witness, &prepared.successor.cell_witness),
        (&inference_file, &prepared.successor.inference_control),
    ] {
        let physical = file.metadata()?;
        if (
            physical.dev(),
            physical.ino(),
            physical.uid(),
            physical.gid(),
            physical.mode(),
        ) != (
            expected.device,
            expected.inode,
            expected.uid,
            expected.gid,
            expected.mode,
        ) || physical.nlink() != 1
        {
            return Err(refused(
                "actual C descriptor differs from original Root custody",
            ));
        }
    }
    if previous.metadata()?.len() == 0
        || previous_witness.metadata()?.len() == 0
        || next_witness.metadata()?.len() == 0
    {
        return Err(refused(
            "original Root predecessor or target witness is absent",
        ));
    }
    for new in [
        &next,
        &source_journal,
        &source_witness,
        &cell_journal,
        &cell_witness,
        &inference_file,
    ] {
        if new.metadata()?.len() != 0 {
            return Err(refused("new C cannot replace earlier original history"));
        }
    }
    let previous_witness = FileAnchorWitnessStore::open(
        previous_witness,
        old.witness_scope,
        old.witness_generation,
        old.witness_records,
    )
    .map_err(refused)?;
    let next_witness = FileAnchorWitnessStore::open(
        next_witness,
        target.witness_scope,
        target.witness_generation,
        target.witness_records,
    )
    .map_err(refused)?;
    let source_witness = FileAnchorWitnessStore::open(
        source_witness,
        source.witness_scope,
        source.witness_generation,
        source.witness_records,
    )
    .map_err(refused)?;
    let cell_witness = FileAnchorWitnessStore::open(
        cell_witness,
        JournalScope {
            scope_digest: Digest32::from_array(data.cell_witness_scope),
            objective_digest: Digest32::from_array(data.cell_witness_objective),
        },
        Generation::new(data.cell_witness_generation).map_err(refused)?,
        data.cell_witness_records,
    )
    .map_err(refused)?;
    if previous_witness.current().map_err(refused)?.is_none()
        || next_witness.current().map_err(refused)?.is_some()
        || source_witness.current().map_err(refused)?.is_some()
        || cell_witness.current().map_err(refused)?.is_some()
    {
        return Err(refused(
            "original C predecessor or new witness history differs",
        ));
    }
    let inference_control = DurableInferenceControl::open_file(
        inference_file,
        &data.inference_control,
        data.inference_capacity,
    )
    .map_err(refused)?;
    Ok((
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: previous,
            witness: previous_witness,
            config: old.generation,
            max_records: old.journal_records,
        },
        AgentdGenerationUpdateTargetV1 {
            file: next,
            witness: next_witness,
            config: target.generation.clone(),
            max_records: target.journal_records,
        },
        OriginalQ24SuccessorExecutionInputsV1 {
            files: CircuitQ24TaskFilesV1 {
                source_journal,
                source_witness,
                cell_journal,
                cell_witness,
                inference_control,
            },
            source_mode: CircuitQ24TaskOpenModeV1::Create,
            fence: source.fence.clone(),
            circuit: source.circuit.clone(),
            routes: source.routes.clone(),
            worker_generation: data.worker_generation,
            maximum_cell_records: data.maximum_cell_records,
            clock: Arc::new(super::super::super::initial_q24::clock::sample),
        },
    ))
}

fn require_original_paths(
    prepared: &PreparedPublicationData,
    source: &OriginalSingleQ24SourceConfigurationV1,
    data: &ExecutionFilesData,
) -> Result<(), AgentdError> {
    let original = &prepared.successor;
    if source.source_journal != original.source_journal.path
        || source.source_witness != original.source_witness.path
        || data.cell_journal != original.cell_journal.path
        || data.cell_witness != original.cell_witness.path
        || data.inference_control != original.inference_control.path
        || data.cell_witness_scope != original.cell_witness_scope
        || data.cell_witness_objective != original.cell_witness_objective
        || data.cell_witness_generation != original.cell_witness_generation
        || data.cell_witness_records != original.cell_witness_records
        || data.maximum_cell_records != original.maximum_cell_records
        || data.inference_capacity != original.inference_capacity
        || data.worker_generation != original.worker_generation
    {
        return Err(refused(
            "C execution differs from original fixed Root input",
        ));
    }
    Ok(())
}

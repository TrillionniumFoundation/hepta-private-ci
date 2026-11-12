//! Actual independently placed witness files for deployment owners.
//! Descriptor fields only select the original scope and generation; this
//! constructor retains the real file and runs the original witness validation.

use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;

use super::deployment_error;
use super::deployment_refused;
use super::files::MutableFileData;
use super::files::OriginalDeploymentFiles;
use super::files::OriginalFileMode;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalWitnessData {
    pub file: MutableFileData,
    pub scope: [u8; 32],
    pub objective: [u8; 32],
    pub generation: u64,
    pub maximum_records: usize,
}

impl OriginalWitnessData {
    pub(super) fn open_original(
        &self,
        files: &mut OriginalDeploymentFiles,
    ) -> Result<FileAnchorWitnessStore, AgentdError> {
        let scope = JournalScope {
            scope_digest: Digest32::from_array(self.scope),
            objective_digest: Digest32::from_array(self.objective),
        };
        let generation = Generation::new(self.generation).map_err(deployment_error)?;
        let file = files.open_original_owner(&self.file)?;
        files.require_original_context()?;
        let witness = FileAnchorWitnessStore::open(
            file, scope, generation, self.maximum_records,
        )
        .map_err(deployment_error)?;
        files.require_original_context()?;
        Ok(witness)
    }
}

pub(super) fn require_fresh_original_file(input: &MutableFileData) -> Result<(), AgentdError> {
    if matches!(input.mode, OriginalFileMode::Recover) {
        return Err(deployment_refused(
            "this fresh Learning owner cannot use recovery data or reset its trust history",
        ));
    }
    Ok(())
}

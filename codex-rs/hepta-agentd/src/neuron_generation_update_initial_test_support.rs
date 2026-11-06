//! Private real-file custody for first-generation tests. The initial Control
//! file is created directly as Prepared, never through a transient Active cut.
//! This fixture does not represent a production RootAuthorityDirectory.

use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;

use super::ArtifactFiles;
use super::CurrentHead;
use super::Fixture;
use super::NOW;
use super::RECORDS;
use super::super::PreparedNeuronGenerationInitialV1;
use super::super::initial::initial_head_and_prepared;

impl Fixture {
    pub(crate) fn new_initial(
        config: CellGenerationConfigV2,
        operation_id: &str,
    ) -> anyhow::Result<Self> {
        Self::create(config.clone(), config, Some(operation_id))
    }

    pub(crate) fn initial_prepared(
        &self,
        operation_id: &str,
    ) -> anyhow::Result<PreparedNeuronGenerationInitialV1> {
        let selected = self.selection()?;
        let binding = CellGenerationOwnerBindingV1::new(&self.target_config, RECORDS)?;
        let (_, expected) = initial_head_and_prepared(operation_id.into(), binding, &selected)?;
        Ok(self.current.recover_initial_operation(operation_id, expected.intent_digest())?)
    }
}

pub(super) fn current_head(
    old: &CellGenerationConfigV2,
    target: &CellGenerationConfigV2,
    artifacts: &ArtifactFiles,
    initial_operation: Option<&str>,
) -> anyhow::Result<CurrentHead> {
    if let Some(operation) = initial_operation {
        let selected = artifacts.selection(NOW)?;
        let binding = CellGenerationOwnerBindingV1::new(target, RECORDS)?;
        let (head, _) = initial_head_and_prepared(operation.into(), binding, &selected)?;
        Ok(head)
    } else {
        Ok(CurrentHead {
            schema_version: 1,
            current: CellGenerationOwnerBindingV1::new(old, RECORDS)?,
            prepared: None,
            published: None,
            initial: None,
        })
    }
}

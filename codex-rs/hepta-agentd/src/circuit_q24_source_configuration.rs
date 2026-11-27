//! The complete single-Q24 Source preimage shared by the original Root and A.
//! This data carries no descriptor, execution receipt, live guard or authority.

use std::path::PathBuf;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;

use crate::AgentdError;
use crate::CircuitCellBindingV1;
use crate::CircuitCellRegistryV1;
use crate::CircuitCellRouteV1;
use crate::CircuitTaskSourceInputV1;

pub(crate) struct OriginalSingleQ24SourceConfigurationV1 {
    pub(crate) source_journal: PathBuf,
    pub(crate) source_witness: PathBuf,
    pub(crate) witness_scope: JournalScope,
    pub(crate) witness_generation: Generation,
    pub(crate) witness_records: usize,
    pub(crate) fence: TaskFlowFence,
    pub(crate) circuit: BoundedCircuitDefinitionV2,
    pub(crate) routes: Vec<CircuitCellRouteV1>,
    pub(crate) definition: CellDefinitionV1,
    pub(crate) source: CircuitTaskSourceInputV1,
}

impl OriginalSingleQ24SourceConfigurationV1 {
    pub(crate) fn registry(&self) -> Result<CircuitCellRegistryV1, AgentdError> {
        let program = self
            .circuit
            .programs
            .iter()
            .find(|program| program.program_id == self.circuit.entry_program)
            .ok_or_else(|| {
                AgentdError::Invalid("single Q24 Source entry program missing".into())
            })?;
        let binding = CircuitCellBindingV1 {
            program_id: program.program_id.clone(),
            node_id: program.entry_node.clone(),
            cell: self.definition.clone(),
            routes: self.routes.clone(),
        };
        CircuitCellRegistryV1::new(self.circuit.clone(), vec![binding])
            .map_err(|error| AgentdError::Invalid(error.to_string()))
    }
}

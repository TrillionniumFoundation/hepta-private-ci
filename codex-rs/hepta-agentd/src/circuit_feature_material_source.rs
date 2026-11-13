//! A same-task, same-Cell read for the original Material Source loan. Unlike
//! retirement this performs no drain, mutation or admission.

use super::*;

impl PublishedCircuitFeatureTaskV1 {
    pub(crate) fn read_original_material_publication<CW: AnchorWitnessStore, SW: AnchorWitnessStore>(
        &self, cell: &PublishedCircuitCellOwnerV1<CW>, source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity, run: &StableId,
    ) -> Result<CircuitTaskSourcePublicationV1, AgentdError> {
        if !Arc::ptr_eq(&self.0, &cell.task.0) || run != &self.source().scope.run_id {
            return Err(invalid("Material Source belongs to a different original task"));
        }
        self.require_current()?;
        let observed = source.read_run_publication(identity, run).map_err(invalid)?;
        let decision = cell.committed(&observed)?;
        if source.read_run_publication(identity, run).map_err(invalid)? != observed
            || cell.committed(&observed)? != decision
        { return Err(invalid("original Material Source or Cell changed")); }
        self.require_current()?;
        Ok(observed)
    }
}

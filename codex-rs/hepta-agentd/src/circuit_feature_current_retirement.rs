//! Explicit retirement belongs to the original publication host. A read-only
//! Cell/Observer handle cannot acquire this durable version mutation capability.

use super::*;

impl PublishedCircuitFeatureTaskV1 {
    /// Close this exact original task only after actual source and private Cell
    /// completion. Durable drain is never a manufactured model STOP.
    pub fn drain_completed_task<CW: AnchorWitnessStore, SW: AnchorWitnessStore>(&self,
        cell: &PublishedCircuitCellOwnerV1<CW>, source: &CircuitTaskSourceReadbackV1<SW>, identity: &AgentdIdentity)
        -> Result<PublishedCircuitFeatureCompletionV1, AgentdError> {
        if !Arc::ptr_eq(&self.0, &cell.task.0) { return Err(invalid("Feature retirement belongs to a different owner")); }
        let before = source.read_run_publication(identity, &self.source().scope.run_id).map_err(invalid)?;
        let receipt = cell.committed(&before)?;
        if source.read_run_publication(identity, &self.source().scope.run_id).map_err(invalid)? != before {
            return Err(invalid("original Feature source changed before drain"));
        }
        let mut original = self.0.original.lock().map_err(invalid)?;
        original.require_current()?;
        original.drain()?;
        if !original.is_drained()? { return Err(invalid("original task drain is uncertain")); }
        drop(original);
        if source.read_run_publication(identity, &self.source().scope.run_id).map_err(invalid)? != before {
            return Err(invalid("original Feature source changed across drain"));
        }
        self.require_current()?;
        Ok(PublishedCircuitFeatureCompletionV1 { binding: self.0.publication.target().clone(),
            manifest: self.0.manifest.clone(), source: before, receipt })
    }
}

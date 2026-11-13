//! Fixed pre-freeze read from the original published task. The request contains
//! only pre-task material. Full RunStart/request/result bytes are read from the
//! existing Source and its same-Arc Cell, never reconstructed from a report.

use super::*;
use crate::OriginalCircuitPrefreezeSourceRequestV1;

impl<SW: AnchorWitnessStore, CW: AnchorWitnessStore> OriginalRootCircuitTaskCustodyV1<SW, CW> {
    /// This cold-path observation never waits for a future event when the
    /// original journals already contain completion. Only the original typed
    /// Missing/Pending result is eligible for the later one-shot wait.
    pub(crate) fn original_prefreeze_is_pending(
        &self, request: &OriginalCircuitPrefreezeSourceRequestV1,
    ) -> Result<bool, AgentdError> {
        self.require_original_prefreeze_task(request)?;
        let observed = self.source.read_run_publication(&self.identity, &request.source.scope.run_id);
        match observed {
            Ok(_) => { self.read_original_prefreeze_source(request)?; Ok(false) }
            Err(crate::CircuitTaskErrorV1::ReconciliationRequired) => {
                self.require_original_prefreeze_task(request)?;
                Ok(true)
            }
            Err(error) => Err(invalid(error)),
        }
    }

    pub(crate) fn require_original_completed_source(&self) -> Result<(), AgentdError> {
        require_root()?;
        self.read_original_operation()?;
        self.source.require_original_input(&self.identity, self.task.source()).map_err(invalid)?;
        self.task.read_original_material_publication(
            &self.cell, &self.source, &self.identity, &self.task.source().scope.run_id,
        )?;
        self.read_original_operation()?;
        Ok(())
    }

    pub(crate) fn read_original_prefreeze_source(
        &self, request: &OriginalCircuitPrefreezeSourceRequestV1,
    ) -> Result<Vec<u8>, AgentdError> {
        self.require_original_prefreeze_task(request)?;
        let run = &request.source.scope.run_id;
        let observed = self.task.read_original_material_publication(
            &self.cell, &self.source, &self.identity, run,
        )?;
        request.require_publication(&observed).map_err(invalid)?;
        // This existing encoder recomputes and compares the complete original
        // request frame and saved input/result under the actual Source lock.
        let payload = self.source.encode_original_material_publication(&self.identity, &observed)
            .map_err(invalid)?;
        if self.task.read_original_material_publication(
            &self.cell, &self.source, &self.identity, run,
        )? != observed { return Err(invalid("the pre-freeze original Source changed")); }
        self.read_original_operation()?;
        Ok(payload)
    }

    fn require_original_prefreeze_task(
        &self, request: &OriginalCircuitPrefreezeSourceRequestV1,
    ) -> Result<(), AgentdError> {
        require_root()?;
        self.read_original_operation()?;
        if self.operation.recovery.operation_id != request.generation_operation_id
            || self.operation.recovery.intent_digest != request.generation_intent_digest
            || self.task.source() != &request.source
            || crate::circuit_feature_task_digest_v1(self.task.definition(), self.task.source())?
                != request.task_digest
        { return Err(invalid("pre-freeze disclosure differs from the original task custody")); }
        self.source.require_original_input(&self.identity, &request.source).map_err(invalid)
    }
}

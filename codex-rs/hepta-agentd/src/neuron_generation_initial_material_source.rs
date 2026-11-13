//! Read only the factory's retained original Source and same-Arc Cell. The
//! result is bounded data; no caller can obtain a Source/Cell/current writer.

use super::*;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;

impl<SW: AnchorWitnessStore, CW: AnchorWitnessStore> OriginalRootCircuitTaskCustodyV1<SW, CW> {
    pub(crate) fn read_original_material_source(&self, request: &LearningIterationRequestV1) -> Result<Vec<u8>, AgentdError> {
        require_root()?;
        self.read_original_operation()?;
        let run = &request.source_run_id;
        let observed = self.task.read_original_material_publication(
            &self.cell, &self.source, &self.identity, run,
        )?;
        crate::cell_q24_dataset::require_source(&self.identity, &observed, request).map_err(invalid)?;
        let payload = self.source.encode_original_material_publication(&self.identity, &observed)
            .map_err(invalid)?;
        if self.task.read_original_material_publication(
            &self.cell, &self.source, &self.identity, run,
        )? != observed { return Err(invalid("original Material Source changed during encoding")); }
        self.read_original_operation()?;
        Ok(payload)
    }
}

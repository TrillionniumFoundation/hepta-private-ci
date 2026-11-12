//! Closed bridge to the original Initial client's live data-retention lane.

use super::*;

impl NeuronGenerationCurrentOwnerV1 {
    pub(crate) fn retain_root_initial_run_start(
        &self,
        record: &codex_hepta_learning_ledger::RunStartRecordV1,
        published: &codex_hepta_intelligence::PublishedObjectiveRunV1,
    ) -> Result<(), AgentdError> {
        self.store
            .original_initial_client()?
            .retain_live_run_start(record, published)
    }
}

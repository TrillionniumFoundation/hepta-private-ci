//! Original launch selection of the live RunStart acknowledgement. Only the
//! same Initial CURRENT connection is retained, without Source/Cell owners.

use std::sync::Arc;

use super::AgentdProductionLaunch;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::PublishedCircuitFeatureTaskV1;

pub(crate) struct OriginalInitialRunStartRetainerV1 {
    pub(crate) identity: AgentdIdentity,
    current: Arc<NeuronGenerationCurrentOwnerV1>,
}

impl AgentdProductionLaunch {
    /// Select the originally published task for its first live append. The
    /// actual publication connection checks the same Root session by Arc
    /// identity; matching public identities alone cannot install this path.
    pub fn retain_original_initial_run_start(
        &mut self,
        published: &PublishedCircuitFeatureTaskV1,
    ) -> Result<(), AgentdError> {
        if self.original_run_start_retention.is_some() {
            return Err(AgentdError::Invalid(
                "original RunStart retention was already selected".into(),
            ));
        }
        let identity = self.root.bootstrap.registered_identity.identity()?;
        let current = published.original_initial_source_current(&self.root.session, &identity)?;
        self.original_run_start_retention =
            Some(OriginalInitialRunStartRetainerV1 { identity, current });
        Ok(())
    }
}

impl OriginalInitialRunStartRetainerV1 {
    pub(crate) async fn retain_live_append(
        &self,
        record: codex_hepta_learning_ledger::RunStartRecordV1,
        published: codex_hepta_intelligence::PublishedObjectiveRunV1,
    ) -> Result<(), AgentdError> {
        let current = Arc::clone(&self.current);
        tokio::task::spawn_blocking(move || {
            current.retain_root_initial_run_start(&record, &published)
        })
        .await
        .map_err(|error| {
            AgentdError::GenerationFenced(format!(
                "original RunStart retention worker is uncertain: {error}"
            ))
        })?
    }
}

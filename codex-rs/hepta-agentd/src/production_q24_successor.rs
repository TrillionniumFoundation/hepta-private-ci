//! Select the waiting service from the real launch, after original retained-A
//! learning assembly and before the ordinary daemon consumes that bootstrap.

use super::*;
use crate::root_production_inputs::OriginalQ24SuccessorSession;

impl AgentdProductionLaunch {
    pub async fn prepare_original_q24_successor(
        self,
        config: AgentdConfig,
        queue_capacity: usize,
    ) -> Result<(Self, AgentdConfig, crate::OriginalQ24SuccessorHandoffV1), AgentdError> {
        config.require_root_learning_assembled()?;
        if self.q24_model.is_some() || self.initial_publication.is_some() {
            return Err(AgentdError::Invalid(
                "successor requires assembled learning and the update purpose".into(),
            ));
        }
        let session = Arc::new(
            OriginalQ24SuccessorSession::capture_original_successor_session(
                &self.root.session,
                &self.root.bootstrap,
                config.identity(),
            )?,
        );
        let (config, handoff) = config
            .with_original_pending_successor(session, queue_capacity)
            .await?;
        Ok((self, config, handoff))
    }
}

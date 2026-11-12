//! The original launch retains only its Initial CURRENT connection for the
//! post-runtime data handoff. The Source writer and State must already be gone.

use super::AgentdProductionLaunch;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::circuit_task::OriginalCircuitSourceClosedV1;
use std::sync::Arc;

pub(crate) struct OriginalSourceCaptureRequestV1 {
    pub(crate) identity: AgentdIdentity,
    current: Arc<NeuronGenerationCurrentOwnerV1>,
}

impl AgentdProductionLaunch {
    /// Select the same originally published task before installing its runtime.
    /// This retains no Cell/Source writer and sends no capture request yet.
    pub fn retain_original_initial_source_capture(
        &mut self,
        published: &PublishedCircuitFeatureTaskV1,
    ) -> Result<(), AgentdError> {
        if self.original_source_capture.is_some() {
            return Err(AgentdError::Invalid(
                "original Source capture was already selected".into(),
            ));
        }
        let identity = self.root.bootstrap.registered_identity.identity()?;
        let current = published.original_initial_source_current(&self.root.session, &identity)?;
        self.original_source_capture = Some(OriginalSourceCaptureRequestV1 { identity, current });
        Ok(())
    }
}

impl OriginalSourceCaptureRequestV1 {
    pub(crate) async fn capture_after_close(
        self,
        closed: OriginalCircuitSourceClosedV1,
    ) -> Result<(), AgentdError> {
        // Keep the runtime's executor free for the original Root observation
        // feed. The original descriptor and deadline bound this one worker;
        // its result is joined before the launch releases that Root session.
        tokio::task::spawn_blocking(move || self.current.capture_original_initial_source(closed))
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("original Source capture worker failed: {error}"))
            })?
    }
}

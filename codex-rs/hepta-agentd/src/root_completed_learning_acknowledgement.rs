//! A received fresh acceptance remains bound to its actual Root connection.
//! Reading this DATA sends no Accept request and no historical read frame.

use super::*;

impl OriginalCompletedLearningAcknowledgementV1 {
    pub(crate) fn data(&self) -> &OriginalQ24TerminalAcceptanceDataV1 {
        &self.data
    }

    pub(crate) fn require_original_current(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        let mut fence = FenceReadOnDrop {
            client: &self.client,
            armed: true,
        };
        self.client.require_completed_identity(identity)?;
        if identity != &self.identity {
            return Err(AgentdError::Io(refused()));
        }
        let result = self.data.validate_data().map_err(AgentdError::Protocol);
        let after = self.client.require_completed_identity(identity);
        after?;
        result?;
        fence.armed = false;
        Ok(())
    }
}

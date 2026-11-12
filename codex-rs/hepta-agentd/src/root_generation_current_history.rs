//! Match a historical A receipt to this actual CURRENT connection. Equal
//! public identities or profile bytes cannot replace the shared live verifier.

use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;

use super::*;

impl RootGenerationCurrentClient {
    pub(crate) fn require_original_historical_receipt(
        &self,
        original: &OriginalHistoricalTaskReadReceiptV1,
    ) -> Result<(), AgentdError> {
        let result = (|| {
            OriginalHistoricalTaskReadReceiptV1::require_original_publication_connection(
                original,
                &self.connection,
            )?;
            self.observe()?;
            let initial = original.initial_snapshot();
            if self.profile.initial != initial.head_digest.to_string()
                || self.profile.learning_operation != initial.request.operation_id.as_str()
            {
                return Err(uncertain());
            }
            OriginalHistoricalTaskReadReceiptV1::require_original_publication_connection(
                original,
                &self.connection,
            )
        })();
        if result.is_err() {
            self.fence();
        }
        result
    }
}

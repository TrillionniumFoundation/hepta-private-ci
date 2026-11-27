//! Match a historical A receipt to this actual CURRENT connection. Equal
//! public identities or profile bytes cannot replace the shared live verifier.

use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;

use super::*;

impl RootGenerationCurrentClient {
    pub(crate) fn read_original_recovery_intent(
        &self,
        original: &OriginalHistoricalTaskReadReceiptV1,
    ) -> Result<codex_hepta_types::Digest32, AgentdError> {
        let result = (|| {
            self.require_original_historical_receipt(original)?;
            if self.version != PublicationVersion::DurableV2 {
                return Err(uncertain());
            }
            let before = self.observe()?;
            let published = before.published.as_ref().ok_or_else(uncertain)?;
            if before.current != self.profile.intent.target
                || before.prepared.is_some()
                || published.intent != self.profile.intent
            {
                return Err(uncertain());
            }
            let digest = published.intent.digest()?;
            if digest.is_zero() || self.observe()? != before {
                return Err(uncertain());
            }
            self.require_original_historical_receipt(original)?;
            Ok(digest)
        })();
        if result.is_err() {
            self.fence();
        }
        result
    }

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

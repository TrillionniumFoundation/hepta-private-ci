//! Revalidate the original dispatch event under the entry barrier's held lock.

use super::*;

impl LocalLeaseOutbox {
    pub(crate) async fn require_dispatch_entry_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        occurrence_key: &str,
        dispatch_event_id: &str,
        operation_digest: &Sha256Digest,
    ) -> Result<(), LocalLeaseOutboxError> {
        self.require_current_transaction(transaction).await?;
        let event = latest_occurrence_event(
            transaction,
            &self.lease_id,
            occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| LocalLeaseOutboxError::StaleFence("dispatch event is absent".to_string()))?;
        if event.event_id != dispatch_event_id
            || event.kind != "indeterminate"
            || event.generation != self.generation
            || event.fencing_token != self.fencing_token
            || event.payload_json
                != format!("dispatch_started_pending_ack:{}", operation_digest.as_str())
        {
            return Err(LocalLeaseOutboxError::StaleFence(
                "dispatch event is no longer the exact current pending entry".to_string(),
            ));
        }
        Ok(())
    }
}

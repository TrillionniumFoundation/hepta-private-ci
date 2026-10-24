//! Exact terminal evidence for the original production publication path.
use super::*;

impl LocalLeaseOutbox {
    /// Publication-only check for the exact terminal row just returned to its
    /// sole production writer. This never makes a terminal handle active and
    /// is not used by enqueue, claim, entry or ordinary currentness checks.
    pub(crate) async fn require_terminal_publication_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        expected: &LocalLease,
    ) -> Result<LocalLease, LocalLeaseOutboxError> {
        if self.binding().is_none()
            || !matches!(expected.state, LocalLeaseState::Released | LocalLeaseState::RolledBack)
        {
            return Err(LocalLeaseOutboxError::Invalid("bound terminal publication required".into()));
        }
        let lease = self.current_lease(transaction).await?;
        if lease != *expected {
            return Err(LocalLeaseOutboxError::StaleFence("terminal publication head changed".into()));
        }
        ensure_current_handle_fields(&lease, self)?;
        let expiry = lease.lease_expires_at_unix_seconds.ok_or_else(||
            LocalLeaseOutboxError::Invalid("terminal publication requires expiry".into()))?;
        if u64::try_from(now_unix_seconds()?).map_err(|_| LocalLeaseOutboxError::Clock("clock before Unix epoch".into()))? >= expiry {
            return Err(LocalLeaseOutboxError::StaleFence("terminal publication authority expired".into()));
        }
        let events = verify_event_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox = verify_outbox_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox)?;
        ensure_no_unresolved_outcomes(&events, self.generation, &self.fencing_token)?;
        verify_operation_ledger(transaction, &self.lease_id, &self.owner_agent_id, &events, &outbox).await?;
        self.verify_bound_compact_journals(transaction).await?;
        Ok(lease)
    }

}

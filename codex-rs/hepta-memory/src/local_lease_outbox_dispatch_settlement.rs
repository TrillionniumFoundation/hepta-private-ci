//! Same-result ACK/observer races without weakening semantic receipt replay.

use super::*;

impl LocalLeaseOutbox {
    pub(crate) async fn settle_dispatch_terminal(
        &self,
        occurrence_key: &str,
        state: LocalOutcomeState,
        payload: &str,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        let kind = match state {
            LocalOutcomeState::Committed => "reconcile_committed",
            LocalOutcomeState::Rejected => "reconcile_rejected",
            LocalOutcomeState::Queued
            | LocalOutcomeState::Indeterminate
            | LocalOutcomeState::RolledBack => {
                return Err(LocalLeaseOutboxError::Invalid(
                    "dispatch settlement requires a terminal result".to_string(),
                ));
            }
        };
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let receipt = match self
            .append_outcome_in_transaction(
                &mut transaction,
                occurrence_key.to_string(),
                kind,
                payload.to_string(),
                &[LocalOutcomeState::Queued, LocalOutcomeState::Indeterminate],
                state,
                /*allow_exact_replay*/ true,
            )
            .await
        {
            Ok(receipt) => receipt,
            Err(error @ LocalLeaseOutboxError::IllegalTransition(_)) => {
                // The only additional replay accepted here is a canonical
                // terminal observer event for this same outcome. Generic
                // apply/apply_in_transaction retain exact-payload replay.
                let lease = self.current_lease(&mut transaction).await?;
                ensure_current_active(&lease, self)?;
                let admission = find_admission(
                    &mut transaction,
                    &self.lease_id,
                    occurrence_key,
                    &self.owner_agent_id,
                )
                .await?
                .ok_or_else(|| corrupt("dispatch settlement admission is missing"))?;
                let outbox = find_outbox(
                    &mut transaction,
                    &self.lease_id,
                    occurrence_key,
                    &self.owner_agent_id,
                )
                .await?
                .ok_or_else(|| corrupt("dispatch settlement outbox is missing"))?;
                verify_occurrence_pair_incremental(
                    &self.lease_id,
                    &self.owner_agent_id,
                    &admission,
                    &outbox,
                )?;
                ensure_current_occurrence_fence(self, &admission, &outbox)?;
                let current = current_outcome(
                    &mut transaction,
                    &self.lease_id,
                    occurrence_key,
                    &self.owner_agent_id,
                )
                .await?;
                let latest = latest_occurrence_event(
                    &mut transaction,
                    &self.lease_id,
                    occurrence_key,
                    &self.owner_agent_id,
                )
                .await?
                .ok_or_else(|| corrupt("dispatch settlement terminal event is missing"))?;
                if current != state
                    || latest.kind != kind
                    || latest.payload_json != state.as_str()
                    || latest.generation != self.generation
                    || latest.fencing_token != self.fencing_token
                {
                    return Err(error);
                }
                LocalOutcomeReceipt {
                    lease_id: self.lease_id.clone(),
                    occurrence_key: occurrence_key.to_string(),
                    state,
                    event_id: latest.event_id,
                    external_effect: false,
                }
            }
            Err(error) => return Err(error),
        };
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(receipt)
    }
}

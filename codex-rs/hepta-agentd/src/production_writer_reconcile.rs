//! Original-owner recovery, with an explicit trusted destination boundary.
use super::*;

#[derive(Clone, Copy)]
enum DestinationScope<'a> {
    All,
    Fixed(&'a str),
}

impl DestinationScope<'_> {
    fn includes(self, destination: &str) -> bool {
        match self {
            Self::All => true,
            Self::Fixed(expected) => expected == destination,
        }
    }
}

impl AgentdProductionWriterHost {
    fn require_reconciliation_scope(&self, scope: DestinationScope<'_>) -> Result<(), AgentdError> {
        if let DestinationScope::Fixed(destination) = scope
            && !self.dispatchers.contains_key(destination)
        {
            return Err(AgentdError::Protocol(
                "fixed recovery destination is not attached".into(),
            ));
        }
        Ok(())
    }

    /// Bounded observer-only reconciliation. This never invokes target
    /// dispatch, so an acknowledgement-loss/restart cannot become a resend.
    pub async fn reconcile(&self, limit: usize) -> Result<usize, AgentdError> {
        self.reconcile_scope(DestinationScope::All, limit).await
    }

    /// Reconcile only this deployment-fixed destination and any old Notes
    /// receipt attached through that same current Notes recovery channel.
    pub(crate) async fn reconcile_for_destination(
        &self,
        destination: &str,
        limit: usize,
    ) -> Result<usize, AgentdError> {
        self.reconcile_scope(DestinationScope::Fixed(destination), limit)
            .await
    }

    async fn reconcile_scope(
        &self,
        scope: DestinationScope<'_>,
        limit: usize,
    ) -> Result<usize, AgentdError> {
        self.require_reconciliation_scope(scope)?;
        if !(1..=256).contains(&limit) {
            return Err(AgentdError::Protocol(
                "production operation reconcile limit must be 1..=256".to_string(),
            ));
        }
        if self.dispatchers.is_empty() {
            return Err(AgentdError::Protocol(
                "production final-use outbox dispatcher is not explicitly attached".to_string(),
            ));
        }
        let mut total = 0_usize;
        if let Some((current_destination, previous)) = &self.previous_notes
            && scope.includes(current_destination)
        {
            total += self
                .writer
                .reconcile_target_batch(previous.as_ref(), limit)
                .await?;
        }
        for dispatcher in self
            .dispatchers
            .values()
            .filter(|dispatcher| scope.includes(dispatcher.destination_id()))
        {
            if total >= limit {
                break;
            }
            total += dispatcher
                .reconcile(self.writer.as_ref(), limit - total)
                .await?;
        }
        Ok(total)
    }

    /// Retry only an internally proved pre-boundary rejection, with a fresh
    /// grant from the already attached external issuer. Source-unknown rows
    /// are absent from this discovery path and can only use `reconcile`.
    pub async fn reauthorize_pending(&self, limit: usize) -> Result<usize, AgentdError> {
        self.reauthorize_scope(DestinationScope::All, limit).await
    }

    /// Renew only internally proved pre-boundary work for a fixed destination.
    /// This selector comes from trusted composition, never an IPC request.
    pub(crate) async fn reauthorize_pending_for_destination(
        &self,
        destination: &str,
        limit: usize,
    ) -> Result<usize, AgentdError> {
        self.reauthorize_scope(DestinationScope::Fixed(destination), limit)
            .await
    }

    async fn reauthorize_scope(
        &self,
        scope: DestinationScope<'_>,
        limit: usize,
    ) -> Result<usize, AgentdError> {
        self.require_reconciliation_scope(scope)?;
        if !(1..=256).contains(&limit) {
            return Err(AgentdError::Protocol(
                "reauthorization limit must be 1..=256".to_string(),
            ));
        }
        let grants = self.grants.as_ref().ok_or_else(|| {
            AgentdError::Protocol("production grant provider is not attached".to_string())
        })?;
        let mut attempted = 0;
        for dispatcher in self
            .dispatchers
            .values()
            .filter(|dispatcher| scope.includes(dispatcher.destination_id()))
        {
            if attempted >= limit {
                break;
            }
            let receipts = self
                .writer
                .awaiting_authorization(dispatcher.destination_id(), limit - attempted)
                .await?;
            for receipt in receipts {
                attempted += 1;
                let binding = self
                    .writer
                    .final_use_binding(&receipt, dispatcher.destination_id())
                    .await?;
                // An issuer refusal does not mutate the original operation or
                // manufacture a grant. The same proof remains pending.
                let Ok(signed) = grants.signed_grant(&binding).await else {
                    continue;
                };
                match dispatcher
                    .dispatch(self.writer.as_ref(), &signed, &binding, receipt)
                    .await
                {
                    Ok(_) | Err(codex_hepta_memory::ProductionWriterError::FinalUse(_)) => {}
                    Err(codex_hepta_memory::ProductionWriterError::Local(
                        codex_hepta_memory::LocalLeaseOutboxError::StaleFence(_)
                        | codex_hepta_memory::LocalLeaseOutboxError::IllegalTransition(_),
                    ))
                    | Err(codex_hepta_memory::ProductionWriterError::StaleReceipt) => {}
                    Err(error) => return Err(error.into()),
                }
            }
        }
        Ok(attempted)
    }
}

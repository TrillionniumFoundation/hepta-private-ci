//! Native streaming entry through the configured production writer, external
//! grant provider and existing destination registry.

use codex_hepta_memory::ProductionDispatchReceipt;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionEffectEntry;
use codex_hepta_memory::ProductionEffectObservation;
use codex_hepta_memory::ProductionTargetOutcome;

use super::AgentdError;
use super::AgentdProductionWriterHost;

impl AgentdProductionWriterHost {
    /// Read an existing original operation without re-admitting it.
    pub async fn resolve_native_operation(
        &self,
        destination_id: &str,
        operation_id: &str,
    ) -> Result<ProductionDispatchRequest, AgentdError> {
        self.require_native_destination(destination_id)?;
        Ok(self
            .writer
            .resolve_operation_request(operation_id, destination_id)
            .await?)
    }

    /// The same original owner resolves the receipt, derives the exact binding,
    /// asks its configured external issuer and claims the one-shot entry.
    /// Unknown/terminal operations cannot receive a replacement dispatch.
    pub async fn begin_native_effect(
        &self,
        destination_id: &str,
        operation_id: &str,
    ) -> Result<(ProductionEffectEntry, ProductionEffectObservation), AgentdError> {
        self.require_native_destination(destination_id)?;
        let dispatcher = &self.dispatchers[destination_id];
        let grants = self.grants.as_ref().ok_or_else(|| {
            AgentdError::Protocol("production final-use grant provider is not attached".to_string())
        })?;
        let receipt = self
            .writer
            .resolve_queued_operation(operation_id, destination_id)
            .await?;
        let binding = self
            .writer
            .final_use_binding(&receipt, destination_id)
            .await?;
        let signed = grants.signed_grant(&binding).await?;
        Ok(dispatcher
            .begin_effect_entry(&self.writer, &signed, &binding, receipt)
            .await?)
    }

    /// Settle the original paired claim only from destination terminal evidence.
    /// A transport acknowledgement/start/timeout remains indeterminate.
    pub async fn settle_native_effect(
        &self,
        observation: ProductionEffectObservation,
        outcome: ProductionTargetOutcome,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        self.require_native_destination(&observation.request().operation_destination_id)?;
        Ok(self
            .writer
            .settle_effect_entry(observation, outcome)
            .await?)
    }

    /// Observer-only restart recovery using the original operation identity.
    /// This path does not request a grant, dispatch, or replace a missing row.
    pub async fn reconcile_native_effect(
        &self,
        destination_id: &str,
        operation_id: &str,
        outcome: ProductionTargetOutcome,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        self.require_native_destination(destination_id)?;
        Ok(self
            .writer
            .reconcile_observed_operation(operation_id, destination_id, outcome)
            .await?)
    }

    fn require_native_destination(&self, destination_id: &str) -> Result<(), AgentdError> {
        if !self.dispatchers.contains_key(destination_id) {
            return Err(AgentdError::Protocol(format!(
                "production destination {destination_id:?} is not registered"
            )));
        }
        Ok(())
    }
}

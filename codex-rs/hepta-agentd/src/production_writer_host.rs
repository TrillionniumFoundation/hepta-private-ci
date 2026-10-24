//! Explicit Agentd/host seam for the production durable writer.
//!
//! The host must supply an externally verified authority lease and verifier.
//! Nothing in Agentd startup installs this capability automatically; the
//! default runtime remains read-only. Destination adapters are explicitly
//! registered by stable destination id and dispatch fails closed when the
//! requested destination is absent or ambiguous.

include!("production_writer_owner.rs");

use crate::AgentdConfig;

#[path = "production_protected_config.rs"]
mod protected_config;

impl AgentdProductionOperationRuntimeConfig {
    pub fn validate_for(&self, config: &AgentdConfig) -> Result<(), AgentdError> {
        if self.authority.agent_id != config.identity().agent_id {
            return Err(AgentdError::GenerationFenced(
                "production operation authority belongs to another Agent".to_string(),
            ));
        }
        if self.lease_generation == 0
            || self.lease_id.trim().is_empty()
            || self.reconcile_interval.is_zero()
            || self.target.destination_id().is_empty()
        {
            return Err(AgentdError::Invalid(
                "production operation runtime requires a non-zero generation, non-empty lease id/destination, and non-zero reconcile interval"
                    .to_string(),
            ));
        }
        let mut destinations = BTreeMap::new();
        destinations.insert(self.target.destination_id(), ());
        for (_, target) in &self.additional_targets {
            if target.destination_id().is_empty()
                || destinations.insert(target.destination_id(), ()).is_some()
            {
                return Err(AgentdError::Invalid(
                    "production operation destinations must be non-empty and unique".to_string(),
                ));
            }
        }
        Ok(())
    }
}

impl AgentdProductionWriterHost {
    /// Open a production writer only from an independently authenticated exact
    /// current cut. No ordinary writable `CognitiveStore::open` fallback exists
    /// at this product boundary.
    pub async fn open(
        config: &AgentdConfig,
        requirement: CognitiveRecoveryRequirement<'_>,
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        lease_generation: u64,
    ) -> Result<Self, AgentdError> {
        Self::open_with_recovery(
            config,
            requirement,
            authority,
            verifier,
            lease_id,
            lease_generation,
        )
        .await
    }

    /// Recover the exact independently retained current cut and immediately
    /// bind the recovered generation to the same externally verified authority
    /// lease used by the production writer. Recovery keeps its exclusive store
    /// fence for the lifetime of the returned writer generation.
    pub async fn open_with_recovery(
        config: &AgentdConfig,
        requirement: CognitiveRecoveryRequirement<'_>,
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        lease_generation: u64,
    ) -> Result<Self, AgentdError> {
        let lease_id = lease_id.into();
        verifier
            .verify_sender_process_binding(
                &authority,
                &config.identity().agent_id,
                &lease_id,
                lease_generation,
                config.identity().spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)?;
        let store = CognitiveStore::open_with_recovery(
            &config.identity().layout,
            requirement,
            &authority,
            verifier.as_ref(),
        )
        .await
        .map_err(|error| {
            AgentdError::Protocol(format!("recover production cognitive store: {error}"))
        })?;
        Self::from_recovered_store(
            config.identity().spawn_generation,
            store,
            authority,
            verifier,
            lease_id,
            lease_generation,
        )
        .await
    }
}

//! Explicit Agentd/host seam for the production durable writer.
//!
//! The host must supply an externally verified authority lease and verifier.
//! Nothing in Agentd startup installs this capability automatically; the
//! default runtime remains read-only. A dispatcher target is likewise an
//! explicit attachment and dispatch fails closed while it is absent.

use std::fmt;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDispatchReceipt;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_memory::ProductionWriterError;

use crate::AgentdConfig;
use crate::AgentdError;

/// Externally owned grant source. Agentd asks for a grant bound to the exact
/// FinalUseBinding; it never receives or constructs the issuer signing key.
pub trait AgentdFinalUseGrantProvider: Send + Sync {
    fn signed_grant(
        &self,
        binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, AgentdError>;
}

/// Explicit runtime composition input for the production operation service.
/// Supplying this value is a product-host decision; default Agentd startup does
/// not manufacture any of these authorities.
pub struct AgentdProductionOperationRuntimeConfig {
    pub authority: ProductionAuthorityLease,
    pub verifier: Arc<dyn ProductionAuthorityVerifier>,
    pub lease_id: String,
    pub lease_generation: u64,
    pub final_use: FinalUseAuthority,
    pub target: Arc<dyn FinalUseProductionOutboxTarget>,
    pub grants: Arc<dyn AgentdFinalUseGrantProvider>,
    pub reconcile_interval: Duration,
}

impl fmt::Debug for AgentdProductionOperationRuntimeConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdProductionOperationRuntimeConfig")
            .field("authority", &self.authority)
            .field("lease_id", &self.lease_id)
            .field("lease_generation", &self.lease_generation)
            .field("destination", &self.target.destination_id())
            .field("reconcile_interval", &self.reconcile_interval)
            .finish_non_exhaustive()
    }
}

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
        {
            return Err(AgentdError::Invalid(
                "production operation runtime requires a non-zero generation, non-empty lease id, and non-zero reconcile interval"
                    .to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) async fn open(
        self,
        store: CognitiveStore,
    ) -> Result<Arc<AgentdProductionWriterHost>, AgentdError> {
        let host = AgentdProductionWriterHost::open_with_store(
            store,
            self.authority,
            self.verifier.as_ref(),
            self.lease_id,
            self.lease_generation,
        )
        .await?
        .attach_target(self.final_use, self.target, self.grants);
        Ok(Arc::new(host))
    }
}

/// Host-owned production writer handle. Constructing this value does not
/// mutate Agentd's runtime configuration; callers explicitly attach/use it.
#[derive(Clone)]
pub struct AgentdProductionWriterHost {
    writer: Arc<ProductionDurableWriter>,
    dispatcher: Option<ProductionFinalUseOutboxDispatcher>,
    grants: Option<Arc<dyn AgentdFinalUseGrantProvider>>,
}

impl fmt::Debug for AgentdProductionWriterHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdProductionWriterHost")
            .field("writer", &self.writer)
            .field("dispatcher_attached", &self.dispatcher.is_some())
            .field("grant_provider_attached", &self.grants.is_some())
            .finish()
    }
}

impl AgentdProductionWriterHost {
    /// Open the writer against Agentd's exact private cognitive store. The
    /// verifier is mandatory and runs before any lease/event/outbox mutation.
    pub async fn open<V>(
        config: &AgentdConfig,
        authority: ProductionAuthorityLease,
        verifier: &V,
        lease_id: impl Into<String>,
        lease_generation: u64,
    ) -> Result<Self, AgentdError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let store = CognitiveStore::open(&config.identity().layout)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("open production cognitive store: {error}"))
            })?;
        let writer =
            ProductionDurableWriter::open(store, authority, verifier, lease_id, lease_generation)
                .await?;
        Ok(Self {
            writer: Arc::new(writer),
            dispatcher: None,
            grants: None,
        })
    }

    /// Build a host handle around an already-open Agentd-owned store. This is
    /// useful when the runtime has already attached a CognitiveStore and keeps
    /// the same mandatory external verifier contract.
    pub async fn open_with_store<V>(
        store: CognitiveStore,
        authority: ProductionAuthorityLease,
        verifier: &V,
        lease_id: impl Into<String>,
        lease_generation: u64,
    ) -> Result<Self, ProductionWriterError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let writer =
            ProductionDurableWriter::open(store, authority, verifier, lease_id, lease_generation)
                .await?;
        Ok(Self {
            writer: Arc::new(writer),
            dispatcher: None,
            grants: None,
        })
    }

    pub fn writer(&self) -> Arc<ProductionDurableWriter> {
        Arc::clone(&self.writer)
    }

    /// Attach the provider/host target together with the kernel-owned final-use
    /// authority. Replacing either value requires a new host handle, avoiding
    /// an in-flight authority/target swap behind the writer's back.
    pub fn attach_target(
        mut self,
        final_use: FinalUseAuthority,
        target: Arc<dyn FinalUseProductionOutboxTarget>,
        grants: Arc<dyn AgentdFinalUseGrantProvider>,
    ) -> Self {
        self.dispatcher = Some(ProductionFinalUseOutboxDispatcher::attach(
            final_use, target,
        ));
        self.grants = Some(grants);
        self
    }

    pub fn has_target(&self) -> bool {
        self.dispatcher.is_some() && self.grants.is_some()
    }

    /// Product dispatch path: derive the exact final-use binding from the
    /// durable operation, ask the external grant provider for that binding,
    /// and consume it immediately at the attached target.
    pub async fn dispatch_with_grant_provider(
        &self,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        let dispatcher = self.dispatcher.as_ref().ok_or_else(|| {
            AgentdError::Protocol(
                "production final-use outbox dispatcher is not explicitly attached".to_string(),
            )
        })?;
        let grants = self.grants.as_ref().ok_or_else(|| {
            AgentdError::Protocol(
                "production final-use grant provider is not explicitly attached".to_string(),
            )
        })?;
        let binding = self
            .writer
            .final_use_binding(&receipt, dispatcher.destination_id())
            .await?;
        let signed = grants.signed_grant(&binding)?;
        Ok(dispatcher
            .dispatch(self.writer.as_ref(), &signed, &binding, receipt)
            .await?)
    }

    /// Bounded observer-only reconciliation. This never invokes target
    /// dispatch, so an acknowledgement-loss/restart cannot become a resend.
    pub async fn reconcile(&self, limit: usize) -> Result<usize, AgentdError> {
        let dispatcher = self.dispatcher.as_ref().ok_or_else(|| {
            AgentdError::Protocol(
                "production final-use outbox dispatcher is not explicitly attached".to_string(),
            )
        })?;
        Ok(dispatcher.reconcile(self.writer.as_ref(), limit).await?)
    }

    pub async fn dispatch(
        &self,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        let dispatcher = self.dispatcher.as_ref().ok_or_else(|| {
            AgentdError::Protocol(
                "production final-use outbox dispatcher is not explicitly attached".to_string(),
            )
        })?;
        Ok(dispatcher
            .dispatch(self.writer.as_ref(), signed, expected, receipt)
            .await?)
    }
}

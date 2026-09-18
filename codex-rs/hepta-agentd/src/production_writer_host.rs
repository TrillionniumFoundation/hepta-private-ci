//! Explicit Agentd/host seam for the production durable writer.
//!
//! The host must supply an externally verified authority lease and verifier.
//! Nothing in Agentd startup installs this capability automatically; the
//! default runtime remains read-only. A dispatcher target is likewise an
//! explicit attachment and dispatch fails closed while it is absent.

use std::fmt;
use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::ProductionDispatchReceipt;
use codex_hepta_cognitive_store::ProductionDurableWriter;
use codex_hepta_cognitive_store::ProductionOutboxDispatcher;
use codex_hepta_cognitive_store::ProductionOutboxTarget;
use codex_hepta_cognitive_store::ProductionQueuedReceipt;
use codex_hepta_cognitive_store::ProductionWriterError;

use crate::AgentdConfig;
use crate::AgentdError;

/// Host-owned production writer handle. Constructing this value does not
/// mutate Agentd's runtime configuration; callers explicitly attach/use it.
#[derive(Clone)]
pub struct AgentdProductionWriterHost {
    writer: Arc<ProductionDurableWriter>,
    dispatcher: Option<ProductionOutboxDispatcher>,
}

impl fmt::Debug for AgentdProductionWriterHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdProductionWriterHost")
            .field("writer", &self.writer)
            .field("dispatcher_attached", &self.dispatcher.is_some())
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
        })
    }

    pub fn writer(&self) -> Arc<ProductionDurableWriter> {
        Arc::clone(&self.writer)
    }

    /// Attach the provider/host target explicitly. Replacing a target is
    /// allowed only through a new host handle, avoiding an in-flight target
    /// swap behind the writer's back.
    pub fn attach_target(mut self, target: Arc<dyn ProductionOutboxTarget>) -> Self {
        self.dispatcher = Some(ProductionOutboxDispatcher::attach(target));
        self
    }

    pub fn has_target(&self) -> bool {
        self.dispatcher.is_some()
    }

    pub async fn dispatch(
        &self,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        let dispatcher = self.dispatcher.as_ref().ok_or_else(|| {
            AgentdError::Protocol(
                "production outbox dispatcher is not explicitly attached".to_string(),
            )
        })?;
        Ok(dispatcher.dispatch(self.writer.as_ref(), receipt).await?)
    }
}

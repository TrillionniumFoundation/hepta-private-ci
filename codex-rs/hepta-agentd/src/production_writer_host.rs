//! Explicit Agentd/host seam for the production durable writer.
//!
//! The host must supply an externally verified authority lease and verifier.
//! Nothing in Agentd startup installs this capability automatically; the
//! default runtime remains read-only. A dispatcher target is likewise an
//! explicit attachment and dispatch fails closed while it is absent.
//!
//! Production store ownership is intentionally composed through
//! `codex_hepta_cognitive_store::ProductionCognitiveStore`. `hepta-memory`
//! remains the durability engine, not a second product-facing cognitive-store
//! authority.

use std::fmt;
use std::sync::Arc;

use codex_hepta_cognitive_store::ProductionCognitiveStore;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDispatchReceipt;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionOutboxDispatcher;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_memory::ProductionWriterError;

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
    ///
    /// This is the canonical product path: the durable backend is opened by the
    /// `cognitive.store` owner façade and never handed back to Agentd.
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
        let store = ProductionCognitiveStore::open(&config.identity().layout)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("open authoritative cognitive store: {error}"))
            })?;
        let writer = store
            .open_writer(authority, verifier, lease_id, lease_generation)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("open production cognitive writer: {error}"))
            })?;
        Ok(Self {
            writer: Arc::new(writer),
            dispatcher: None,
        })
    }

    /// Build a host handle around an already-open Agentd-owned store.
    ///
    /// This remains an explicitly registered qualification boundary for the H4
    /// persistent-writer fixtures. It has no product callers. Product
    /// composition must use [`Self::open`] so a raw backend cannot become an
    /// alternate authority seam.
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

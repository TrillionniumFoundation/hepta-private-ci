//! Explicit Agentd/host seam for the production durable writer.
//!
//! The host must supply an externally verified authority lease and verifier.
//! Nothing in Agentd startup installs this capability automatically; the
//! default runtime remains read-only. A dispatcher target is likewise an
//! explicit attachment and dispatch fails closed while it is absent.

use std::fmt;
use std::sync::Arc;

use codex_hepta_cognitive_store::CognitiveAccess;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::CognitiveWriteReceipt;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::ForgetMemoryDraft;
use codex_hepta_cognitive_store::KgFactSetDraft;
use codex_hepta_cognitive_store::MemoryDraft;
use codex_hepta_cognitive_store::MemoryRevisionDraft;
use codex_hepta_cognitive_store::SourceDraft;
use codex_hepta_cognitive_store::StableMemoryId;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::ProductionCognitiveMutation;
use codex_hepta_cognitive_store::ProductionCognitiveMutationFuture;
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
        let writer = ProductionDurableWriter::open_with_live_verifier(
            store,
            authority,
            verifier,
            lease_id,
            lease_generation,
        )
        .await?;
        Ok(Self {
            writer: Arc::new(writer),
            dispatcher: None,
        })
    }

    /// Qualification-only compatibility seam around an already-open store.
    /// It does not retain the verifier, so production semantic mutation methods
    /// below reject this handle with `LiveVerifierRequired`.
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

    pub async fn remember_with_kg(
        &self,
        access: &CognitiveAccess,
        source: &SourceDraft,
        draft: &MemoryDraft,
        facts: &KgFactSetDraft,
    ) -> Result<CognitiveWriteReceipt, AgentdError> {
        self.writer.verify_current_authority().await?;
        Ok(self
            .writer
            .store()
            .remember_with_kg(access, source, draft, facts)
            .await?)
    }

    pub async fn correct_with_kg(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &MemoryRevisionDraft,
        facts: &KgFactSetDraft,
    ) -> Result<CognitiveWriteReceipt, AgentdError> {
        self.writer.verify_current_authority().await?;
        Ok(self
            .writer
            .store()
            .correct_with_kg(
                access,
                memory_id,
                expected_revision,
                source,
                draft,
                facts,
            )
            .await?)
    }

    pub async fn forget_with_kg(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &ForgetMemoryDraft,
    ) -> Result<CognitiveWriteReceipt, AgentdError> {
        self.writer.verify_current_authority().await?;
        Ok(self
            .writer
            .store()
            .forget_with_kg(access, memory_id, expected_revision, source, draft)
            .await?)
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

impl ProductionCognitiveMutation for AgentdProductionWriterHost {
    fn owner_agent_id(&self) -> &codex_hepta_contracts::AgentId {
        self.writer.store().owner_agent_id()
    }

    fn remember_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        source: &'a SourceDraft,
        draft: &'a MemoryDraft,
        facts: &'a KgFactSetDraft,
    ) -> ProductionCognitiveMutationFuture<'a> {
        Box::pin(async move {
            self.writer.verify_current_authority().await?;
            Ok(self.writer.store().remember_with_kg(access, source, draft, facts).await?)
        })
    }

    fn correct_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        memory_id: &'a StableMemoryId,
        expected_revision: u64,
        source: &'a SourceDraft,
        draft: &'a MemoryRevisionDraft,
        facts: &'a KgFactSetDraft,
    ) -> ProductionCognitiveMutationFuture<'a> {
        Box::pin(async move {
            self.writer.verify_current_authority().await?;
            Ok(self.writer.store().correct_with_kg(
                access, memory_id, expected_revision, source, draft, facts,
            ).await?)
        })
    }

    fn forget_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        memory_id: &'a StableMemoryId,
        expected_revision: u64,
        source: &'a SourceDraft,
        draft: &'a ForgetMemoryDraft,
    ) -> ProductionCognitiveMutationFuture<'a> {
        Box::pin(async move {
            self.writer.verify_current_authority().await?;
            Ok(self.writer.store().forget_with_kg(
                access, memory_id, expected_revision, source, draft,
            ).await?)
        })
    }
}

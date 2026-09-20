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
use codex_hepta_cognitive_store::ProductionCognitiveMutationCapability;
use codex_hepta_cognitive_store::ProductionDispatchReceipt;
use codex_hepta_cognitive_store::ProductionDurableWriter;
use codex_hepta_cognitive_store::ProductionOutboxDispatcher;
use codex_hepta_cognitive_store::ProductionOutboxTarget;
use codex_hepta_cognitive_store::ProductionQueuedReceipt;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_cognitive_store::ProductionWriterError;

use crate::AgentdConfig;
use crate::AgentdError;

/// Host-owned production writer handle. Constructing this value does not
/// mutate Agentd's runtime configuration; callers explicitly attach/use it.
#[derive(Clone)]
pub struct AgentdProductionWriterHost {
    writer: Arc<ProductionDurableWriter>,
    // Private read-side clone of the exact recovered generation. Runtime
    // composition can reuse the same fenced owner without reopening by path or
    // exposing ProductionDurableWriter's crate-private raw-store handle.
    cognitive_runtime: codex_hepta_memory::CognitiveRuntime,
    mutation: Option<Arc<ProductionCognitiveMutationCapability>>,
    dispatcher: Option<ProductionOutboxDispatcher>,
}

impl fmt::Debug for AgentdProductionWriterHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdProductionWriterHost")
            .field("writer", &self.writer)
            .field(
                "cognitive_runtime_available",
                &self.cognitive_runtime.available_store().is_some(),
            )
            .field("production_mutation_attached", &self.mutation.is_some())
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
        let runtime_store = store.clone();
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                authority,
                verifier,
                lease_id,
                lease_generation,
            )
            .await?,
        );
        let mutation = Arc::new(writer.cognitive_mutation_capability()?);
        Ok(Self {
            writer,
            cognitive_runtime: codex_hepta_memory::CognitiveRuntime::Available(Arc::new(
                runtime_store,
            )),
            mutation: Some(mutation),
            dispatcher: None,
        })
    }

    /// Qualification-only compatibility seam around an already-open store.
    /// It does not retain the verifier, so production semantic mutation methods
    /// below reject this handle with `LiveVerifierRequired`. The seam does not
    /// exist in the default/product build.
    #[cfg(feature = "qualification-cognitive-write")]
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
        let runtime_store = store.clone();
        let writer =
            ProductionDurableWriter::open(store, authority, verifier, lease_id, lease_generation)
                .await?;
        Ok(Self {
            writer: Arc::new(writer),
            cognitive_runtime: codex_hepta_memory::CognitiveRuntime::Available(Arc::new(
                runtime_store,
            )),
            mutation: None,
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
        let mutation = self.production_mutation().ok_or_else(|| {
            AgentdError::Protocol(
                "production cognitive mutation capability is not attached".to_string(),
            )
        })?;
        Ok(mutation.remember_with_kg(access, source, draft, facts).await?)
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
        let mutation = self.production_mutation().ok_or_else(|| {
            AgentdError::Protocol(
                "production cognitive mutation capability is not attached".to_string(),
            )
        })?;
        Ok(mutation
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
        let mutation = self.production_mutation().ok_or_else(|| {
            AgentdError::Protocol(
                "production cognitive mutation capability is not attached".to_string(),
            )
        })?;
        Ok(mutation
            .forget_with_kg(access, memory_id, expected_revision, source, draft)
            .await?)
    }

    pub fn writer(&self) -> Arc<ProductionDurableWriter> {
        Arc::clone(&self.writer)
    }

    /// Reuse the exact recovered generation for Agentd's read side without
    /// reopening by path and without widening the durable writer's raw-store
    /// visibility beyond the owner crate.
    pub(crate) fn cognitive_runtime(&self) -> codex_hepta_memory::CognitiveRuntime {
        self.cognitive_runtime.clone()
    }

    /// Return the sealed production mutation capability, if this host was
    /// created through exact-cut recovery with a retained live verifier.
    pub fn production_mutation(&self) -> Option<Arc<dyn ProductionCognitiveMutation>> {
        self.mutation.as_ref().map(|capability| {
            let capability: Arc<dyn ProductionCognitiveMutation> = capability.clone();
            capability
        })
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


//! Explicit Agentd/host seam for the production durable writer.
//!
//! The host must supply an externally verified authority lease and verifier.
//! Nothing in Agentd startup installs this capability automatically; the
//! default runtime remains read-only. Destination adapters are explicitly
//! registered by stable destination id and dispatch fails closed when the
//! requested destination is absent or ambiguous.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::CognitiveAccess;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::ForgetMemoryDraft;
use codex_hepta_cognitive_store::KgFactSetDraft;
use codex_hepta_cognitive_store::MemoryDraft;
use codex_hepta_cognitive_store::MemoryRevisionDraft;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::ProductionCognitiveMutation;
use codex_hepta_cognitive_store::ProductionCognitiveMutationCapability;
use codex_hepta_cognitive_store::ProductionCognitiveMutationReceiptV1;
use codex_hepta_cognitive_store::ProductionDispatchReceipt;
use codex_hepta_cognitive_store::ProductionDurableWriter;
use codex_hepta_cognitive_store::ProductionQueuedReceipt;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_cognitive_store::ProductionWriterError;
use codex_hepta_cognitive_store::SourceDraft;
use codex_hepta_cognitive_store::StableMemoryId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;

use crate::AgentdConfig;
use crate::AgentdError;

/// Externally owned grant source. Agentd asks for a grant bound to the exact
/// FinalUseBinding; it never receives or constructs the issuer signing key.
pub trait AgentdFinalUseGrantProvider: Send + Sync {
    fn signed_grant(&self, binding: &FinalUseBinding) -> Result<SignedFinalUseGrant, AgentdError>;
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
    additional_targets: Vec<(FinalUseAuthority, Arc<dyn FinalUseProductionOutboxTarget>)>,
}

impl fmt::Debug for AgentdProductionOperationRuntimeConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdProductionOperationRuntimeConfig")
            .field("authority", &self.authority)
            .field("lease_id", &self.lease_id)
            .field("lease_generation", &self.lease_generation)
            .field("destination", &self.target.destination_id())
            .field("additional_destinations", &self.additional_targets.len())
            .field("reconcile_interval", &self.reconcile_interval)
            .finish_non_exhaustive()
    }
}

impl AgentdProductionOperationRuntimeConfig {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: String,
        lease_generation: u64,
        final_use: FinalUseAuthority,
        target: Arc<dyn FinalUseProductionOutboxTarget>,
        grants: Arc<dyn AgentdFinalUseGrantProvider>,
        reconcile_interval: Duration,
    ) -> Self {
        Self {
            authority,
            verifier,
            lease_id,
            lease_generation,
            final_use,
            target,
            grants,
            reconcile_interval,
            additional_targets: Vec::new(),
        }
    }

    pub fn with_additional_target(
        mut self,
        final_use: FinalUseAuthority,
        target: Arc<dyn FinalUseProductionOutboxTarget>,
    ) -> Result<Self, AgentdError> {
        let destination = target.destination_id();
        if destination.is_empty()
            || destination == self.target.destination_id()
            || self
                .additional_targets
                .iter()
                .any(|(_, existing)| existing.destination_id() == destination)
        {
            return Err(AgentdError::Invalid(
                "production operation destinations must be non-empty and unique".to_string(),
            ));
        }
        self.additional_targets.push((final_use, target));
        Ok(self)
    }

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

    /// Attach operation dispatch to the same independently recovered owner
    /// used for semantic mutations. This never opens a second writer or falls
    /// back to an unauthenticated legacy store after recovery failure.
    pub(crate) async fn attach(
        self,
        recovered_host: Arc<AgentdProductionWriterHost>,
    ) -> Result<(Arc<AgentdProductionWriterHost>, Duration), AgentdError> {
        let Self {
            authority,
            verifier,
            lease_id,
            lease_generation,
            final_use,
            target,
            grants,
            reconcile_interval,
            additional_targets,
        } = self;
        if recovered_host.writer.authority() != &authority
            || recovered_host.writer.lease_id() != lease_id
            || recovered_host.writer.generation() != lease_generation
            || recovered_host.production_mutation().is_none()
        {
            return Err(AgentdError::GenerationFenced(
                "production operation configuration differs from the recovered writer owner"
                    .to_string(),
            ));
        }
        verifier
            .verify(&authority, recovered_host.writer.owner_agent_id())
            .map_err(|reason| {
                AgentdError::GenerationFenced(format!(
                    "production operation authority rejected: {reason}"
                ))
            })?;
        recovered_host.writer.verify_current_authority().await?;
        let mut host = recovered_host.as_ref().clone().attach_target(
            final_use,
            target,
            Arc::clone(&grants),
        )?;
        for (additional_final_use, additional_target) in additional_targets {
            host = host.attach_additional_target(additional_final_use, additional_target)?;
        }
        Ok((Arc::new(host), reconcile_interval))
    }
}

/// Host-owned production writer handle. Constructing this value does not
/// mutate Agentd's runtime configuration; callers explicitly attach/use it.
#[derive(Clone)]
pub struct AgentdProductionWriterHost {
    writer: Arc<ProductionDurableWriter>,
    dispatchers: BTreeMap<String, ProductionFinalUseOutboxDispatcher>,
    grants: Option<Arc<dyn AgentdFinalUseGrantProvider>>,
    // Private read-side clone of the exact recovered generation. Runtime
    // composition can reuse the same fenced owner without reopening by path or
    // exposing ProductionDurableWriter's crate-private raw-store handle.
    cognitive_runtime: codex_hepta_memory::CognitiveRuntime,
    mutation: Option<Arc<ProductionCognitiveMutationCapability>>,
}

impl fmt::Debug for AgentdProductionWriterHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdProductionWriterHost")
            .field("writer", &self.writer)
            .field("destination_count", &self.dispatchers.len())
            .field("grant_provider_attached", &self.grants.is_some())
            .field(
                "cognitive_runtime_available",
                &self.cognitive_runtime.available_store().is_some(),
            )
            .field("production_mutation_attached", &self.mutation.is_some())
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
            dispatchers: BTreeMap::new(),
            grants: None,
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
            dispatchers: BTreeMap::new(),
            grants: None,
            cognitive_runtime: codex_hepta_memory::CognitiveRuntime::Available(Arc::new(
                runtime_store,
            )),
            mutation: None,
        })
    }

    pub async fn remember_with_kg(
        &self,
        access: &CognitiveAccess,
        source: &SourceDraft,
        draft: &MemoryDraft,
        facts: &KgFactSetDraft,
    ) -> Result<ProductionCognitiveMutationReceiptV1, AgentdError> {
        let mutation = self.production_mutation().ok_or_else(|| {
            AgentdError::Protocol(
                "production cognitive mutation capability is not attached".to_string(),
            )
        })?;
        Ok(mutation
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
    ) -> Result<ProductionCognitiveMutationReceiptV1, AgentdError> {
        let mutation = self.production_mutation().ok_or_else(|| {
            AgentdError::Protocol(
                "production cognitive mutation capability is not attached".to_string(),
            )
        })?;
        Ok(mutation
            .correct_with_kg(access, memory_id, expected_revision, source, draft, facts)
            .await?)
    }

    pub async fn forget_with_kg(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &ForgetMemoryDraft,
    ) -> Result<ProductionCognitiveMutationReceiptV1, AgentdError> {
        let mutation = self.production_mutation().ok_or_else(|| {
            AgentdError::Protocol(
                "production cognitive mutation capability is not attached".to_string(),
            )
        })?;
        Ok(mutation
            .forget_with_kg(access, memory_id, expected_revision, source, draft)
            .await?)
    }

    /// Observe an already-admitted semantic operation without repeating it.
    /// This returns immutable result metadata, never a new execution grant.
    pub async fn cognitive_mutation_result(
        &self,
        operation_digest: &codex_hepta_contracts::Sha256Digest,
    ) -> Result<Option<codex_hepta_cognitive_store::ProductionCognitiveMutationResultV1>, AgentdError>
    {
        Ok(self
            .writer
            .cognitive_mutation_result(operation_digest)
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

    /// Attach the provider/host target together with the kernel-owned final-use
    /// authority. Replacing either value requires a new host handle, avoiding
    /// an in-flight authority/target swap behind the writer's back.
    pub fn attach_target(
        mut self,
        final_use: FinalUseAuthority,
        target: Arc<dyn FinalUseProductionOutboxTarget>,
        grants: Arc<dyn AgentdFinalUseGrantProvider>,
    ) -> Result<Self, AgentdError> {
        let destination = target.destination_id().to_string();
        if destination.is_empty() || !self.dispatchers.is_empty() {
            return Err(AgentdError::Invalid(
                "primary production operation destination must be non-empty and attached exactly once"
                    .to_string(),
            ));
        }
        self.dispatchers.insert(
            destination,
            ProductionFinalUseOutboxDispatcher::attach(final_use, target),
        );
        self.grants = Some(grants);
        Ok(self)
    }

    pub fn attach_additional_target(
        mut self,
        final_use: FinalUseAuthority,
        target: Arc<dyn FinalUseProductionOutboxTarget>,
    ) -> Result<Self, AgentdError> {
        let destination = target.destination_id().to_string();
        if destination.is_empty() || self.dispatchers.contains_key(&destination) {
            return Err(AgentdError::Invalid(
                "production operation destination must be non-empty and unique".to_string(),
            ));
        }
        self.dispatchers.insert(
            destination,
            ProductionFinalUseOutboxDispatcher::attach(final_use, target),
        );
        Ok(self)
    }

    pub fn has_target(&self) -> bool {
        !self.dispatchers.is_empty() && self.grants.is_some()
    }

    pub fn destination_count(&self) -> usize {
        self.dispatchers.len()
    }

    /// Product dispatch path: derive the exact final-use binding from the
    /// durable operation, ask the external grant provider for that binding,
    /// and consume it immediately at the attached target.
    pub async fn dispatch_with_grant_provider(
        &self,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        if self.dispatchers.len() != 1 {
            return Err(AgentdError::Protocol(
                "multiple production destinations are attached; dispatch must name the destination"
                    .to_string(),
            ));
        }
        let destination = self
            .dispatchers
            .keys()
            .next()
            .ok_or_else(|| {
                AgentdError::Protocol(
                    "production final-use outbox dispatcher is not explicitly attached".to_string(),
                )
            })?
            .clone();
        self.dispatch_to_with_grant_provider(&destination, receipt)
            .await
    }

    pub async fn dispatch_to_with_grant_provider(
        &self,
        destination_id: &str,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        let dispatcher = self.dispatchers.get(destination_id).ok_or_else(|| {
            AgentdError::Protocol(format!(
                "production destination {destination_id:?} is not registered"
            ))
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
        for dispatcher in self.dispatchers.values() {
            if total >= limit {
                break;
            }
            total += dispatcher
                .reconcile(self.writer.as_ref(), limit - total)
                .await?;
        }
        Ok(total)
    }

    pub async fn dispatch(
        &self,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        let dispatcher = self
            .dispatchers
            .get(&expected.destination_id)
            .ok_or_else(|| {
                AgentdError::Protocol(format!(
                    "production destination {:?} is not registered",
                    expected.destination_id
                ))
            })?;
        Ok(dispatcher
            .dispatch(self.writer.as_ref(), signed, expected, receipt)
            .await?)
    }
}

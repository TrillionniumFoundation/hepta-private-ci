//! Canonical cognitive-store boundaries over the single durable SQLite owner.
//!
//! `hepta-memory::CognitiveStore` remains the physical database owner. Ordinary
//! serving code receives [`DurableCognitiveReadCapability`]. The named Agentd
//! host may additionally derive [`FederationPolicyCapability`] through its
//! explicit feature, while semantic production mutation remains a separate
//! sealed capability. No capability below exposes a raw-backend escape method.

use std::fmt;
use std::sync::Arc;

pub const DURABLE_BACKEND_ID: &str = "hepta-memory::CognitiveStore";
pub const DURABLE_DATABASE_BASENAME: &str = "cognitive_1.sqlite3";
pub const DURABLE_SINGLE_WRITER: bool = true;

pub use codex_hepta_memory::CognitiveAccess;
pub use codex_hepta_memory::CognitiveRecoveryAnchor;
pub use codex_hepta_memory::CognitiveRecoveryError;
pub use codex_hepta_memory::CognitiveRecoveryRequirement;
pub use codex_hepta_memory::CognitiveScope;
pub use codex_hepta_memory::CognitiveStoreError as DurableCognitiveStoreError;
pub use codex_hepta_memory::CognitiveWriteReceipt;
pub use codex_hepta_memory::DurableCognitiveSnapshot;
pub use codex_hepta_memory::DurableCognitiveSnapshotCursor;
pub use codex_hepta_memory::DurableCognitiveSnapshotPage;
pub use codex_hepta_memory::FederationCapability;
pub use codex_hepta_memory::FederationCapabilityId;
pub use codex_hepta_memory::FederationCapabilityStatus;
pub use codex_hepta_memory::FederationGrantRequest;
pub use codex_hepta_memory::FederationRevocation;
pub use codex_hepta_memory::ForgetMemoryDraft;
pub use codex_hepta_memory::KgFactSetDraft;
pub use codex_hepta_memory::LedgerSourceKind;
pub use codex_hepta_memory::MAX_LANE_C_PAGE_ANCESTRY_REVISIONS;
pub use codex_hepta_memory::MAX_LANE_C_PAGE_CITATIONS;
pub use codex_hepta_memory::MAX_LANE_C_SNAPSHOT_PAGE_HEADS;
pub use codex_hepta_memory::MemoryDraft;
pub use codex_hepta_memory::MemoryLifecycleState;
pub use codex_hepta_memory::MemoryRevisionDraft;
pub use codex_hepta_memory::MemoryVerification;
pub use codex_hepta_memory::PRODUCTION_COGNITIVE_MUTATION_NAMESPACE;
pub use codex_hepta_memory::PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION;
pub use codex_hepta_memory::ProductionAuthorityLease;
pub use codex_hepta_memory::ProductionAuthorityToken;
pub use codex_hepta_memory::ProductionAuthorityVerifier;
pub use codex_hepta_memory::ProductionCognitiveMutation;
pub use codex_hepta_memory::ProductionCognitiveMutationCapability;
pub use codex_hepta_memory::ProductionCognitiveMutationError;
pub use codex_hepta_memory::ProductionCognitiveMutationFuture;
pub use codex_hepta_memory::ProductionCognitiveMutationReceiptV1;
pub use codex_hepta_memory::ProductionDispatchFuture;
pub use codex_hepta_memory::ProductionDispatchReceipt;
pub use codex_hepta_memory::ProductionDispatchRequest;
pub use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;
pub use codex_hepta_memory::ProductionOutboxTarget;
pub use codex_hepta_memory::ProductionQueuedReceipt;
pub use codex_hepta_memory::ProductionWriterError;
pub use codex_hepta_memory::RecoveredCognitiveReadOnly;
pub use codex_hepta_memory::SourceDraft;
pub use codex_hepta_memory::StableMemoryId;

/// Mutable physical owner compatibility alias.
///
/// Host-feature unification must not expose this alias to ordinary consumers.
/// The physical-owner import is restricted to the canonical host by the source
/// boundary check; this compatibility spelling is only for qualification.
#[cfg(feature = "qualification-cognitive-write")]
#[doc(hidden)]
pub use codex_hepta_memory::CognitiveStore as DurableCognitiveStore;

/// Qualification-only spelling for the mutable physical owner.
#[cfg(feature = "qualification-cognitive-write")]
#[doc(hidden)]
pub use codex_hepta_memory::CognitiveStore as QualificationDurableCognitiveStore;

/// Bounded read capability for one exact durable cognitive owner.
///
/// This type contains no semantic mutation or federation-policy mutation
/// methods. It can only be derived from an already composed `CognitiveRuntime`,
/// so it cannot open a second database owner or manufacture authority.
#[derive(Clone)]
pub struct DurableCognitiveReadCapability {
    backend: Arc<codex_hepta_memory::CognitiveStore>,
}

/// Compatibility spelling retained while callers migrate to the capability
/// name. Both names denote the same read-only API.
pub type DurableCognitiveReadStore = DurableCognitiveReadCapability;

impl fmt::Debug for DurableCognitiveReadCapability {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableCognitiveReadCapability")
            .field("owner_agent_id", self.backend.owner_agent_id())
            .finish_non_exhaustive()
    }
}

impl DurableCognitiveReadCapability {
    /// Derive a bounded capability from a host-composed runtime. No file is
    /// opened and no authority is manufactured here.
    pub fn from_runtime(runtime: &codex_hepta_memory::CognitiveRuntime) -> Option<Self> {
        runtime.available_store().map(|backend| Self {
            backend: Arc::clone(backend),
        })
    }

    pub fn owner_agent_id(&self) -> &codex_hepta_contracts::AgentId {
        self.backend.owner_agent_id()
    }

    pub async fn lane_c_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, DurableCognitiveStoreError> {
        self.backend
            .lane_c_snapshot(access, scope, now_unix_seconds)
            .await
    }

    /// Page through the existing owner without exposing a writable handle.
    /// The owner enforces 1..=512 heads, complete selected ancestry/citations,
    /// scope authorization and exact-cut/observation-time cursor currentness.
    pub async fn lane_c_snapshot_page(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        maximum_heads: u32,
        after: Option<DurableCognitiveSnapshotCursor>,
    ) -> Result<DurableCognitiveSnapshotPage, DurableCognitiveStoreError> {
        self.backend
            .lane_c_snapshot_page(access, scope, now_unix_seconds, maximum_heads, after)
            .await
    }

    /// Recheck exactly the same page through the owner before consumer use.
    /// A changed scope, page size, observation time or owner cut is not a valid
    /// continuation and never causes silent replacement with a newer page.
    pub async fn revalidate_lane_c_snapshot_page(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        maximum_heads: u32,
        expected: &DurableCognitiveSnapshotPage,
    ) -> Result<DurableCognitiveSnapshotPage, DurableCognitiveStoreError> {
        let observed = self
            .lane_c_snapshot_page(
                access,
                scope,
                now_unix_seconds,
                maximum_heads,
                expected.after().cloned(),
            )
            .await?;
        if observed != *expected {
            return Err(DurableCognitiveStoreError::Conflict(
                "Lane C product page no longer matches its exact owner observation".to_string(),
            ));
        }
        Ok(observed)
    }

    pub async fn observe_memory_retrieval(
        &self,
        access: &CognitiveAccess,
        request: &codex_hepta_memory::RetrievalRequest,
    ) -> Result<codex_hepta_memory::RetrievalObservation, DurableCognitiveStoreError> {
        self.backend.observe_memory_retrieval(access, request).await
    }

    pub async fn revalidate_memory_candidates(
        &self,
        access: &CognitiveAccess,
        bindings: &[codex_hepta_memory::MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> Result<Vec<codex_hepta_memory::RevalidationStatus>, DurableCognitiveStoreError> {
        self.backend
            .revalidate_memory_candidates(access, bindings, now_unix_seconds)
            .await
    }

    pub async fn read_shared_experience(
        &self,
        consumer: &codex_hepta_memory::FederationConsumerAccess,
        key: &codex_hepta_contracts::Sha256Digest,
        purpose: &codex_hepta_memory::SharedExperiencePurposeV1,
    ) -> Result<codex_hepta_memory::SharedExperienceUseV1, DurableCognitiveStoreError> {
        self.backend
            .read_shared_experience(consumer, key, purpose)
            .await
    }

    pub async fn revalidate_lane_c_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected: &DurableCognitiveSnapshot,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, DurableCognitiveStoreError> {
        self.backend
            .revalidate_lane_c_snapshot(access, scope, expected, now_unix_seconds)
            .await
    }

    pub async fn federation_capability_status(
        &self,
        capability_id: &FederationCapabilityId,
    ) -> Result<Option<FederationCapabilityStatus>, DurableCognitiveStoreError> {
        self.backend
            .federation_capability_status(capability_id)
            .await
    }

    pub async fn list_federation_capabilities(
        &self,
        limit: usize,
    ) -> Result<Vec<FederationCapabilityStatus>, DurableCognitiveStoreError> {
        self.backend.list_federation_capabilities(limit).await
    }
}

/// Named-host-only policy capability for federation grant and revocation.
///
/// It is a separate type from the read capability and is absent from default
/// builds. It cannot mutate Memory revisions, append sources, create writer
/// leases, migrate storage, or expose the raw SQLite owner.
#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
#[derive(Clone)]
pub struct FederationPolicyCapability {
    backend: Arc<codex_hepta_memory::CognitiveStore>,
}

#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
impl fmt::Debug for FederationPolicyCapability {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederationPolicyCapability")
            .field("owner_agent_id", self.backend.owner_agent_id())
            .finish_non_exhaustive()
    }
}

#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
impl FederationPolicyCapability {
    /// Derive the policy capability from the same already-composed owner used
    /// for reads. No second connection, writer, or authority is created.
    pub fn from_runtime(runtime: &codex_hepta_memory::CognitiveRuntime) -> Option<Self> {
        runtime.available_store().map(|backend| Self {
            backend: Arc::clone(backend),
        })
    }

    pub fn owner_agent_id(&self) -> &codex_hepta_contracts::AgentId {
        self.backend.owner_agent_id()
    }

    pub async fn grant_federated_recall(
        &self,
        owner_access: &CognitiveAccess,
        request: &FederationGrantRequest,
    ) -> Result<FederationCapability, DurableCognitiveStoreError> {
        self.backend
            .grant_federated_recall(owner_access, request)
            .await
    }

    pub async fn revoke_federated_recall_by_id(
        &self,
        owner_access: &CognitiveAccess,
        capability_id: &FederationCapabilityId,
        revoked_at_unix_seconds: i64,
    ) -> Result<FederationRevocation, DurableCognitiveStoreError> {
        self.backend
            .revoke_federated_recall_by_id(owner_access, capability_id, revoked_at_unix_seconds)
            .await
    }
}

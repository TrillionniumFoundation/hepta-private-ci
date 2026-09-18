use std::collections::BTreeSet;
use std::fmt;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory_federation::FederatedCompletenessV2;
use codex_hepta_memory_federation::FederatedCoverageV2;
use codex_hepta_memory_federation::FederatedEvidenceItemV2;
use codex_hepta_memory_federation::FederatedLeaseV2;
use codex_hepta_memory_federation::FederatedQueryV2;
use codex_hepta_memory_federation::FederatedValidityV2;
use codex_hepta_memory_federation::FederationAttemptControlV2;
use codex_hepta_memory_federation::FederationAuthorityFuture;
use codex_hepta_memory_federation::FederationAuthorityObservationV2;
use codex_hepta_memory_federation::FederationAuthorityStateV2;
use codex_hepta_memory_federation::FederationAuthorityV2;
use codex_hepta_memory_federation::FederationStopFuture;
use codex_hepta_memory_federation::FederationStopReasonV2;
use codex_hepta_memory_federation::FederationTransportFuture;
use codex_hepta_memory_federation::FederationTransportResultV2;
use codex_hepta_memory_federation::FederationTransportV2;
use codex_hepta_memory_federation::FederationV2Error;
use codex_hepta_memory_federation::RemoteFederatedResponseV2;
use codex_hepta_memory_federation::execute_once;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CognitiveCompactError;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CompactCheckpoint;
use crate::CompactCommitDecision;
use crate::CompactLease;
use crate::CompactParentSnapshot;
use crate::FederatedMemoryReader;
use crate::FederatedMemoryRevalidationBinding;
use crate::FederatedRecallSet;
use crate::FederatedRetrievalBatch;
use crate::FederatedRetrievalCandidate;
use crate::FederatedRevalidationStatus;
use crate::FederationCapability;
use crate::FederationConsumerAccess;
use crate::FederationRevalidationDrift;
use crate::MAX_FEDERATION_SOURCES_PER_AGENT;
use crate::MAX_RETRIEVAL_RESULTS;
use crate::RehydrationPlan;
use crate::RetrievalRequest;

const PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(2);
const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;
const PRODUCT_FEDERATION_PURPOSE: &[u8] = b"hepta.cognitive.federated-recall.product.v2";
static PRODUCT_FEDERATION_ATTEMPT_SEQUENCE: AtomicU64 = AtomicU64::new(1);

/// Sanitized reason why an owning runtime could not open its Cognitive Plane.
///
/// This type deliberately carries no filesystem paths, database text, or raw
/// error strings, so it is safe to expose through health and tool surfaces.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CognitiveUnavailableReason {
    InvalidStoreConfiguration,
    AccessDenied,
    RevisionConflict,
    CorruptStore,
    StorageUnavailable,
}

impl CognitiveUnavailableReason {
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidStoreConfiguration => "invalid_store_configuration",
            Self::AccessDenied => "access_denied",
            Self::RevisionConflict => "revision_conflict",
            Self::CorruptStore => "corrupt_store",
            Self::StorageUnavailable => "storage_unavailable",
        }
    }
}

impl From<&CognitiveStoreError> for CognitiveUnavailableReason {
    fn from(error: &CognitiveStoreError) -> Self {
        match error {
            CognitiveStoreError::Invalid(_) => Self::InvalidStoreConfiguration,
            CognitiveStoreError::AccessDenied(_) => Self::AccessDenied,
            CognitiveStoreError::Conflict(_) => Self::RevisionConflict,
            CognitiveStoreError::Corrupt(_) => Self::CorruptStore,
            CognitiveStoreError::Unavailable(_) => Self::StorageUnavailable,
        }
    }
}

/// Process-scoped Cognitive Plane capability supplied to Codex extensions.
///
/// Plain Codex uses `Absent`. An owning Hepta agent uses `Available` after a
/// successful open, or `Unavailable` when opening failed. `AvailableFederated`
/// is retained for compatibility-only callers. Production Agentd composition
/// uses `AvailableFederatedV2`, which stores only enrolled owner layouts and
/// executes every physical read through the canonical memory.federation V2
/// transport, deadline and post-I/O authority boundary.
#[derive(Clone, Default)]
pub enum CognitiveRuntime {
    #[default]
    Absent,
    Available(Arc<CognitiveStore>),
    AvailableFederated {
        store: Arc<CognitiveStore>,
        federation: Arc<FederatedRecallSet>,
    },
    AvailableFederatedV2 {
        store: Arc<CognitiveStore>,
        consumer_agent_id: AgentId,
        owner_layouts: Arc<Vec<HeptaAgentLayout>>,
    },
    Unavailable(CognitiveUnavailableReason),
}

impl CognitiveRuntime {
    pub fn from_open_result(result: Result<CognitiveStore, CognitiveStoreError>) -> Self {
        match result {
            Ok(store) => Self::Available(Arc::new(store)),
            Err(error) => Self::Unavailable(CognitiveUnavailableReason::from(&error)),
        }
    }

    pub fn available_store(&self) -> Option<&Arc<CognitiveStore>> {
        match self {
            Self::Available(store) => Some(store),
            Self::AvailableFederated { store, .. }
            | Self::AvailableFederatedV2 { store, .. } => Some(store),
            Self::Absent | Self::Unavailable(_) => None,
        }
    }

    /// Compatibility-only federation composition. Product Agentd uses
    /// `with_federation_sources` so all reads cross the canonical V2 boundary.
    pub fn with_federation(self, federation: FederatedRecallSet) -> Self {
        if federation.is_empty() {
            return self;
        }
        match self {
            Self::Available(store) => Self::AvailableFederated {
                store,
                federation: Arc::new(federation),
            },
            Self::AvailableFederated { store, .. }
            | Self::AvailableFederatedV2 { store, .. } => Self::AvailableFederated {
                store,
                federation: Arc::new(federation),
            },
            Self::Absent | Self::Unavailable(_) => self,
        }
    }

    /// Product composition for capability-scoped federated memory reads.
    ///
    /// The owner layouts are enrollment candidates only. Every request
    /// rediscovers current grants read-only, executes one bounded V2 attempt per
    /// enrolled owner, and re-observes authority after remote I/O before any
    /// evidence becomes eligible for attachment.
    pub fn with_federation_sources(
        self,
        consumer_agent_id: AgentId,
        mut owner_layouts: Vec<HeptaAgentLayout>,
    ) -> Self {
        owner_layouts.sort_by(|left, right| left.agent_id().cmp(right.agent_id()));
        owner_layouts.dedup_by(|left, right| left.agent_id() == right.agent_id());
        owner_layouts.truncate(MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS);
        if owner_layouts.is_empty() {
            return self;
        }
        match self {
            Self::Available(store)
            | Self::AvailableFederated { store, .. }
            | Self::AvailableFederatedV2 { store, .. } => Self::AvailableFederatedV2 {
                store,
                consumer_agent_id,
                owner_layouts: Arc::new(owner_layouts),
            },
            Self::Absent | Self::Unavailable(_) => self,
        }
    }

    /// Legacy accessor retained for compatibility-only tests and callers.
    pub fn federation(&self) -> Option<&Arc<FederatedRecallSet>> {
        match self {
            Self::AvailableFederated { federation, .. } => Some(federation),
            Self::Absent
            | Self::Available(_)
            | Self::AvailableFederatedV2 { .. }
            | Self::Unavailable(_) => None,
        }
    }

    pub fn has_federation(&self) -> bool {
        match self {
            Self::AvailableFederated { federation, .. } => !federation.is_empty(),
            Self::AvailableFederatedV2 { owner_layouts, .. } => !owner_layouts.is_empty(),
            Self::Absent | Self::Available(_) | Self::Unavailable(_) => false,
        }
    }

    pub fn federation_consumer_agent_id(&self) -> Option<&AgentId> {
        match self {
            Self::AvailableFederated { federation, .. } => Some(federation.consumer_agent_id()),
            Self::AvailableFederatedV2 {
                consumer_agent_id, ..
            } => Some(consumer_agent_id),
            Self::Absent | Self::Available(_) | Self::Unavailable(_) => None,
        }
    }

    /// Executes the product federated read path and returns explicit aggregate
    /// coverage. `failed_peers` is never silently collapsed into an empty
    /// candidate set.
    pub async fn retrieve_federated(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<(FederatedRetrievalBatch, FederatedCoverageV2), CognitiveStoreError> {
        match self {
            Self::AvailableFederated { federation, .. } => {
                let batch = federation.retrieve(access, request).await?;
                Ok((
                    batch,
                    FederatedCoverageV2 {
                        requested_peers: 1,
                        completed_peers: 1,
                        failed_peers: 0,
                        truncated_items: 0,
                    },
                ))
            }
            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                ..
            } => {
                retrieve_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    access,
                    request,
                )
                .await
            }
            Self::Absent | Self::Available(_) | Self::Unavailable(_) => Err(
                CognitiveStoreError::AccessDenied("memory federation is unavailable".to_string()),
            ),
        }
    }

    /// Revalidates an attachment binding at the physical model-request
    /// boundary. The V2 product path rediscovers the current owner capability
    /// rather than trusting the reader that produced the earlier result.
    pub async fn revalidate_federated(
        &self,
        access: &FederationConsumerAccess,
        binding: &FederatedMemoryRevalidationBinding,
        now_unix_seconds: i64,
    ) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
        match self {
            Self::AvailableFederated { federation, .. } => {
                federation.revalidate(access, binding, now_unix_seconds).await
            }
            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                ..
            } => {
                revalidate_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    access,
                    binding,
                    now_unix_seconds,
                )
                .await
            }
            Self::Absent | Self::Available(_) | Self::Unavailable(_) => Err(
                CognitiveStoreError::AccessDenied("memory federation is unavailable".to_string()),
            ),
        }
    }

    pub fn unavailable_reason(&self) -> Option<CognitiveUnavailableReason> {
        match self {
            Self::Unavailable(reason) => Some(*reason),
            Self::Absent
            | Self::Available(_)
            | Self::AvailableFederated { .. }
            | Self::AvailableFederatedV2 { .. } => None,
        }
    }

    /// Captures a typed, local-development-only pre-compact lease envelope.
    ///
    /// This is a read-only contract seam: it does not acquire a lease, append
    /// an event, mutate SQLite, or authorize compaction. The Agent-local
    /// authoritative writer must perform the real CAS transaction.
    pub fn pre_compact(
        &self,
        snapshot: CompactParentSnapshot,
    ) -> Result<CompactLease, CognitiveCompactError> {
        self.require_compact_runtime()?;
        Ok(CompactLease::from_snapshot(snapshot))
    }

    /// Builds a typed post-compact rehydration plan without writing state.
    ///
    /// A plan starts as NotStarted; callers must execute and acknowledge
    /// rehydration through the owning event store before treating it as
    /// complete.
    pub fn post_compact(
        &self,
        checkpoint: &CompactCheckpoint,
        expected_revision: u64,
    ) -> Result<RehydrationPlan, CognitiveCompactError> {
        self.require_compact_runtime()?;
        checkpoint.rehydration_plan(expected_revision)
    }

    /// Performs read-only parent CAS and generation/fence validation for a
    /// checkpoint. No commit or projection write occurs here.
    pub fn validate_compact_commit(
        &self,
        checkpoint: &CompactCheckpoint,
        current: &CompactParentSnapshot,
    ) -> Result<CompactCommitDecision, CognitiveCompactError> {
        self.require_compact_runtime()?;
        Ok(checkpoint.validate_against(current))
    }

    fn require_compact_runtime(&self) -> Result<(), CognitiveCompactError> {
        match self {
            Self::Absent => Err(CognitiveCompactError::RuntimeAbsent),
            Self::Unavailable(reason) => {
                Err(CognitiveCompactError::RuntimeUnavailable { reason: *reason })
            }
            Self::Available(_)
            | Self::AvailableFederated { .. }
            | Self::AvailableFederatedV2 { .. } => Ok(()),
        }
    }
}

async fn retrieve_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
) -> Result<(FederatedRetrievalBatch, FederatedCoverageV2), CognitiveStoreError> {
    if access.agent_id() != consumer_agent_id {
        return Err(CognitiveStoreError::AccessDenied(
            "memory federation caller does not match the product consumer".to_string(),
        ));
    }

    let logical_start_ms = seconds_to_ms(request.now_unix_seconds())?;
    let started_at = Instant::now();
    let global_deadline_ms = logical_start_ms
        .checked_add(
            u64::try_from(PRODUCT_FEDERATION_TOTAL_BUDGET.as_millis()).unwrap_or(u64::MAX),
        )
        .ok_or_else(|| CognitiveStoreError::Invalid("federation deadline overflow".to_string()))?;

    let discovery = async {
        let mut readers = Vec::new();
        for owner_layout in owner_layouts {
            if readers.len() >= MAX_FEDERATION_SOURCES_PER_AGENT {
                break;
            }
            let discovered = FederatedMemoryReader::discover(
                owner_layout,
                consumer_agent_id,
                request.now_unix_seconds(),
            )
            .await;
            let Ok(discovered) = discovered else {
                continue;
            };
            for reader in discovered {
                if readers.len() >= MAX_FEDERATION_SOURCES_PER_AGENT {
                    break;
                }
                readers.push((owner_layout.clone(), reader));
            }
        }
        readers
    };
    let mut readers = tokio::time::timeout(PRODUCT_FEDERATION_TOTAL_BUDGET, discovery)
        .await
        .map_err(|_| {
            CognitiveStoreError::Unavailable("memory federation discovery timed out".to_string())
        })?;
    readers.sort_by(|(_, left), (_, right)| {
        left.capability()
            .owner_agent_id()
            .cmp(right.capability().owner_agent_id())
            .then_with(|| left.capability().id().cmp(right.capability().id()))
    });
    readers.dedup_by(|(_, left), (_, right)| left.capability().id() == right.capability().id());
    readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);

    let query_sha256 = Sha256Digest::for_bytes(request.query().as_bytes());
    let mut coverage = FederatedCoverageV2 {
        requested_peers: u32::try_from(readers.len()).unwrap_or(u32::MAX),
        completed_peers: 0,
        failed_peers: 0,
        truncated_items: 0,
    };
    let mut candidates = Vec::new();

    for (owner_layout, reader) in &readers {
        if elapsed_logical_ms(logical_start_ms, started_at) >= global_deadline_ms {
            coverage.failed_peers = coverage.failed_peers.saturating_add(1);
            continue;
        }
        let (query, lease) = build_product_query_and_lease(
            reader,
            access,
            request,
            logical_start_ms,
            global_deadline_ms,
        )?;
        let captured = Arc::new(Mutex::new(None));
        let transport = ProductReaderTransport {
            reader,
            access,
            request,
            captured: Arc::clone(&captured),
        };
        let authority = ProductReaderAuthority {
            owner_layout,
            consumer_agent_id,
            expected_capability: reader.capability(),
            logical_start_ms,
            started_at,
        };
        let control = ProductAttemptControl {
            logical_start_ms,
            started_at,
        };
        let result = execute_once(
            &transport,
            &authority,
            &control,
            logical_start_ms,
            query,
            &lease,
        )
        .await;
        let Ok(result) = result else {
            coverage.failed_peers = coverage.failed_peers.saturating_add(1);
            continue;
        };
        coverage.completed_peers = coverage
            .completed_peers
            .saturating_add(result.coverage.completed_peers);
        coverage.failed_peers = coverage
            .failed_peers
            .saturating_add(result.coverage.failed_peers);
        coverage.truncated_items = coverage
            .truncated_items
            .saturating_add(result.coverage.truncated_items);

        if result.validity != FederatedValidityV2::Valid {
            continue;
        }
        let selected = result
            .items
            .iter()
            .map(|item| {
                (
                    item.source_owner_id.as_str().to_string(),
                    item.record_id.as_str().to_string(),
                    item.record_revision.get(),
                )
            })
            .collect::<BTreeSet<_>>();
        let mut guard = captured.lock().map_err(|_| {
            CognitiveStoreError::Unavailable("memory federation capture lock poisoned".to_string())
        })?;
        if let Some(batch) = guard.take() {
            candidates.extend(batch.candidates.into_iter().filter(|candidate| {
                selected.contains(&(
                    candidate.source_agent_id.as_str().to_string(),
                    candidate.candidate.memory.id.memory_id.as_str().to_string(),
                    candidate.candidate.memory.id.revision,
                ))
            }));
        }
    }

    candidates.sort_by(|left, right| {
        right
            .candidate
            .reciprocal_rank_score
            .cmp(&left.candidate.reciprocal_rank_score)
            .then_with(|| left.source_agent_id.cmp(&right.source_agent_id))
            .then_with(|| {
                left.candidate
                    .memory
                    .id
                    .memory_id
                    .cmp(&right.candidate.memory.id.memory_id)
            })
            .then_with(|| {
                left.candidate
                    .memory
                    .id
                    .revision
                    .cmp(&right.candidate.memory.id.revision)
            })
    });
    candidates.dedup_by(|left, right| {
        left.source_agent_id == right.source_agent_id
            && left.candidate.memory.id == right.candidate.memory.id
    });
    let before_truncation = candidates.len();
    candidates.truncate(MAX_RETRIEVAL_RESULTS);
    coverage.truncated_items = coverage.truncated_items.saturating_add(
        u32::try_from(before_truncation.saturating_sub(candidates.len())).unwrap_or(u32::MAX),
    );

    Ok((
        FederatedRetrievalBatch {
            query_sha256,
            candidates,
        },
        coverage,
    ))
}

async fn revalidate_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    access: &FederationConsumerAccess,
    binding: &FederatedMemoryRevalidationBinding,
    now_unix_seconds: i64,
) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
    if access.agent_id() != consumer_agent_id {
        return Ok(FederatedRevalidationStatus::Stale(
            FederationRevalidationDrift::Consumer,
        ));
    }
    let Some(owner_layout) = owner_layouts
        .iter()
        .find(|layout| layout.agent_id() == &binding.source_agent_id)
    else {
        return Ok(FederatedRevalidationStatus::Stale(
            FederationRevalidationDrift::CapabilityMissing,
        ));
    };
    let readers = FederatedMemoryReader::discover(owner_layout, consumer_agent_id, now_unix_seconds)
        .await?;
    let Some(reader) = readers
        .into_iter()
        .find(|reader| reader.capability().id() == binding.capability.id())
    else {
        return Ok(FederatedRevalidationStatus::Stale(
            FederationRevalidationDrift::CapabilityMissing,
        ));
    };
    reader.revalidate(access, binding, now_unix_seconds).await
}

struct ProductReaderTransport<'a> {
    reader: &'a FederatedMemoryReader,
    access: &'a FederationConsumerAccess,
    request: &'a RetrievalRequest,
    captured: Arc<Mutex<Option<FederatedRetrievalBatch>>>,
}

impl FederationTransportV2 for ProductReaderTransport<'_> {
    fn send_once<'a>(&'a self, query: &'a FederatedQueryV2) -> FederationTransportFuture<'a> {
        Box::pin(async move {
            let batch = self
                .reader
                .retrieve(self.access, self.request)
                .await
                .map_err(|_| FederationV2Error::TransportRejected)?;
            let items = batch
                .candidates
                .iter()
                .map(product_evidence_item)
                .collect::<Result<Vec<_>, _>>()?;
            let completeness = if items.is_empty() {
                FederatedCompletenessV2::Empty
            } else {
                FederatedCompletenessV2::Complete
            };
            let expires_unix_ms = capability_expiry_ms(self.reader.capability())
                .map_err(|_| FederationV2Error::TransportRejected)?;
            let response = RemoteFederatedResponseV2 {
                peer_id: query.peer_id.clone(),
                query_binding_digest: query.binding_digest(),
                scope_digest: query.scope_digest,
                purpose_digest: query.purpose_digest,
                generation_vector_digest: query.generation_vector_digest,
                response_digest: Digest32::ZERO,
                observed_frontier: self.reader.capability().revision().max(1),
                expires_unix_ms,
                items,
                completeness,
                terminal_observed: true,
            }
            .seal()?;
            let mut guard = self
                .captured
                .lock()
                .map_err(|_| FederationV2Error::TransportRejected)?;
            *guard = Some(batch);
            Ok(FederationTransportResultV2::Terminal(response))
        })
    }
}

struct ProductReaderAuthority<'a> {
    owner_layout: &'a HeptaAgentLayout,
    consumer_agent_id: &'a AgentId,
    expected_capability: &'a FederationCapability,
    logical_start_ms: u64,
    started_at: Instant,
}

impl FederationAuthorityV2 for ProductReaderAuthority<'_> {
    fn revalidate<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFuture<'a> {
        Box::pin(async move {
            let observed_unix_ms = elapsed_logical_ms(self.logical_start_ms, self.started_at);
            let now_unix_seconds = i64::try_from(observed_unix_ms / 1_000)
                .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let readers = FederatedMemoryReader::discover(
                self.owner_layout,
                self.consumer_agent_id,
                now_unix_seconds,
            )
            .await
            .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let current = readers
                .iter()
                .find(|reader| reader.capability().id() == self.expected_capability.id());
            let state = match current {
                None => FederationAuthorityStateV2::Revoked,
                Some(reader) if reader.capability() == self.expected_capability => {
                    FederationAuthorityStateV2::Current
                }
                Some(_) => FederationAuthorityStateV2::StaleGeneration,
            };
            Ok(FederationAuthorityObservationV2 {
                query_binding_digest: query.binding_digest(),
                lease_epoch: query.lease_epoch,
                observed_unix_ms,
                state,
            })
        })
    }
}

struct ProductAttemptControl {
    logical_start_ms: u64,
    started_at: Instant,
}

impl FederationAttemptControlV2 for ProductAttemptControl {
    fn wait_for_stop<'a>(&'a self, query: &'a FederatedQueryV2) -> FederationStopFuture<'a> {
        let current = elapsed_logical_ms(self.logical_start_ms, self.started_at);
        let remaining = query.deadline_unix_ms.saturating_sub(current);
        Box::pin(async move {
            if remaining > 0 {
                tokio::time::sleep(Duration::from_millis(remaining)).await;
            }
            FederationStopReasonV2::DeadlineExpired
        })
    }
}

fn build_product_query_and_lease(
    reader: &FederatedMemoryReader,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    logical_start_ms: u64,
    deadline_unix_ms: u64,
) -> Result<(FederatedQueryV2, FederatedLeaseV2), CognitiveStoreError> {
    let capability = reader.capability();
    let peer_id = StableId::new(capability.owner_agent_id().as_str().to_string())
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let principal_id = StableId::new(access.agent_id().as_str().to_string())
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let mut scope_bytes = serde_json::to_vec(capability.scope())
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    scope_bytes.extend_from_slice(access.workspace_sha256().as_str().as_bytes());
    let scope_digest = domain_digest32(b"hepta.memory-federation.product-scope.v2", &[&scope_bytes]);
    let purpose_digest = Digest32::of_bytes(PRODUCT_FEDERATION_PURPOSE);
    let generation_vector_digest = domain_digest32(
        b"hepta.memory-federation.product-generation.v2",
        &[
            capability.id().as_str().as_bytes(),
            &capability.generation().to_be_bytes(),
            &capability.revision().to_be_bytes(),
        ],
    );
    let query_digest = Digest32::of_bytes(request.query().as_bytes());
    let nonce_digest = product_attempt_nonce_digest(
        query_digest,
        capability.id().as_str(),
        logical_start_ms,
    )?;
    let query_id_digest = domain_digest32(
        b"hepta.memory-federation.product-query-id.v2",
        &[nonce_digest.as_array(), peer_id.as_str().as_bytes()],
    );
    let query_id = StableId::new(format!("query:{query_id_digest}"))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let query = FederatedQueryV2 {
        query_id,
        peer_id,
        principal_id,
        scope_digest,
        purpose_digest,
        generation_vector_digest,
        query_digest,
        maximum_results: u32::try_from(MAX_RETRIEVAL_RESULTS).unwrap_or(u32::MAX),
        deadline_unix_ms,
        lease_epoch: capability.generation(),
        nonce_digest,
    };
    let lease_id = StableId::new(format!("lease:{}", query.binding_digest()))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let lease = FederatedLeaseV2 {
        lease_id,
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        lease_epoch: query.lease_epoch,
        expires_unix_ms: capability_expiry_ms(capability)?,
        revoked: false,
    };
    Ok((query, lease))
}

fn product_evidence_item(
    candidate: &FederatedRetrievalCandidate,
) -> Result<FederatedEvidenceItemV2, FederationV2Error> {
    let source_owner_id = StableId::new(candidate.source_agent_id.as_str().to_string())
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let record_id = StableId::new(candidate.candidate.memory.id.memory_id.as_str().to_string())
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let record_revision = Revision::new(candidate.candidate.memory.id.revision)
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let record_digest = Digest32::from_str(candidate.candidate.memory.content_sha256.as_str())
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let binding = serde_json::to_vec(&candidate.revalidation)
        .map_err(|_| FederationV2Error::TransportRejected)?;
    Ok(FederatedEvidenceItemV2 {
        source_owner_id,
        record_id,
        record_revision,
        record_digest,
        support_digest: domain_digest32(
            b"hepta.memory-federation.product-support.v2",
            &[&binding],
        ),
        validity_digest: domain_digest32(
            b"hepta.memory-federation.product-validity.v2",
            &[&binding],
        ),
    })
}

fn product_attempt_nonce_digest(
    query_digest: Digest32,
    capability_id: &str,
    logical_start_ms: u64,
) -> Result<Digest32, CognitiveStoreError> {
    let attempt_sequence = PRODUCT_FEDERATION_ATTEMPT_SEQUENCE
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| value.checked_add(1))
        .map_err(|_| {
            CognitiveStoreError::Unavailable(
                "memory federation attempt sequence exhausted".to_string(),
            )
        })?;
    let wall_clock_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    let process_id = u64::from(std::process::id());
    Ok(domain_digest32(
        b"hepta.memory-federation.product-nonce.v2",
        &[
            query_digest.as_array(),
            capability_id.as_bytes(),
            &logical_start_ms.to_be_bytes(),
            &attempt_sequence.to_be_bytes(),
            &wall_clock_nanos.to_be_bytes(),
            &process_id.to_be_bytes(),
        ],
    ))
}

fn capability_expiry_ms(capability: &FederationCapability) -> Result<u64, CognitiveStoreError> {
    seconds_to_ms(capability.expires_at_unix_seconds())
}

fn seconds_to_ms(value: i64) -> Result<u64, CognitiveStoreError> {
    let value = u64::try_from(value).map_err(|_| {
        CognitiveStoreError::Invalid("memory federation time must be non-negative".to_string())
    })?;
    value.checked_mul(1_000).ok_or_else(|| {
        CognitiveStoreError::Invalid("memory federation time overflow".to_string())
    })
}

fn elapsed_logical_ms(logical_start_ms: u64, started_at: Instant) -> u64 {
    logical_start_ms.saturating_add(
        u64::try_from(started_at.elapsed().as_millis()).unwrap_or(u64::MAX),
    )
}

fn domain_digest32(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(domain);
    for part in parts {
        bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod product_nonce_tests {
    use super::*;

    #[test]
    fn repeated_product_attempts_receive_distinct_nonce_digests() {
        let query_digest = Digest32::of_bytes(b"same-query");
        let first = product_attempt_nonce_digest(query_digest, "federation:v1:test", 123_000)
            .expect("first nonce");
        let second = product_attempt_nonce_digest(query_digest, "federation:v1:test", 123_000)
            .expect("second nonce");
        assert_ne!(first, second);
    }
}

impl fmt::Debug for CognitiveRuntime {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Absent => formatter.write_str("CognitiveRuntime::Absent"),
            Self::Available(_) => formatter.write_str("CognitiveRuntime::Available(<owned store>)"),
            Self::AvailableFederated { .. } => formatter.write_str(
                "CognitiveRuntime::AvailableFederated(<owned store>, <legacy read-only sources>)",
            ),
            Self::AvailableFederatedV2 { .. } => formatter.write_str(
                "CognitiveRuntime::AvailableFederatedV2(<owned store>, <canonical read-only sources>)",
            ),
            Self::Unavailable(reason) => formatter
                .debug_tuple("CognitiveRuntime::Unavailable")
                .field(reason)
                .finish(),
        }
    }
}

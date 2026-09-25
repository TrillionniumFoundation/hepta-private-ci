use std::collections::BTreeSet;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use futures::StreamExt;
use futures::future::join_all;
use futures::stream;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory_federation::FederatedCompletenessV2;
use codex_hepta_memory_federation::FederatedCoverageV2;
use codex_hepta_memory_federation::FederatedEvidenceItemV2;
use codex_hepta_memory_federation::FederatedFailureCoverageV2;
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

#[path = "cognitive_runtime_identity.rs"]
mod identity;

#[cfg(test)]
#[path = "cognitive_federation_discovery_tests.rs"]
mod discovery_tests;

const PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(2);
const PRODUCT_FEDERATION_DISCOVERY_BUDGET: Duration = Duration::from_secs(1);
const PRODUCT_FEDERATION_OWNER_DISCOVERY_BUDGET: Duration = Duration::from_millis(250);
const PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY: usize = 8;
const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;
const PRODUCT_FEDERATION_PURPOSE: &[u8] = b"hepta.cognitive.federated-recall.product.v2";
static PRODUCT_FEDERATION_ATTEMPT_SEQUENCE: AtomicU64 = AtomicU64::new(1);

pub(crate) type ProductDiscoveryFuture<'a> = Pin<
    Box<dyn Future<Output = Result<Vec<FederatedMemoryReader>, CognitiveStoreError>> + Send + 'a>,
>;
pub(crate) type ProductDiscoverer =
    for<'a> fn(&'a HeptaAgentLayout, &'a AgentId, i64) -> ProductDiscoveryFuture<'a>;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum ProductDiscoveryFailureKind {
    Unavailable,
    Deadline,
}

#[derive(Debug)]
struct ProductDiscoveryFailure {
    owner_agent_id: AgentId,
    kind: ProductDiscoveryFailureKind,
}

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
        omitted_owner_candidates: u32,
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
            Self::AvailableFederated { store, .. } | Self::AvailableFederatedV2 { store, .. } => {
                Some(store)
            }
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
            Self::Available(store) | Self::AvailableFederated { store, .. } => {
                Self::AvailableFederated {
                    store,
                    federation: Arc::new(federation),
                }
            }
            runtime @ Self::AvailableFederatedV2 { .. } => runtime,
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
        let omitted_owner_candidates = u32::try_from(
            owner_layouts
                .len()
                .saturating_sub(MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS),
        )
        .unwrap_or(u32::MAX);
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
                omitted_owner_candidates,
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

    /// Returns true only for the canonical V2 federation composition admitted
    /// to product model-input assembly. Legacy federation may remain available
    /// through explicit compatibility APIs, but it must not be selected by a
    /// product caller through a generic "has federation" check.
    pub fn has_product_federation(&self) -> bool {
        matches!(
            self,
            Self::AvailableFederatedV2 { owner_layouts, .. } if !owner_layouts.is_empty()
        )
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
                        truncated_peers: 0,
                        omitted_peer_candidates: 0,
                        truncated_items: 0,
                        failures: FederatedFailureCoverageV2::default(),
                    },
                ))
            }
            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                omitted_owner_candidates,
                ..
            } => {
                retrieve_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    *omitted_owner_candidates,
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

    /// Executes only the canonical V2 product federation path.
    ///
    /// This deliberately rejects the legacy compatibility variant so product
    /// model-input callers cannot silently inherit its older failure semantics.
    pub async fn retrieve_product_federated(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<(FederatedRetrievalBatch, FederatedCoverageV2), CognitiveStoreError> {
        match self {
            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                omitted_owner_candidates,
                ..
            } => {
                retrieve_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    *omitted_owner_candidates,
                    access,
                    request,
                )
                .await
            }
            Self::Absent
            | Self::Available(_)
            | Self::AvailableFederated { .. }
            | Self::Unavailable(_) => Err(CognitiveStoreError::AccessDenied(
                "canonical memory federation V2 is unavailable".to_string(),
            )),
        }
    }

    /// Revalidates a product attachment only through canonical V2 composition.
    pub async fn revalidate_product_federated(
        &self,
        access: &FederationConsumerAccess,
        binding: &FederatedMemoryRevalidationBinding,
        now_unix_seconds: i64,
    ) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
        self.revalidate_product_federated_batch(
            access,
            std::slice::from_ref(binding),
            now_unix_seconds,
        )
        .await?
        .pop()
        .ok_or_else(|| {
            CognitiveStoreError::Corrupt(
                "single product federation revalidation returned no status".to_string(),
            )
        })
    }

    /// Revalidates the full prepared product attachment under one bounded
    /// operation. Bindings from the same owner/capability share one SQLite read
    /// snapshot; different owners remain independent federation snapshots.
    pub async fn revalidate_product_federated_batch(
        &self,
        access: &FederationConsumerAccess,
        bindings: &[FederatedMemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> Result<Vec<FederatedRevalidationStatus>, CognitiveStoreError> {
        match self {
            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                ..
            } => {
                revalidate_federated_product_batch(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    access,
                    bindings,
                    now_unix_seconds,
                )
                .await
            }
            Self::Absent
            | Self::Available(_)
            | Self::AvailableFederated { .. }
            | Self::Unavailable(_) => Err(CognitiveStoreError::AccessDenied(
                "canonical memory federation V2 is unavailable".to_string(),
            )),
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
                federation
                    .revalidate(access, binding, now_unix_seconds)
                    .await
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

fn discover_product_owner<'a>(
    owner_layout: &'a HeptaAgentLayout,
    consumer_agent_id: &'a AgentId,
    now_unix_seconds: i64,
) -> ProductDiscoveryFuture<'a> {
    Box::pin(FederatedMemoryReader::discover(
        owner_layout,
        consumer_agent_id,
        now_unix_seconds,
    ))
}

async fn retrieve_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    omitted_owner_candidates: u32,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
) -> Result<(FederatedRetrievalBatch, FederatedCoverageV2), CognitiveStoreError> {
    retrieve_federated_product_with_discoverer(
        consumer_agent_id,
        owner_layouts,
        omitted_owner_candidates,
        access,
        request,
        PRODUCT_FEDERATION_DISCOVERY_BUDGET,
        discover_product_owner,
    )
    .await
}

pub(crate) async fn retrieve_federated_product_with_discoverer(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    omitted_owner_candidates: u32,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    discovery_budget: Duration,
    discoverer: ProductDiscoverer,
) -> Result<(FederatedRetrievalBatch, FederatedCoverageV2), CognitiveStoreError> {
    if access.agent_id() != consumer_agent_id {
        return Err(CognitiveStoreError::AccessDenied(
            "memory federation caller does not match the product consumer".to_string(),
        ));
    }

    if owner_layouts.len() > MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS {
        return Err(CognitiveStoreError::Invalid(
            "memory federation owner candidates exceed the product bound".to_string(),
        ));
    }
    let logical_start_ms = seconds_to_ms(request.now_unix_seconds())?;
    let started_at = Instant::now();
    let global_deadline_ms = logical_start_ms
        .checked_add(u64::try_from(PRODUCT_FEDERATION_TOTAL_BUDGET.as_millis()).unwrap_or(u64::MAX))
        .ok_or_else(|| CognitiveStoreError::Invalid("federation deadline overflow".to_string()))?;

    let discovery_budget =
        discovery_budget.min(PRODUCT_FEDERATION_TOTAL_BUDGET.saturating_sub(started_at.elapsed()));
    let discovery_started = Instant::now();
    let mut pending_owner_ids = owner_layouts
        .iter()
        .map(|owner_layout| owner_layout.agent_id().clone())
        .collect::<BTreeSet<_>>();
    let mut pending = stream::iter(owner_layouts.iter().cloned())
        .map(|owner_layout| async move {
            let outcome = tokio::time::timeout(
                PRODUCT_FEDERATION_OWNER_DISCOVERY_BUDGET,
                discoverer(&owner_layout, consumer_agent_id, request.now_unix_seconds()),
            )
            .await;
            (owner_layout, outcome)
        })
        .buffer_unordered(PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY);

    let mut readers = Vec::new();
    let mut discovery_failures = Vec::new();
    while !pending_owner_ids.is_empty() {
        let remaining = discovery_budget.saturating_sub(discovery_started.elapsed());
        if remaining.is_zero() {
            break;
        }
        let next = tokio::time::timeout(remaining, pending.next()).await;
        let (owner_layout, outcome) = match next {
            Ok(Some(completed)) => completed,
            Ok(None) => break,
            Err(_) => break,
        };
        pending_owner_ids.remove(owner_layout.agent_id());
        match outcome {
            Ok(Ok(discovered)) => {
                for reader in discovered {
                    if reader.capability().scope().consumer_workspace_sha256()
                        != access.workspace_sha256()
                    {
                        continue;
                    }
                    readers.push((owner_layout.clone(), reader));
                }
            }
            Ok(Err(_)) => discovery_failures.push(ProductDiscoveryFailure {
                owner_agent_id: owner_layout.agent_id().clone(),
                kind: ProductDiscoveryFailureKind::Unavailable,
            }),
            Err(_) => discovery_failures.push(ProductDiscoveryFailure {
                owner_agent_id: owner_layout.agent_id().clone(),
                kind: ProductDiscoveryFailureKind::Deadline,
            }),
        }
    }
    drop(pending);
    discovery_failures.extend(pending_owner_ids.into_iter().map(|owner_agent_id| {
        ProductDiscoveryFailure {
            owner_agent_id,
            kind: ProductDiscoveryFailureKind::Deadline,
        }
    }));
    discovery_failures.sort_by(|left, right| {
        left.owner_agent_id
            .cmp(&right.owner_agent_id)
            .then_with(|| left.kind.cmp(&right.kind))
    });
    readers.sort_by(|(_, left), (_, right)| {
        left.capability()
            .owner_agent_id()
            .cmp(right.capability().owner_agent_id())
            .then_with(|| left.capability().id().cmp(right.capability().id()))
    });
    readers.dedup_by(|(_, left), (_, right)| left.capability().id() == right.capability().id());
    let observable_peer_slots = readers.len().saturating_add(discovery_failures.len());
    let truncated_peers = observable_peer_slots.saturating_sub(MAX_FEDERATION_SOURCES_PER_AGENT);
    readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);

    let discovery_failure_slots = discovery_failures
        .len()
        .min(MAX_FEDERATION_SOURCES_PER_AGENT.saturating_sub(readers.len()));
    let selected_discovery_failures = &discovery_failures[..discovery_failure_slots];
    let discovery_unavailable = selected_discovery_failures
        .iter()
        .filter(|failure| failure.kind == ProductDiscoveryFailureKind::Unavailable)
        .count();
    let discovery_deadline = selected_discovery_failures
        .iter()
        .filter(|failure| failure.kind == ProductDiscoveryFailureKind::Deadline)
        .count();
    let requested_peer_slots = readers.len().saturating_add(discovery_failure_slots);
    let query_sha256 = Sha256Digest::for_bytes(request.query().as_bytes());
    let mut coverage = FederatedCoverageV2 {
        requested_peers: u32::try_from(requested_peer_slots).unwrap_or(u32::MAX),
        completed_peers: 0,
        failed_peers: u32::try_from(discovery_failure_slots).unwrap_or(u32::MAX),
        truncated_peers: u32::try_from(truncated_peers).unwrap_or(u32::MAX),
        omitted_peer_candidates: omitted_owner_candidates,
        truncated_items: 0,
        failures: FederatedFailureCoverageV2 {
            discovery_unavailable: u32::try_from(discovery_unavailable).unwrap_or(u32::MAX),
            deadline_or_cancelled: u32::try_from(discovery_deadline).unwrap_or(u32::MAX),
            ..FederatedFailureCoverageV2::default()
        },
    };
    let mut candidates = Vec::new();

    let attempts = join_all(readers.iter().map(|(owner_layout, reader)| async move {
        if elapsed_logical_ms(logical_start_ms, started_at) >= global_deadline_ms {
            return Ok((
                Err(FederationV2Error::DeadlineExpired),
                Arc::new(Mutex::new(None)),
            ));
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
            expected_owner_generation_sha256: reader.owner_generation_sha256(),
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
        Ok::<_, CognitiveStoreError>((result, captured))
    }))
    .await;

    for attempt in attempts {
        let (result, captured) = attempt?;
        let result = match result {
            Ok(result) => result,
            Err(error) => {
                coverage.failed_peers = coverage.failed_peers.saturating_add(1);
                record_product_failure(&mut coverage.failures, &error);
                continue;
            }
        };
        merge_product_coverage(&mut coverage, &result.coverage, result.validity);
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

fn merge_product_coverage(
    aggregate: &mut FederatedCoverageV2,
    attempt: &FederatedCoverageV2,
    validity: FederatedValidityV2,
) {
    aggregate.truncated_peers = aggregate
        .truncated_peers
        .saturating_add(attempt.truncated_peers);
    aggregate.omitted_peer_candidates = aggregate
        .omitted_peer_candidates
        .saturating_add(attempt.omitted_peer_candidates);
    aggregate.truncated_items = aggregate
        .truncated_items
        .saturating_add(attempt.truncated_items);
    merge_failure_coverage(&mut aggregate.failures, &attempt.failures);
    if validity == FederatedValidityV2::Valid {
        aggregate.completed_peers = aggregate
            .completed_peers
            .saturating_add(attempt.completed_peers);
        aggregate.failed_peers = aggregate.failed_peers.saturating_add(attempt.failed_peers);
    } else {
        aggregate.failed_peers = aggregate
            .failed_peers
            .saturating_add(attempt.failed_peers)
            .saturating_add(attempt.completed_peers);
        aggregate.failures.authority_rejected = aggregate
            .failures
            .authority_rejected
            .saturating_add(attempt.completed_peers);
    }
}

fn merge_failure_coverage(
    aggregate: &mut FederatedFailureCoverageV2,
    attempt: &FederatedFailureCoverageV2,
) {
    aggregate.discovery_unavailable = aggregate
        .discovery_unavailable
        .saturating_add(attempt.discovery_unavailable);
    aggregate.deadline_or_cancelled = aggregate
        .deadline_or_cancelled
        .saturating_add(attempt.deadline_or_cancelled);
    aggregate.authority_rejected = aggregate
        .authority_rejected
        .saturating_add(attempt.authority_rejected);
    aggregate.integrity_rejected = aggregate
        .integrity_rejected
        .saturating_add(attempt.integrity_rejected);
    aggregate.transport_unavailable = aggregate
        .transport_unavailable
        .saturating_add(attempt.transport_unavailable);
}

fn record_product_failure(failures: &mut FederatedFailureCoverageV2, error: &FederationV2Error) {
    match error {
        FederationV2Error::DeadlineExpired
        | FederationV2Error::AttemptCancelled
        | FederationV2Error::LeaseExpired
        | FederationV2Error::ResponseExpired => {
            failures.deadline_or_cancelled = failures.deadline_or_cancelled.saturating_add(1);
        }
        FederationV2Error::LeaseRevoked
        | FederationV2Error::LeaseEpochMismatch
        | FederationV2Error::AuthorityObservationRegressed
        | FederationV2Error::AuthorityExpired
        | FederationV2Error::LeaseAuthorityHorizonExceeded
        | FederationV2Error::AuthorityNotCurrent(_)
        | FederationV2Error::AuthorityGranted
        | FederationV2Error::AuthorityRevalidationFailed => {
            failures.authority_rejected = failures.authority_rejected.saturating_add(1);
        }
        FederationV2Error::TransportRejected => {
            failures.transport_unavailable = failures.transport_unavailable.saturating_add(1);
        }
        FederationV2Error::ZeroValue(_)
        | FederationV2Error::EmptyDigest(_)
        | FederationV2Error::InvalidMaximumResults
        | FederationV2Error::IdentityMismatch(_)
        | FederationV2Error::DigestMismatch(_)
        | FederationV2Error::MissingTerminalObservation
        | FederationV2Error::ResultLimitExceeded
        | FederationV2Error::DuplicateResultIdentity
        | FederationV2Error::InvalidCompleteness
        | FederationV2Error::InvalidCoverage
        | FederationV2Error::StaleEvidenceExposed => {
            failures.integrity_rejected = failures.integrity_rejected.saturating_add(1);
        }
    }
}

async fn revalidate_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    access: &FederationConsumerAccess,
    binding: &FederatedMemoryRevalidationBinding,
    now_unix_seconds: i64,
) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
    revalidate_federated_product_batch(
        consumer_agent_id,
        owner_layouts,
        access,
        std::slice::from_ref(binding),
        now_unix_seconds,
    )
    .await?
    .pop()
    .ok_or_else(|| {
        CognitiveStoreError::Corrupt(
            "single federated product revalidation returned no status".to_string(),
        )
    })
}

async fn revalidate_federated_product_batch(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    access: &FederationConsumerAccess,
    bindings: &[FederatedMemoryRevalidationBinding],
    now_unix_seconds: i64,
) -> Result<Vec<FederatedRevalidationStatus>, CognitiveStoreError> {
    if owner_layouts.len() > MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS
        || bindings.len() > MAX_RETRIEVAL_RESULTS
    {
        return Err(CognitiveStoreError::Invalid(
            "memory federation final revalidation exceeds product bounds".to_string(),
        ));
    }
    if bindings.is_empty() {
        return Ok(Vec::new());
    }
    if access.agent_id() != consumer_agent_id {
        return Ok(vec![
            FederatedRevalidationStatus::Stale(
                FederationRevalidationDrift::Consumer
            );
            bindings.len()
        ]);
    }
    let revalidation = async {
        let mut statuses = vec![None; bindings.len()];

        for owner_layout in owner_layouts {
            let owner_indices = bindings
                .iter()
                .enumerate()
                .filter_map(|(index, binding)| {
                    (binding.source_agent_id == *owner_layout.agent_id()).then_some(index)
                })
                .collect::<Vec<_>>();
            if owner_indices.is_empty() {
                continue;
            }

            let readers =
                FederatedMemoryReader::discover(owner_layout, consumer_agent_id, now_unix_seconds)
                    .await?;
            let capability_ids = owner_indices
                .iter()
                .map(|index| bindings[*index].capability.id().as_str())
                .collect::<BTreeSet<_>>();

            for capability_id in capability_ids {
                let group_indices = owner_indices
                    .iter()
                    .copied()
                    .filter(|index| bindings[*index].capability.id().as_str() == capability_id)
                    .collect::<Vec<_>>();
                let Some(reader) = readers
                    .iter()
                    .find(|reader| reader.capability().id().as_str() == capability_id)
                else {
                    for index in group_indices {
                        statuses[index] = Some(FederatedRevalidationStatus::Stale(
                            FederationRevalidationDrift::CapabilityMissing,
                        ));
                    }
                    continue;
                };
                let group_bindings = group_indices
                    .iter()
                    .map(|index| bindings[*index].clone())
                    .collect::<Vec<_>>();
                let group_statuses = reader
                    .revalidate_many(access, &group_bindings, now_unix_seconds)
                    .await?;
                if group_statuses.len() != group_indices.len() {
                    return Err(CognitiveStoreError::Corrupt(
                        "product federation batch revalidation changed result cardinality"
                            .to_string(),
                    ));
                }
                for (index, status) in group_indices.into_iter().zip(group_statuses) {
                    statuses[index] = Some(status);
                }
            }
        }

        Ok(statuses
            .into_iter()
            .map(|status| {
                status.unwrap_or(FederatedRevalidationStatus::Stale(
                    FederationRevalidationDrift::CapabilityMissing,
                ))
            })
            .collect::<Vec<_>>())
    };

    tokio::time::timeout(PRODUCT_FEDERATION_TOTAL_BUDGET, revalidation)
        .await
        .map_err(|_| {
            CognitiveStoreError::Unavailable(
                "memory federation final batch revalidation timed out".to_string(),
            )
        })?
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
            let (batch, observed_frontier) = self
                .reader
                .retrieve_with_frontier(self.access, self.request)
                .await
                .map_err(|error| match error {
                    CognitiveStoreError::AccessDenied(_) => {
                        FederationV2Error::AuthorityRevalidationFailed
                    }
                    _ => FederationV2Error::TransportRejected,
                })?;
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
                observed_frontier,
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
    expected_owner_generation_sha256: &'a Sha256Digest,
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
                Some(reader)
                    if reader.capability() == self.expected_capability
                        && reader.owner_generation_sha256()
                            == self.expected_owner_generation_sha256 =>
                {
                    FederationAuthorityStateV2::Current
                }
                Some(_) => FederationAuthorityStateV2::StaleGeneration,
            };
            let authority_capability =
                current.map_or(self.expected_capability, |reader| reader.capability());
            let authority_expires_unix_ms = capability_expiry_ms(authority_capability)
                .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            Ok(FederationAuthorityObservationV2 {
                query_binding_digest: query.binding_digest(),
                lease_epoch: query.lease_epoch,
                observed_unix_ms,
                authority_expires_unix_ms,
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
    fn wait_for_stop<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
    ) -> FederationStopFuture<'a> {
        let current = elapsed_logical_ms(self.logical_start_ms, self.started_at);
        let authority_deadline = query.deadline_unix_ms.min(lease.expires_unix_ms);
        let remaining = authority_deadline.saturating_sub(current);
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
    let scope_digest =
        domain_digest32(b"hepta.memory-federation.product-scope.v2", &[&scope_bytes]);
    let purpose_digest = Digest32::of_bytes(PRODUCT_FEDERATION_PURPOSE);
    let generation_vector_digest = domain_digest32(
        b"hepta.memory-federation.product-generation.v2",
        &[
            reader.owner_generation_sha256().as_str().as_bytes(),
            capability.id().as_str().as_bytes(),
            &capability.generation().to_be_bytes(),
            &capability.revision().to_be_bytes(),
        ],
    );
    let query_digest = Digest32::of_bytes(request.query().as_bytes());
    let nonce_digest =
        product_attempt_nonce_digest(query_digest, capability.id().as_str(), logical_start_ms)?;
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
        support_digest: domain_digest32(b"hepta.memory-federation.product-support.v2", &[&binding]),
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
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
            value.checked_add(1)
        })
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
    value
        .checked_mul(1_000)
        .ok_or_else(|| CognitiveStoreError::Invalid("memory federation time overflow".to_string()))
}

fn elapsed_logical_ms(logical_start_ms: u64, started_at: Instant) -> u64 {
    logical_start_ms
        .saturating_add(u64::try_from(started_at.elapsed().as_millis()).unwrap_or(u64::MAX))
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

#[cfg(test)]
mod product_nonce_tests {
    use super::*;

    #[test]
    fn nonvalid_terminal_attempt_counts_as_failed_product_coverage() {
        let mut aggregate = FederatedCoverageV2 {
            requested_peers: 1,
            completed_peers: 0,
            failed_peers: 0,
            truncated_peers: 0,
            omitted_peer_candidates: 0,
            truncated_items: 0,
            failures: FederatedFailureCoverageV2::default(),
        };
        let attempt = FederatedCoverageV2 {
            requested_peers: 1,
            completed_peers: 1,
            failed_peers: 0,
            truncated_peers: 0,
            omitted_peer_candidates: 0,
            truncated_items: 0,
            failures: FederatedFailureCoverageV2::default(),
        };
        merge_product_coverage(&mut aggregate, &attempt, FederatedValidityV2::Revoked);
        assert_eq!(aggregate.completed_peers, 0);
        assert_eq!(aggregate.failed_peers, 1);
    }

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

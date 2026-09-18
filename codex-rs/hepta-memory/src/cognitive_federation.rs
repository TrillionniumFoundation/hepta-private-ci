use std::path::Path;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory_federation::FederatedCompletenessV2 as CanonicalCompletenessV2;
use codex_hepta_memory_federation::FederatedEvidenceItemV2 as CanonicalEvidenceItemV2;
use codex_hepta_memory_federation::FederatedLeaseV2 as CanonicalLeaseV2;
use codex_hepta_memory_federation::FederatedQueryV2 as CanonicalQueryV2;
use codex_hepta_memory_federation::FederatedValidityV2 as CanonicalValidityV2;
use codex_hepta_memory_federation::FederationAuthorityObservationV2 as CanonicalAuthorityObservationV2;
use codex_hepta_memory_federation::FederationAuthorityV2 as CanonicalAuthorityV2;
use codex_hepta_memory_federation::FederationCancellationV2 as CanonicalCancellationV2;
use codex_hepta_memory_federation::FederationTransportOutcomeV2 as CanonicalTransportOutcomeV2;
use codex_hepta_memory_federation::FederationTransportResultV2 as CanonicalTransportResultV2;
use codex_hepta_memory_federation::FederationTransportV2 as CanonicalTransportV2;
use codex_hepta_memory_federation::FederationV2Error as CanonicalFederationError;
use codex_hepta_memory_federation::FederationV2Future as CanonicalFutureV2;
use codex_hepta_memory_federation::RemoteFederatedResponseV2 as CanonicalResponseV2;
use codex_hepta_memory_federation::execute_once as execute_canonical_federation_v2;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_types::Digest32 as CanonicalDigest32;
use codex_hepta_types::Revision as CanonicalRevision;
use codex_hepta_types::StableId as CanonicalStableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;
use tokio::sync::Mutex;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryExplanation;
use crate::MemoryRevalidationBinding;
use crate::RetrievalCandidate;
use crate::RetrievalRequest;
use crate::RevalidationStatus;
use crate::cognitive_path::canonical_path_without_redirection;
use crate::cognitive_store::unavailable;
use crate::framing::frame_part;

pub const MAX_FEDERATION_CAPABILITIES_PER_STORE: u64 = 128;
pub const MAX_FEDERATION_CAPABILITY_REVISIONS: u64 = 1024;
pub const MAX_FEDERATION_GRANT_LIFETIME_SECONDS: i64 = 31 * 24 * 60 * 60;
pub const MAX_FEDERATION_SOURCES_PER_AGENT: usize = 16;
const MAX_FEDERATION_OWNER_LAYOUTS_PER_AGENT: usize = 128;
const FEDERATION_REFRESH_TIMEOUT: Duration = Duration::from_secs(2);
const FEDERATION_READ_TIMEOUT_MS: u64 = 2_000;

const COGNITIVE_DB_FILENAME: &str = "cognitive_1.sqlite3";
const CAPABILITY_ID_PREFIX: &str = "federation:v1:";

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct FederationCapabilityId(String);

impl FederationCapabilityId {
    fn for_binding(
        owner_agent_id: &AgentId,
        consumer_agent_id: &AgentId,
        scope: &FederationGrantScope,
    ) -> Self {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, b"hepta:cognitive:federation-capability:v1");
        frame_part(&mut hasher, owner_agent_id.as_str().as_bytes());
        frame_part(&mut hasher, consumer_agent_id.as_str().as_bytes());
        let (scope_kind, owner_workspace) = scope.owner_scope.database_parts();
        frame_part(&mut hasher, scope_kind.as_bytes());
        frame_part(&mut hasher, owner_workspace.unwrap_or_default().as_bytes());
        frame_part(
            &mut hasher,
            scope.consumer_workspace_sha256.as_str().as_bytes(),
        );
        Self(format!("{CAPABILITY_ID_PREFIX}{:x}", hasher.finalize()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn parse(value: String) -> Result<Self, CognitiveStoreError> {
        let digest = value.strip_prefix(CAPABILITY_ID_PREFIX).ok_or_else(|| {
            CognitiveStoreError::Corrupt("invalid memory federation capability id".to_string())
        })?;
        Sha256Digest::parse(digest.to_string()).map_err(CognitiveStoreError::Corrupt)?;
        Ok(Self(value))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FederationCapabilityState {
    Granted,
    Revoked,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederationCapabilityStatus {
    pub capability: FederationCapability,
    pub state: FederationCapabilityState,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederationGrantScope {
    owner_scope: CognitiveScope,
    consumer_workspace_sha256: Sha256Digest,
}

impl FederationGrantScope {
    pub fn new(owner_scope: CognitiveScope, consumer_workspace_sha256: Sha256Digest) -> Self {
        Self {
            owner_scope,
            consumer_workspace_sha256,
        }
    }

    pub fn owner_scope(&self) -> &CognitiveScope {
        &self.owner_scope
    }

    pub fn consumer_workspace_sha256(&self) -> &Sha256Digest {
        &self.consumer_workspace_sha256
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationGrantRequest {
    pub consumer_agent_id: AgentId,
    pub scope: FederationGrantScope,
    pub effective_at_unix_seconds: i64,
    pub expires_at_unix_seconds: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederationCapability {
    id: FederationCapabilityId,
    owner_agent_id: AgentId,
    consumer_agent_id: AgentId,
    scope: FederationGrantScope,
    generation: u64,
    revision: u64,
    effective_at_unix_seconds: i64,
    expires_at_unix_seconds: i64,
}

impl FederationCapability {
    pub fn id(&self) -> &FederationCapabilityId {
        &self.id
    }

    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }

    pub fn consumer_agent_id(&self) -> &AgentId {
        &self.consumer_agent_id
    }

    pub fn scope(&self) -> &FederationGrantScope {
        &self.scope
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub fn effective_at_unix_seconds(&self) -> i64 {
        self.effective_at_unix_seconds
    }

    pub fn expires_at_unix_seconds(&self) -> i64 {
        self.expires_at_unix_seconds
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederationRevocation {
    pub capability_id: FederationCapabilityId,
    pub generation: u64,
    pub revision: u64,
    pub revoked_at_unix_seconds: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationConsumerAccess {
    agent_id: AgentId,
    workspace_sha256: Sha256Digest,
}

impl FederationConsumerAccess {
    pub fn new(agent_id: AgentId, workspace_sha256: Sha256Digest) -> Self {
        Self {
            agent_id,
            workspace_sha256,
        }
    }

    pub fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    pub fn workspace_sha256(&self) -> &Sha256Digest {
        &self.workspace_sha256
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FederationRevalidationDrift {
    CapabilityMissing,
    CapabilityRevision,
    CapabilityGeneration,
    Revoked,
    NotYetEffective,
    Expired,
    Consumer,
    Scope,
    Memory,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedMemoryRevalidationBinding {
    pub source_agent_id: AgentId,
    pub capability: FederationCapability,
    pub memory: MemoryRevalidationBinding,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedRetrievalCandidate {
    pub source_agent_id: AgentId,
    pub candidate: RetrievalCandidate,
    pub revalidation: FederatedMemoryRevalidationBinding,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedRetrievalCoverage {
    pub requested_sources: u32,
    pub completed_sources: u32,
    pub failed_sources: u32,
    pub discovery_failures: u32,
}

impl FederatedRetrievalCoverage {
    pub fn is_partial(&self) -> bool {
        self.failed_sources > 0
            || self.discovery_failures > 0
            || self.completed_sources.saturating_add(self.failed_sources) < self.requested_sources
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedRetrievalBatch {
    pub query_sha256: Sha256Digest,
    pub candidates: Vec<FederatedRetrievalCandidate>,
    pub coverage: FederatedRetrievalCoverage,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedMemoryExplanation {
    pub source_agent_id: AgentId,
    pub capability: FederationCapability,
    pub explanation: MemoryExplanation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederatedRevalidationStatus {
    Current(Box<FederatedMemoryExplanation>),
    Stale(FederationRevalidationDrift),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FederationAction {
    Grant,
    Revoke,
}

impl FederationAction {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Grant => "grant",
            Self::Revoke => "revoke",
        }
    }

    fn parse(value: &str) -> Result<Self, CognitiveStoreError> {
        match value {
            "grant" => Ok(Self::Grant),
            "revoke" => Ok(Self::Revoke),
            _ => Err(CognitiveStoreError::Corrupt(
                "invalid memory federation action".to_string(),
            )),
        }
    }
}

struct StoredCapabilityEvent {
    capability: FederationCapability,
    action: FederationAction,
}

impl CognitiveStore {
    pub async fn grant_federated_recall(
        &self,
        owner_access: &CognitiveAccess,
        request: &FederationGrantRequest,
    ) -> Result<FederationCapability, CognitiveStoreError> {
        self.authorize(owner_access, request.scope.owner_scope())?;
        if request.consumer_agent_id == self.owner_agent_id {
            return Err(CognitiveStoreError::Invalid(
                "memory federation consumer must be a different agent".to_string(),
            ));
        }
        let lifetime = request
            .expires_at_unix_seconds
            .checked_sub(request.effective_at_unix_seconds)
            .ok_or_else(|| {
                CognitiveStoreError::Invalid("memory federation lifetime overflow".to_string())
            })?;
        if !(1..=MAX_FEDERATION_GRANT_LIFETIME_SECONDS).contains(&lifetime) {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation lifetime must be 1..={MAX_FEDERATION_GRANT_LIFETIME_SECONDS} seconds"
            )));
        }
        let capability_id = FederationCapabilityId::for_binding(
            &self.owner_agent_id,
            &request.consumer_agent_id,
            &request.scope,
        );
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let previous = sqlx::query(
            "SELECT e.*, e.owner_workspace_sha256 AS workspace_sha256
             FROM memory_federation_heads h JOIN memory_federation_events e
               ON e.capability_id = h.capability_id AND e.revision = h.revision
             WHERE h.capability_id = ?",
        )
        .bind(capability_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .map(decode_event)
        .transpose()?;
        let (revision, generation) = match previous {
            None => {
                let identities: i64 =
                    sqlx::query_scalar("SELECT COUNT(*) FROM memory_federation_heads")
                        .fetch_one(&mut *transaction)
                        .await
                        .map_err(unavailable)?;
                if identities
                    >= to_i64(
                        MAX_FEDERATION_CAPABILITIES_PER_STORE,
                        "federation capability count",
                    )?
                {
                    return Err(CognitiveStoreError::Invalid(
                        "memory federation capability store is full".to_string(),
                    ));
                }
                (1, 1)
            }
            Some(previous) => {
                require_stable_binding(
                    &previous.capability,
                    &self.owner_agent_id,
                    &request.consumer_agent_id,
                    &request.scope,
                )?;
                if previous.action == FederationAction::Grant
                    && request.effective_at_unix_seconds
                        < previous.capability.expires_at_unix_seconds
                {
                    return Err(CognitiveStoreError::Conflict(
                        "an overlapping memory federation grant is already active".to_string(),
                    ));
                }
                let revision = previous.capability.revision.checked_add(1).ok_or_else(|| {
                    CognitiveStoreError::Conflict("memory federation revision overflow".to_string())
                })?;
                let generation =
                    previous
                        .capability
                        .generation
                        .checked_add(1)
                        .ok_or_else(|| {
                            CognitiveStoreError::Conflict(
                                "memory federation generation overflow".to_string(),
                            )
                        })?;
                if revision > MAX_FEDERATION_CAPABILITY_REVISIONS {
                    return Err(CognitiveStoreError::Conflict(
                        "memory federation capability exhausted its revision bound".to_string(),
                    ));
                }
                (revision, generation)
            }
        };
        let capability = FederationCapability {
            id: capability_id,
            owner_agent_id: self.owner_agent_id.clone(),
            consumer_agent_id: request.consumer_agent_id.clone(),
            scope: request.scope.clone(),
            generation,
            revision,
            effective_at_unix_seconds: request.effective_at_unix_seconds,
            expires_at_unix_seconds: request.expires_at_unix_seconds,
        };
        insert_event(
            &mut transaction,
            &capability,
            FederationAction::Grant,
            request.effective_at_unix_seconds,
        )
        .await?;
        if revision == 1 {
            sqlx::query(
                "INSERT INTO memory_federation_heads (capability_id, revision) VALUES (?, ?)",
            )
            .bind(capability.id.as_str())
            .bind(to_i64(revision, "federation revision")?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
        } else {
            let updated = sqlx::query(
                "UPDATE memory_federation_heads SET revision = ?
                 WHERE capability_id = ? AND revision = ?",
            )
            .bind(to_i64(revision, "federation revision")?)
            .bind(capability.id.as_str())
            .bind(to_i64(revision - 1, "previous federation revision")?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if updated.rows_affected() != 1 {
                return Err(CognitiveStoreError::Conflict(
                    "memory federation head changed during grant".to_string(),
                ));
            }
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(capability)
    }

    pub async fn revoke_federated_recall(
        &self,
        owner_access: &CognitiveAccess,
        capability: &FederationCapability,
        revoked_at_unix_seconds: i64,
    ) -> Result<FederationRevocation, CognitiveStoreError> {
        self.authorize(owner_access, capability.scope.owner_scope())?;
        require_stable_binding(
            capability,
            &self.owner_agent_id,
            &capability.consumer_agent_id,
            &capability.scope,
        )?;
        let next_revision = capability.revision.checked_add(1).ok_or_else(|| {
            CognitiveStoreError::Conflict("memory federation revision overflow".to_string())
        })?;
        if next_revision > MAX_FEDERATION_CAPABILITY_REVISIONS {
            return Err(CognitiveStoreError::Conflict(
                "memory federation capability exhausted its revision bound".to_string(),
            ));
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let current = sqlx::query(
            "SELECT e.*, e.owner_workspace_sha256 AS workspace_sha256
             FROM memory_federation_heads h JOIN memory_federation_events e
               ON e.capability_id = h.capability_id AND e.revision = h.revision
             WHERE h.capability_id = ?",
        )
        .bind(capability.id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .ok_or_else(|| {
            CognitiveStoreError::Conflict("memory federation capability is missing".to_string())
        })
        .and_then(decode_event)?;
        if current.action != FederationAction::Grant || current.capability != *capability {
            return Err(CognitiveStoreError::Conflict(
                "memory federation capability is no longer the current grant".to_string(),
            ));
        }
        let revoked = FederationCapability {
            revision: next_revision,
            ..capability.clone()
        };
        insert_event(
            &mut transaction,
            &revoked,
            FederationAction::Revoke,
            revoked_at_unix_seconds,
        )
        .await?;
        let updated = sqlx::query(
            "UPDATE memory_federation_heads SET revision = ?
             WHERE capability_id = ? AND revision = ?",
        )
        .bind(to_i64(next_revision, "federation revision")?)
        .bind(capability.id.as_str())
        .bind(to_i64(capability.revision, "previous federation revision")?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(CognitiveStoreError::Conflict(
                "memory federation head changed during revoke".to_string(),
            ));
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(FederationRevocation {
            capability_id: capability.id.clone(),
            generation: capability.generation,
            revision: next_revision,
            revoked_at_unix_seconds,
        })
    }

    pub async fn revoke_federated_recall_by_id(
        &self,
        owner_access: &CognitiveAccess,
        capability_id: &FederationCapabilityId,
        revoked_at_unix_seconds: i64,
    ) -> Result<FederationRevocation, CognitiveStoreError> {
        let status = self
            .federation_capability_status(capability_id)
            .await?
            .ok_or_else(|| {
                CognitiveStoreError::Invalid(
                    "memory federation capability does not exist".to_string(),
                )
            })?;
        if status.state != FederationCapabilityState::Granted {
            return Err(CognitiveStoreError::Conflict(
                "memory federation capability is not an active grant".to_string(),
            ));
        }
        self.revoke_federated_recall(owner_access, &status.capability, revoked_at_unix_seconds)
            .await
    }

    pub async fn federation_capability_status(
        &self,
        capability_id: &FederationCapabilityId,
    ) -> Result<Option<FederationCapabilityStatus>, CognitiveStoreError> {
        let row = sqlx::query(
            "SELECT e.*, e.owner_workspace_sha256 AS workspace_sha256
             FROM memory_federation_heads h JOIN memory_federation_events e
               ON e.capability_id = h.capability_id AND e.revision = h.revision
             WHERE h.capability_id = ?",
        )
        .bind(capability_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?;
        row.map(decode_status).transpose()
    }

    pub async fn list_federation_capabilities(
        &self,
        limit: usize,
    ) -> Result<Vec<FederationCapabilityStatus>, CognitiveStoreError> {
        if !(1..=MAX_FEDERATION_CAPABILITIES_PER_STORE as usize).contains(&limit) {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation list limit must be 1..={MAX_FEDERATION_CAPABILITIES_PER_STORE}"
            )));
        }
        let rows = sqlx::query(
            "SELECT e.*, e.owner_workspace_sha256 AS workspace_sha256
             FROM memory_federation_heads h JOIN memory_federation_events e
               ON e.capability_id = h.capability_id AND e.revision = h.revision
             ORDER BY h.capability_id LIMIT ?",
        )
        .bind(to_i64(limit as u64, "federation list limit")?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.into_iter().map(decode_status).collect()
    }
}

#[derive(Clone)]
pub struct FederatedMemoryReader {
    owner: Arc<CognitiveStore>,
    capability: FederationCapability,
}

impl FederatedMemoryReader {
    pub async fn discover(
        owner_layout: &HeptaAgentLayout,
        consumer_agent_id: &AgentId,
        now_unix_seconds: i64,
    ) -> Result<Vec<Self>, CognitiveStoreError> {
        if owner_layout.agent_id() == consumer_agent_id {
            return Ok(Vec::new());
        }
        let database_path = owner_layout.cognitive_root().join(COGNITIVE_DB_FILENAME);
        let pool = open_read_only_pool(&database_path).await?;
        verify_read_only_store(&pool, owner_layout.agent_id()).await?;
        let rows = sqlx::query(
            "SELECT e.*, e.owner_workspace_sha256 AS workspace_sha256
             FROM memory_federation_heads h JOIN memory_federation_events e
               ON e.capability_id = h.capability_id AND e.revision = h.revision
             WHERE e.consumer_agent_id = ? ORDER BY e.capability_id",
        )
        .bind(consumer_agent_id.as_str())
        .fetch_all(&pool)
        .await
        .map_err(unavailable)?;
        let owner = Arc::new(CognitiveStore::from_read_only_pool(
            pool,
            owner_layout.agent_id().clone(),
            database_path,
        ));
        let mut readers = Vec::new();
        for row in rows {
            let event = decode_event(row)?;
            if event.capability.owner_agent_id != *owner_layout.agent_id()
                || event.capability.consumer_agent_id != *consumer_agent_id
            {
                return Err(CognitiveStoreError::Corrupt(
                    "memory federation event identity does not match its store query".to_string(),
                ));
            }
            if event.action == FederationAction::Grant
                && event.capability.effective_at_unix_seconds <= now_unix_seconds
                && now_unix_seconds < event.capability.expires_at_unix_seconds
            {
                readers.push(Self {
                    owner: Arc::clone(&owner),
                    capability: event.capability,
                });
            }
        }
        if readers.len() > MAX_FEDERATION_SOURCES_PER_AGENT {
            return Err(CognitiveStoreError::Corrupt(
                "consumer has more active memory federation sources than the product bound"
                    .to_string(),
            ));
        }
        Ok(readers)
    }

    pub fn capability(&self) -> &FederationCapability {
        &self.capability
    }

    pub async fn retrieve(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<FederatedRetrievalBatch, CognitiveStoreError> {
        require_authorized(
            self.validate_capability(access, request.now_unix_seconds())
                .await?,
        )?;
        let owner_access = owner_access(&self.capability);
        let mut batch = self
            .owner
            .retrieve_memory_candidates(&owner_access, request)
            .await?;
        batch
            .candidates
            .retain(|candidate| candidate.memory.scope == *self.capability.scope.owner_scope());
        require_authorized(
            self.validate_capability(access, request.now_unix_seconds())
                .await?,
        )?;
        let candidates = batch
            .candidates
            .into_iter()
            .map(|candidate| FederatedRetrievalCandidate {
                source_agent_id: self.capability.owner_agent_id.clone(),
                revalidation: FederatedMemoryRevalidationBinding {
                    source_agent_id: self.capability.owner_agent_id.clone(),
                    capability: self.capability.clone(),
                    memory: candidate.revalidation.clone(),
                },
                candidate,
            })
            .collect();
        Ok(FederatedRetrievalBatch {
            query_sha256: batch.query_sha256,
            candidates,
            coverage: FederatedRetrievalCoverage {
                requested_sources: 1,
                completed_sources: 1,
                failed_sources: 0,
                discovery_failures: 0,
            },
        })
    }

    pub async fn revalidate(
        &self,
        access: &FederationConsumerAccess,
        binding: &FederatedMemoryRevalidationBinding,
        now_unix_seconds: i64,
    ) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
        if binding.source_agent_id != self.capability.owner_agent_id
            || binding.capability != self.capability
        {
            return Ok(FederatedRevalidationStatus::Stale(
                FederationRevalidationDrift::CapabilityRevision,
            ));
        }
        if let Some(drift) = self.validate_capability(access, now_unix_seconds).await? {
            return Ok(FederatedRevalidationStatus::Stale(drift));
        }
        if binding.memory.scope != *self.capability.scope.owner_scope() {
            return Ok(FederatedRevalidationStatus::Stale(
                FederationRevalidationDrift::Scope,
            ));
        }
        let status = self
            .owner
            .revalidate_memory_candidate(
                &owner_access(&self.capability),
                &binding.memory,
                now_unix_seconds,
            )
            .await?;
        let RevalidationStatus::Current(explanation) = status else {
            return Ok(FederatedRevalidationStatus::Stale(
                FederationRevalidationDrift::Memory,
            ));
        };
        if let Some(drift) = self.validate_capability(access, now_unix_seconds).await? {
            return Ok(FederatedRevalidationStatus::Stale(drift));
        }
        Ok(FederatedRevalidationStatus::Current(Box::new(
            FederatedMemoryExplanation {
                source_agent_id: self.capability.owner_agent_id.clone(),
                capability: self.capability.clone(),
                explanation: *explanation,
            },
        )))
    }

    async fn validate_capability(
        &self,
        access: &FederationConsumerAccess,
        now_unix_seconds: i64,
    ) -> Result<Option<FederationRevalidationDrift>, CognitiveStoreError> {
        if access.agent_id != self.capability.consumer_agent_id {
            return Ok(Some(FederationRevalidationDrift::Consumer));
        }
        if access.workspace_sha256 != *self.capability.scope.consumer_workspace_sha256() {
            return Ok(Some(FederationRevalidationDrift::Scope));
        }
        let row = sqlx::query(
            "SELECT e.*, e.owner_workspace_sha256 AS workspace_sha256
             FROM memory_federation_heads h JOIN memory_federation_events e
               ON e.capability_id = h.capability_id AND e.revision = h.revision
             WHERE h.capability_id = ?",
        )
        .bind(self.capability.id.as_str())
        .fetch_optional(&self.owner.pool)
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Ok(Some(FederationRevalidationDrift::CapabilityMissing));
        };
        let current = decode_event(row)?;
        require_stable_binding(
            &current.capability,
            &self.capability.owner_agent_id,
            &self.capability.consumer_agent_id,
            &self.capability.scope,
        )?;
        if current.action == FederationAction::Revoke {
            return Ok(Some(FederationRevalidationDrift::Revoked));
        }
        if current.capability.generation != self.capability.generation {
            return Ok(Some(FederationRevalidationDrift::CapabilityGeneration));
        }
        if current.capability.revision != self.capability.revision
            || current.capability.effective_at_unix_seconds
                != self.capability.effective_at_unix_seconds
            || current.capability.expires_at_unix_seconds != self.capability.expires_at_unix_seconds
        {
            return Ok(Some(FederationRevalidationDrift::CapabilityRevision));
        }
        if now_unix_seconds < current.capability.effective_at_unix_seconds {
            return Ok(Some(FederationRevalidationDrift::NotYetEffective));
        }
        if now_unix_seconds >= current.capability.expires_at_unix_seconds {
            return Ok(Some(FederationRevalidationDrift::Expired));
        }
        Ok(None)
    }

    async fn observe_memory_frontier(&self) -> Result<u64, CognitiveStoreError> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM memory_revisions WHERE owner_agent_id = ?",
        )
        .bind(self.capability.owner_agent_id.as_str())
        .fetch_one(&self.owner.pool)
        .await
        .map_err(unavailable)?;
        from_i64(count, "memory federation observed frontier")?
            .checked_add(1)
            .ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "memory federation observed frontier overflow".to_string(),
                )
            })
    }
}

struct CurrentFederationReaders {
    readers: Vec<FederatedMemoryReader>,
    discovery_failures: u32,
}

#[derive(Clone)]
pub struct FederatedRecallSet {
    consumer_agent_id: AgentId,
    readers: Vec<FederatedMemoryReader>,
    owner_layouts: Vec<HeptaAgentLayout>,
    attempt_counter: Arc<AtomicU64>,
}

impl FederatedRecallSet {
    pub fn new(
        consumer_agent_id: AgentId,
        mut readers: Vec<FederatedMemoryReader>,
    ) -> Result<Self, CognitiveStoreError> {
        readers.sort_by(|left, right| {
            left.capability
                .owner_agent_id
                .cmp(&right.capability.owner_agent_id)
                .then_with(|| left.capability.id.cmp(&right.capability.id))
        });
        readers.dedup_by(|left, right| left.capability.id == right.capability.id);
        if readers.len() > MAX_FEDERATION_SOURCES_PER_AGENT
            || readers
                .iter()
                .any(|reader| reader.capability.consumer_agent_id != consumer_agent_id)
        {
            return Err(CognitiveStoreError::Invalid(
                "invalid memory federation reader set".to_string(),
            ));
        }
        Ok(Self {
            consumer_agent_id,
            readers,
            owner_layouts: Vec::new(),
            attempt_counter: Arc::new(AtomicU64::new(1)),
        })
    }

    pub async fn discover(
        consumer_agent_id: AgentId,
        owner_layouts: impl IntoIterator<Item = HeptaAgentLayout>,
        now_unix_seconds: i64,
    ) -> Self {
        let _ = now_unix_seconds;
        let mut owner_layouts = owner_layouts.into_iter().collect::<Vec<_>>();
        owner_layouts.sort_by(|left, right| left.agent_id().cmp(right.agent_id()));
        owner_layouts.dedup_by(|left, right| left.agent_id() == right.agent_id());
        owner_layouts.truncate(MAX_FEDERATION_OWNER_LAYOUTS_PER_AGENT);
        Self {
            consumer_agent_id,
            readers: Vec::new(),
            owner_layouts,
            attempt_counter: Arc::new(AtomicU64::new(1)),
        }
    }

    pub fn consumer_agent_id(&self) -> &AgentId {
        &self.consumer_agent_id
    }

    pub fn is_empty(&self) -> bool {
        self.readers.is_empty() && self.owner_layouts.is_empty()
    }

    pub async fn retrieve(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<FederatedRetrievalBatch, CognitiveStoreError> {
        if access.agent_id != self.consumer_agent_id {
            return Err(CognitiveStoreError::AccessDenied(
                "memory federation caller does not match the reader set consumer".to_string(),
            ));
        }
        let current = self
            .current_readers_with_coverage(request.now_unix_seconds())
            .await;
        let requested_sources = u32::try_from(current.readers.len()).unwrap_or(u32::MAX);
        let discovery_failures = current.discovery_failures;
        let readers = current.readers;
        let mut completed_sources = 0u32;
        let mut failed_sources = 0u32;
        let mut candidates = Vec::new();
        for reader in &readers {
            let attempt = self.attempt_counter.fetch_add(1, Ordering::Relaxed);
            match retrieve_reader_through_canonical_v2(reader, access, request, attempt).await {
                Ok(batch) => {
                    completed_sources = completed_sources.saturating_add(1);
                    candidates.extend(batch.candidates);
                }
                Err(_) => {
                    failed_sources = failed_sources.saturating_add(1);
                }
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
        candidates.truncate(crate::MAX_RETRIEVAL_RESULTS);
        Ok(FederatedRetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query().as_bytes()),
            candidates,
            coverage: FederatedRetrievalCoverage {
                requested_sources,
                completed_sources,
                failed_sources,
                discovery_failures,
            },
        })
    }

    pub async fn revalidate(
        &self,
        access: &FederationConsumerAccess,
        binding: &FederatedMemoryRevalidationBinding,
        now_unix_seconds: i64,
    ) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
        let readers = self.current_readers(now_unix_seconds).await;
        let Some(reader) = readers.iter().find(|reader| {
            reader.capability.owner_agent_id == binding.source_agent_id
                && reader.capability.id == binding.capability.id
        }) else {
            return Ok(FederatedRevalidationStatus::Stale(
                FederationRevalidationDrift::CapabilityMissing,
            ));
        };
        reader.revalidate(access, binding, now_unix_seconds).await
    }

    async fn current_readers(&self, now_unix_seconds: i64) -> Vec<FederatedMemoryReader> {
        self.current_readers_with_coverage(now_unix_seconds)
            .await
            .readers
    }

    async fn current_readers_with_coverage(
        &self,
        now_unix_seconds: i64,
    ) -> CurrentFederationReaders {
        let mut readers = self.readers.clone();
        let (dynamic, discovery_failures) = match tokio::time::timeout(
            FEDERATION_REFRESH_TIMEOUT,
            self.discover_dynamic_readers(now_unix_seconds),
        )
        .await
        {
            Ok(observation) => observation,
            Err(_) => (
                Vec::new(),
                u32::try_from(self.owner_layouts.len()).unwrap_or(u32::MAX),
            ),
        };
        readers.extend(dynamic);
        readers.sort_by(|left, right| {
            left.capability
                .owner_agent_id
                .cmp(&right.capability.owner_agent_id)
                .then_with(|| left.capability.id.cmp(&right.capability.id))
        });
        readers.dedup_by(|left, right| left.capability.id == right.capability.id);
        readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);
        CurrentFederationReaders {
            readers,
            discovery_failures,
        }
    }

    async fn discover_dynamic_readers(
        &self,
        now_unix_seconds: i64,
    ) -> (Vec<FederatedMemoryReader>, u32) {
        let mut readers = Vec::new();
        let mut discovery_failures = 0u32;
        for owner_layout in &self.owner_layouts {
            if readers.len() == MAX_FEDERATION_SOURCES_PER_AGENT {
                break;
            }
            let discovered = match FederatedMemoryReader::discover(
                owner_layout,
                &self.consumer_agent_id,
                now_unix_seconds,
            )
            .await
            {
                Ok(discovered) => discovered,
                Err(_) => {
                    discovery_failures = discovery_failures.saturating_add(1);
                    continue;
                }
            };
            readers.extend(
                discovered
                    .into_iter()
                    .take(MAX_FEDERATION_SOURCES_PER_AGENT - readers.len()),
            );
        }
        (readers, discovery_failures)
    }
}


struct CanonicalReaderTransport<'a> {
    reader: &'a FederatedMemoryReader,
    access: &'a FederationConsumerAccess,
    request: &'a RetrievalRequest,
    batch: Arc<Mutex<Option<FederatedRetrievalBatch>>>,
}

impl CanonicalTransportV2 for CanonicalReaderTransport<'_> {
    fn send_once<'a>(
        &'a self,
        query: &'a CanonicalQueryV2,
    ) -> CanonicalFutureV2<'a, Result<CanonicalTransportResultV2, CanonicalFederationError>> {
        Box::pin(async move {
            let expected_query =
                CanonicalDigest32::from_str(Sha256Digest::for_bytes(self.request.query().as_bytes()).as_str())
                    .map_err(|_| CanonicalFederationError::TransportRejected)?;
            if query.query_digest != expected_query {
                return Err(CanonicalFederationError::TransportRejected);
            }
            let frontier_before = match self.reader.observe_memory_frontier().await {
                Ok(frontier) => frontier,
                Err(CognitiveStoreError::Unavailable(_)) => {
                    return Ok(CanonicalTransportResultV2::NonTerminal(
                        CanonicalTransportOutcomeV2::Unavailable,
                    ));
                }
                Err(_) => return Err(CanonicalFederationError::TransportRejected),
            };
            let batch = match self.reader.retrieve(self.access, self.request).await {
                Ok(batch) => batch,
                Err(CognitiveStoreError::Unavailable(_)) => {
                    return Ok(CanonicalTransportResultV2::NonTerminal(
                        CanonicalTransportOutcomeV2::Unavailable,
                    ));
                }
                Err(_) => return Err(CanonicalFederationError::TransportRejected),
            };
            let frontier_after = match self.reader.observe_memory_frontier().await {
                Ok(frontier) => frontier,
                Err(CognitiveStoreError::Unavailable(_)) => {
                    return Ok(CanonicalTransportResultV2::NonTerminal(
                        CanonicalTransportOutcomeV2::Unavailable,
                    ));
                }
                Err(_) => return Err(CanonicalFederationError::TransportRejected),
            };
            if frontier_before != frontier_after {
                return Ok(CanonicalTransportResultV2::NonTerminal(
                    CanonicalTransportOutcomeV2::NoTerminalObservation,
                ));
            }
            let response =
                canonical_response_from_batch(query, self.reader, &batch, frontier_before)?;
            *self.batch.lock().await = Some(batch);
            Ok(CanonicalTransportResultV2::Terminal(response))
        })
    }
}

struct CanonicalReaderAuthority<'a> {
    reader: &'a FederatedMemoryReader,
    access: &'a FederationConsumerAccess,
    now_unix_seconds: i64,
}

impl CanonicalAuthorityV2 for CanonicalReaderAuthority<'_> {
    fn observe<'a>(
        &'a self,
        query: &'a CanonicalQueryV2,
        lease: &'a CanonicalLeaseV2,
    ) -> CanonicalFutureV2<'a, Result<CanonicalAuthorityObservationV2, CanonicalFederationError>> {
        Box::pin(async move {
            if let Some(drift) = self
                .reader
                .validate_capability(self.access, self.now_unix_seconds)
                .await
                .map_err(|_| CanonicalFederationError::TransportRejected)?
            {
                return Err(match drift {
                    FederationRevalidationDrift::Revoked => CanonicalFederationError::LeaseRevoked,
                    FederationRevalidationDrift::Expired => CanonicalFederationError::LeaseExpired,
                    FederationRevalidationDrift::CapabilityGeneration
                    | FederationRevalidationDrift::CapabilityRevision => {
                        CanonicalFederationError::DigestMismatch("authority_generation_vector")
                    }
                    FederationRevalidationDrift::Consumer => {
                        CanonicalFederationError::IdentityMismatch("authority_consumer")
                    }
                    FederationRevalidationDrift::Scope => {
                        CanonicalFederationError::DigestMismatch("authority_scope")
                    }
                    FederationRevalidationDrift::CapabilityMissing
                    | FederationRevalidationDrift::NotYetEffective
                    | FederationRevalidationDrift::Memory => {
                        CanonicalFederationError::TransportRejected
                    }
                });
            }
            Ok(CanonicalAuthorityObservationV2 {
                lease_id: lease.lease_id.clone(),
                query_binding_digest: query.binding_digest(),
                generation_vector_digest: query.generation_vector_digest,
                lease_epoch: query.lease_epoch,
                expires_unix_ms: lease.expires_unix_ms,
                revoked: false,
            })
        })
    }
}

struct CanonicalNeverCancelled;

impl CanonicalCancellationV2 for CanonicalNeverCancelled {
    fn cancelled<'a>(&'a self) -> CanonicalFutureV2<'a, ()> {
        Box::pin(std::future::pending())
    }
}

async fn retrieve_reader_through_canonical_v2(
    reader: &FederatedMemoryReader,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    attempt: u64,
) -> Result<FederatedRetrievalBatch, CanonicalFederationError> {
    let (query, lease, now_unix_ms) = canonical_query_and_lease(reader, access, request, attempt)?;
    let batch = Arc::new(Mutex::new(None));
    let transport = CanonicalReaderTransport {
        reader,
        access,
        request,
        batch: Arc::clone(&batch),
    };
    let authority = CanonicalReaderAuthority {
        reader,
        access,
        now_unix_seconds: request.now_unix_seconds(),
    };
    let result = execute_canonical_federation_v2(
        &transport,
        &authority,
        &CanonicalNeverCancelled,
        now_unix_ms,
        query,
        &lease,
    )
    .await?;
    if result.validity != CanonicalValidityV2::Valid {
        return Err(CanonicalFederationError::TransportRejected);
    }
    batch
        .lock()
        .await
        .take()
        .ok_or(CanonicalFederationError::TransportRejected)
}

fn canonical_query_and_lease(
    reader: &FederatedMemoryReader,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    attempt: u64,
) -> Result<(CanonicalQueryV2, CanonicalLeaseV2, u64), CanonicalFederationError> {
    let now_unix_ms = unix_seconds_to_millis(request.now_unix_seconds())?;
    let capability_expiry =
        unix_seconds_to_millis(reader.capability.expires_at_unix_seconds)?;
    let deadline_unix_ms = now_unix_ms
        .checked_add(FEDERATION_READ_TIMEOUT_MS)
        .ok_or(CanonicalFederationError::TransportRejected)?
        .min(capability_expiry);
    if deadline_unix_ms <= now_unix_ms {
        return Err(CanonicalFederationError::LeaseExpired);
    }

    let peer_id = canonical_id("peer", reader.capability.owner_agent_id.as_str())?;
    let principal_id = canonical_id("principal", access.agent_id.as_str())?;
    let scope_bytes = serde_json::to_vec(&reader.capability.scope)
        .map_err(|_| CanonicalFederationError::TransportRejected)?;
    let scope_digest = CanonicalDigest32::of_bytes(&scope_bytes);
    let purpose_digest = CanonicalDigest32::of_bytes(b"hepta.memory.federation.recall.v2");
    let generation_vector_digest = CanonicalDigest32::of_bytes(
        format!(
            "{}:{}:{}",
            reader.capability.id.as_str(),
            reader.capability.generation,
            reader.capability.revision
        )
        .as_bytes(),
    );
    let query_sha256 = Sha256Digest::for_bytes(request.query().as_bytes());
    let query_digest = CanonicalDigest32::from_str(query_sha256.as_str())
        .map_err(|_| CanonicalFederationError::TransportRejected)?;
    let nonce_digest = CanonicalDigest32::of_bytes(
        format!(
            "{}:{}:{}:{}",
            reader.capability.id.as_str(),
            query_sha256.as_str(),
            request.now_unix_seconds(),
            attempt
        )
        .as_bytes(),
    );
    let query_id = CanonicalStableId::new(format!("query:{nonce_digest}"))
        .map_err(|_| CanonicalFederationError::TransportRejected)?;
    let query = CanonicalQueryV2 {
        query_id: query_id.clone(),
        peer_id: peer_id.clone(),
        principal_id: principal_id.clone(),
        scope_digest,
        purpose_digest,
        generation_vector_digest,
        query_digest,
        maximum_results: u32::try_from(crate::MAX_RETRIEVAL_RESULTS)
            .map_err(|_| CanonicalFederationError::TransportRejected)?,
        deadline_unix_ms,
        lease_epoch: reader.capability.generation,
        nonce_digest,
    };
    let lease_id = canonical_id("lease", reader.capability.id.as_str())?;
    let lease = CanonicalLeaseV2 {
        lease_id,
        query_id,
        peer_id,
        principal_id,
        scope_digest,
        purpose_digest,
        generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        lease_epoch: reader.capability.generation,
        expires_unix_ms: capability_expiry,
        revoked: false,
    };
    Ok((query, lease, now_unix_ms))
}

fn canonical_response_from_batch(
    query: &CanonicalQueryV2,
    reader: &FederatedMemoryReader,
    batch: &FederatedRetrievalBatch,
    observed_frontier: u64,
) -> Result<CanonicalResponseV2, CanonicalFederationError> {
    let mut items = Vec::with_capacity(batch.candidates.len());
    for candidate in &batch.candidates {
        let record_revision = CanonicalRevision::new(candidate.candidate.memory.id.revision)
            .map_err(|_| CanonicalFederationError::TransportRejected)?;
        let record_digest = CanonicalDigest32::from_str(
            candidate.candidate.revalidation.content_sha256.as_str(),
        )
        .map_err(|_| CanonicalFederationError::TransportRejected)?;
        let support_bytes = serde_json::to_vec(&candidate.candidate.revalidation.citations)
            .map_err(|_| CanonicalFederationError::TransportRejected)?;
        let validity_bytes = serde_json::to_vec(&candidate.candidate.revalidation)
            .map_err(|_| CanonicalFederationError::TransportRejected)?;
        items.push(CanonicalEvidenceItemV2 {
            source_owner_id: canonical_id("owner", candidate.source_agent_id.as_str())?,
            record_id: canonical_id(
                "memory",
                candidate.candidate.memory.id.memory_id.as_str(),
            )?,
            record_revision,
            record_digest,
            support_digest: CanonicalDigest32::of_bytes(&support_bytes),
            validity_digest: CanonicalDigest32::of_bytes(&validity_bytes),
        });
    }
    let completeness = if items.is_empty() {
        CanonicalCompletenessV2::Empty
    } else if items.len() >= crate::MAX_RETRIEVAL_RESULTS || batch.coverage.is_partial() {
        CanonicalCompletenessV2::Partial
    } else {
        CanonicalCompletenessV2::Complete
    };
    Ok(CanonicalResponseV2 {
        peer_id: query.peer_id.clone(),
        query_binding_digest: query.binding_digest(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        response_digest: CanonicalDigest32::ZERO,
        observed_frontier,
        expires_unix_ms: unix_seconds_to_millis(reader.capability.expires_at_unix_seconds)?
            .min(query.deadline_unix_ms),
        items,
        completeness,
        terminal_observed: true,
    }
    .sealed())
}

fn canonical_id(prefix: &str, value: &str) -> Result<CanonicalStableId, CanonicalFederationError> {
    let digest = CanonicalDigest32::of_bytes(value.as_bytes());
    CanonicalStableId::new(format!("{prefix}:{digest}"))
        .map_err(|_| CanonicalFederationError::TransportRejected)
}

fn unix_seconds_to_millis(value: i64) -> Result<u64, CanonicalFederationError> {
    let seconds =
        u64::try_from(value).map_err(|_| CanonicalFederationError::TransportRejected)?;
    seconds
        .checked_mul(1_000)
        .ok_or(CanonicalFederationError::TransportRejected)
}

async fn insert_event(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    capability: &FederationCapability,
    action: FederationAction,
    effective_at_unix_seconds: i64,
) -> Result<(), CognitiveStoreError> {
    let (scope_kind, owner_workspace_sha256) = capability.scope.owner_scope.database_parts();
    sqlx::query(
        "INSERT INTO memory_federation_events (
            capability_id, revision, generation, owner_agent_id, consumer_agent_id,
            scope_kind, owner_workspace_sha256, consumer_workspace_sha256, action,
            effective_at_unix_seconds, expires_at_unix_seconds, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(capability.id.as_str())
    .bind(to_i64(capability.revision, "federation revision")?)
    .bind(to_i64(capability.generation, "federation generation")?)
    .bind(capability.owner_agent_id.as_str())
    .bind(capability.consumer_agent_id.as_str())
    .bind(scope_kind)
    .bind(owner_workspace_sha256)
    .bind(capability.scope.consumer_workspace_sha256.as_str())
    .bind(action.as_str())
    .bind(effective_at_unix_seconds)
    .bind(capability.expires_at_unix_seconds)
    .bind(now_unix_seconds()?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn decode_event(
    row: sqlx::sqlite::SqliteRow,
) -> Result<StoredCapabilityEvent, CognitiveStoreError> {
    let id = FederationCapabilityId::parse(row.try_get("capability_id").map_err(unavailable)?)?;
    let owner_agent_id = AgentId::parse(
        row.try_get::<String, _>("owner_agent_id")
            .map_err(unavailable)?,
    )
    .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let consumer_agent_id = AgentId::parse(
        row.try_get::<String, _>("consumer_agent_id")
            .map_err(unavailable)?,
    )
    .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let owner_scope = CognitiveScope::parse(
        row.try_get("scope_kind").map_err(unavailable)?,
        row.try_get("workspace_sha256").map_err(unavailable)?,
    )
    .map_err(CognitiveStoreError::Corrupt)?;
    let consumer_workspace_sha256 = Sha256Digest::parse(
        row.try_get::<String, _>("consumer_workspace_sha256")
            .map_err(unavailable)?,
    )
    .map_err(CognitiveStoreError::Corrupt)?;
    let revision = from_i64(row.try_get("revision").map_err(unavailable)?, "revision")?;
    let generation = from_i64(
        row.try_get("generation").map_err(unavailable)?,
        "generation",
    )?;
    let capability = FederationCapability {
        id,
        owner_agent_id,
        consumer_agent_id,
        scope: FederationGrantScope::new(owner_scope, consumer_workspace_sha256),
        generation,
        revision,
        effective_at_unix_seconds: row
            .try_get("effective_at_unix_seconds")
            .map_err(unavailable)?,
        expires_at_unix_seconds: row
            .try_get("expires_at_unix_seconds")
            .map_err(unavailable)?,
    };
    let expected_id = FederationCapabilityId::for_binding(
        &capability.owner_agent_id,
        &capability.consumer_agent_id,
        &capability.scope,
    );
    if capability.id != expected_id
        || capability.revision == 0
        || capability.revision > MAX_FEDERATION_CAPABILITY_REVISIONS
        || capability.generation == 0
    {
        return Err(CognitiveStoreError::Corrupt(
            "memory federation capability binding is inconsistent".to_string(),
        ));
    }
    Ok(StoredCapabilityEvent {
        capability,
        action: FederationAction::parse(row.try_get("action").map_err(unavailable)?)?,
    })
}

fn decode_status(
    row: sqlx::sqlite::SqliteRow,
) -> Result<FederationCapabilityStatus, CognitiveStoreError> {
    let event = decode_event(row)?;
    Ok(FederationCapabilityStatus {
        capability: event.capability,
        state: match event.action {
            FederationAction::Grant => FederationCapabilityState::Granted,
            FederationAction::Revoke => FederationCapabilityState::Revoked,
        },
    })
}

fn require_stable_binding(
    capability: &FederationCapability,
    owner_agent_id: &AgentId,
    consumer_agent_id: &AgentId,
    scope: &FederationGrantScope,
) -> Result<(), CognitiveStoreError> {
    let expected_id = FederationCapabilityId::for_binding(owner_agent_id, consumer_agent_id, scope);
    if capability.id != expected_id
        || capability.owner_agent_id != *owner_agent_id
        || capability.consumer_agent_id != *consumer_agent_id
        || capability.scope != *scope
    {
        return Err(CognitiveStoreError::Corrupt(
            "memory federation capability changed its stable binding".to_string(),
        ));
    }
    Ok(())
}

fn owner_access(capability: &FederationCapability) -> CognitiveAccess {
    match capability.scope.owner_scope() {
        CognitiveScope::AgentPrivate => {
            CognitiveAccess::agent_private(capability.owner_agent_id.clone())
        }
        CognitiveScope::WorkspacePrivate { workspace_sha256 } => {
            CognitiveAccess::workspace_private(
                capability.owner_agent_id.clone(),
                workspace_sha256.clone(),
            )
        }
    }
}

fn require_authorized(
    drift: Option<FederationRevalidationDrift>,
) -> Result<(), CognitiveStoreError> {
    match drift {
        None => Ok(()),
        Some(drift) => Err(CognitiveStoreError::AccessDenied(format!(
            "memory federation capability is not current ({drift:?})"
        ))),
    }
}

async fn open_read_only_pool(path: &Path) -> Result<SqlitePool, CognitiveStoreError> {
    let metadata = std::fs::metadata(path).map_err(unavailable)?;
    if !metadata.is_file()
        || canonical_path_without_redirection(path)
            .map_err(unavailable)?
            .is_none()
    {
        return Err(CognitiveStoreError::Invalid(
            "federated cognitive database must be an existing canonical regular file".to_string(),
        ));
    }
    let sqlite_home = AbsolutePathBuf::try_from(
        path.parent()
            .ok_or_else(|| {
                CognitiveStoreError::Invalid(
                    "federated cognitive database has no parent directory".to_string(),
                )
            })?
            .to_path_buf(),
    )
    .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_read_only_pool(path)
        .await
        .map_err(unavailable)?;
    sqlx::query("PRAGMA query_only = ON")
        .execute(&pool)
        .await
        .map_err(unavailable)?;
    let query_only: i64 = sqlx::query_scalar("PRAGMA query_only")
        .fetch_one(&pool)
        .await
        .map_err(unavailable)?;
    if query_only != 1 {
        return Err(CognitiveStoreError::Corrupt(
            "federated cognitive connection is not query-only".to_string(),
        ));
    }
    Ok(pool)
}

async fn verify_read_only_store(
    pool: &SqlitePool,
    expected_owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    let quick_check = sqlx::query_scalar::<_, String>("PRAGMA quick_check(1)")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if quick_check != ["ok"]
        || !sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(pool)
            .await
            .map_err(unavailable)?
            .is_empty()
    {
        return Err(CognitiveStoreError::Corrupt(
            "federated cognitive store failed SQLite integrity checks".to_string(),
        ));
    }
    let owner: String =
        sqlx::query_scalar("SELECT owner_agent_id FROM cognitive_meta WHERE singleton = 1")
            .fetch_one(pool)
            .await
            .map_err(unavailable)?;
    if owner != expected_owner.as_str() {
        return Err(CognitiveStoreError::AccessDenied(
            "federated cognitive store owner does not match its AgentId path".to_string(),
        ));
    }
    let objects: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_schema WHERE name IN (
            'memory_federation_events', 'memory_federation_events_no_update',
            'memory_federation_events_no_delete', 'memory_federation_heads',
            'memory_federation_consumer_heads'
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if objects != 5 {
        return Err(CognitiveStoreError::Corrupt(
            "memory federation schema is incomplete".to_string(),
        ));
    }
    Ok(())
}

fn now_unix_seconds() -> Result<i64, CognitiveStoreError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(unavailable)?
        .as_secs();
    i64::try_from(seconds)
        .map_err(|_| CognitiveStoreError::Unavailable("system clock overflow".to_string()))
}

fn to_i64(value: u64, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| CognitiveStoreError::Invalid(format!("{label} exceeds i64")))
}

fn from_i64(value: i64, label: &str) -> Result<u64, CognitiveStoreError> {
    u64::try_from(value)
        .map_err(|_| CognitiveStoreError::Corrupt(format!("negative federation {label}")))
}

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::future::Future;

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use unicode_segmentation::UnicodeSegmentation;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::LedgerSourceKind;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionId;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::ProjectionGeneration;
use crate::SourceRevisionId;
use crate::StableMemoryId;
use crate::cognitive_store::decode_scope;
use crate::cognitive_store::unavailable;

#[path = "cognitive_retrieval_observation.rs"]
mod observation;
use observation::ChannelOutput;
pub use observation::ObservedRetrievalCandidate;
pub use observation::RetrievalChannelObservation;
pub use observation::RetrievalLimitObservation;
pub use observation::RetrievalObservation;

pub const MAX_RETRIEVAL_QUERY_BYTES: usize = 2 * 1024;
pub const MAX_RETRIEVAL_CHANNEL_CANDIDATES: usize = 32;
pub const MAX_RETRIEVAL_RESULTS: usize = 4;

const RRF_K: u64 = 60;
const RRF_SCALE: u64 = 1_000_000;
const MAX_FTS_TERMS: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SourceCitationRecord {
    pub id: SourceRevisionId,
    pub scope: CognitiveScope,
    pub kind: LedgerSourceKind,
    pub content: Vec<u8>,
    pub content_sha256: Sha256Digest,
    pub observed_at_unix_seconds: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryExplanation {
    pub memory: MemoryRevisionRecord,
    pub citations: Vec<SourceCitationRecord>,
    pub kg_projection_generation: Option<ProjectionGeneration>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RetrievalChannel {
    MemoryFts,
    EntityFts,
    GraphOneHop,
    Recency,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SourceRevalidationBinding {
    pub id: SourceRevisionId,
    pub scope: CognitiveScope,
    pub content_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryRevalidationBinding {
    pub memory: MemoryRevisionId,
    pub scope: CognitiveScope,
    pub content_sha256: Sha256Digest,
    pub verification: MemoryVerification,
    pub lifecycle: MemoryLifecycleState,
    pub valid_from_unix_seconds: i64,
    pub valid_to_unix_seconds: Option<i64>,
    pub citations: Vec<SourceRevalidationBinding>,
    pub kg_projection_generation: Option<ProjectionGeneration>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RetrievalCandidate {
    pub memory: MemoryRevisionRecord,
    pub reciprocal_rank_score: u64,
    pub channels: Vec<RetrievalChannel>,
    pub revalidation: MemoryRevalidationBinding,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RetrievalBatch {
    pub query_sha256: Sha256Digest,
    pub candidates: Vec<RetrievalCandidate>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalRequest {
    query: String,
    now_unix_seconds: i64,
}

impl RetrievalRequest {
    pub fn new(query: impl Into<String>, now_unix_seconds: i64) -> Self {
        Self {
            query: query.into(),
            now_unix_seconds,
        }
    }

    pub fn query(&self) -> &str {
        &self.query
    }

    pub fn now_unix_seconds(&self) -> i64 {
        self.now_unix_seconds
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RevalidationDrift {
    HeadRevision,
    Scope,
    ContentHash,
    Verification,
    Lifecycle,
    Validity,
    CitationSet,
    SourceHash,
    KgProjectionGeneration,
    NotEligible,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RevalidationStatus {
    Current(Box<MemoryExplanation>),
    Stale(RevalidationDrift),
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct MemoryKey {
    memory_id: String,
    revision: u64,
}

#[derive(Default)]
struct AggregatedRank {
    score: u64,
    channels: BTreeSet<RetrievalChannel>,
}

struct EntitySeed {
    projection_scope: String,
    generation: i64,
    canonical_entity_id: String,
    memory: MemoryKey,
}

impl CognitiveStore {
    pub async fn read_memory_head(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
    ) -> Result<MemoryRevisionRecord, CognitiveStoreError> {
        self.latest_memory(access, memory_id).await
    }

    pub async fn read_citation(
        &self,
        access: &CognitiveAccess,
        citation: &SourceRevisionId,
    ) -> Result<SourceCitationRecord, CognitiveStoreError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let citation = self
            .read_citation_tx(&mut transaction, access, citation)
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(citation)
    }

    async fn read_citation_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        citation: &SourceRevisionId,
    ) -> Result<SourceCitationRecord, CognitiveStoreError> {
        let row =
            sqlx::query("SELECT * FROM source_ledger WHERE source_id = ? AND source_revision = ?")
                .bind(citation.source_id.as_str())
                .bind(to_i64(citation.revision, "source revision")?)
                .fetch_optional(&mut **transaction)
                .await
                .map_err(unavailable)?
                .ok_or_else(|| {
                    CognitiveStoreError::Invalid("citation does not exist".to_string())
                })?;
        let owner: String = row.try_get("owner_agent_id").map_err(unavailable)?;
        let scope = decode_scope(&row)?;
        self.authorize(access, &scope)?;
        if owner != self.owner_agent_id.as_str() {
            return Err(CognitiveStoreError::Corrupt(
                "citation owner does not match its cognitive store".to_string(),
            ));
        }
        let content: Vec<u8> = row.try_get("content").map_err(unavailable)?;
        let content_sha256 = Sha256Digest::parse(
            row.try_get::<String, _>("content_sha256")
                .map_err(unavailable)?,
        )
        .map_err(CognitiveStoreError::Corrupt)?;
        if content_sha256 != Sha256Digest::for_bytes(&content) {
            return Err(CognitiveStoreError::Corrupt(
                "citation content digest does not match stored content".to_string(),
            ));
        }
        Ok(SourceCitationRecord {
            id: citation.clone(),
            scope,
            kind: LedgerSourceKind::parse(row.try_get("source_kind").map_err(unavailable)?)
                .map_err(CognitiveStoreError::Corrupt)?,
            content,
            content_sha256,
            observed_at_unix_seconds: row
                .try_get("observed_at_unix_seconds")
                .map_err(unavailable)?,
        })
    }

    pub async fn explain_memory_head(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
    ) -> Result<MemoryExplanation, CognitiveStoreError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let explanation = self
            .explain_memory_head_tx(&mut transaction, access, memory_id)
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(explanation)
    }

    async fn explain_memory_head_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
    ) -> Result<MemoryExplanation, CognitiveStoreError> {
        let memory = self
            .latest_memory_tx(transaction, access, memory_id)
            .await?;
        let mut citations = Vec::with_capacity(memory.citations.len());
        for citation in &memory.citations {
            let source = self.read_citation_tx(transaction, access, citation).await?;
            if source.scope != memory.scope {
                return Err(CognitiveStoreError::Corrupt(
                    "memory head and citation scope diverged".to_string(),
                ));
            }
            citations.push(source);
        }
        let kg_projection_generation = self
            .projection_generation_for_scope_tx(transaction, &memory.scope)
            .await?;
        let current_head: i64 =
            sqlx::query_scalar("SELECT revision FROM memory_heads WHERE memory_id = ?")
                .bind(memory.id.memory_id.as_str())
                .fetch_one(&mut **transaction)
                .await
                .map_err(unavailable)?;
        if current_head != to_i64(memory.id.revision, "memory revision")? {
            return Err(CognitiveStoreError::Conflict(
                "memory head changed while its explanation was read".to_string(),
            ));
        }
        Ok(MemoryExplanation {
            memory,
            citations,
            kg_projection_generation,
        })
    }

    /// Performs bounded automatic retrieval without attaching content to a model request.
    pub async fn retrieve_memory_candidates(
        &self,
        access: &CognitiveAccess,
        request: &RetrievalRequest,
    ) -> Result<RetrievalBatch, CognitiveStoreError> {
        let fts_query = self.validate_retrieval_request(access, request)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let batch = self
            .retrieve_memory_candidates_tx(&mut transaction, access, request, &fts_query)
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(batch)
    }

    async fn retrieve_memory_candidates_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        request: &RetrievalRequest,
        fts_query: &str,
    ) -> Result<RetrievalBatch, CognitiveStoreError> {
        let generated = self
            .generate_retrieval_tx(transaction, access, request, fts_query)
            .await?;
        let candidates = self
            .resolve_retrieval_tx(
                transaction,
                access,
                request,
                generated.ranked,
                MAX_RETRIEVAL_RESULTS,
            )
            .await?;
        Ok(RetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query.as_bytes()),
            candidates,
        })
    }

    pub async fn revalidate_memory_candidate(
        &self,
        access: &CognitiveAccess,
        binding: &MemoryRevalidationBinding,
        now_unix_seconds: i64,
    ) -> Result<RevalidationStatus, CognitiveStoreError> {
        self.revalidate_memory_candidates(access, std::slice::from_ref(binding), now_unix_seconds)
            .await?
            .pop()
            .ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "single-memory revalidation returned no status".to_string(),
                )
            })
    }

    /// Revalidates an ordered attachment set against one SQLite read snapshot.
    ///
    /// Physical-send callers must use this batch API rather than opening one
    /// transaction per memory: a projection mutation between two independent
    /// reads could otherwise produce an attachment assembled from different KG
    /// generations.
    pub async fn revalidate_memory_candidates(
        &self,
        access: &CognitiveAccess,
        bindings: &[MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> Result<Vec<RevalidationStatus>, CognitiveStoreError> {
        self.revalidate_memory_candidates_with_after_each(
            access,
            bindings,
            now_unix_seconds,
            |_| async {},
        )
        .await
    }

    async fn revalidate_memory_candidates_with_after_each<F, Fut>(
        &self,
        access: &CognitiveAccess,
        bindings: &[MemoryRevalidationBinding],
        now_unix_seconds: i64,
        mut after_each: F,
    ) -> Result<Vec<RevalidationStatus>, CognitiveStoreError>
    where
        F: FnMut(usize) -> Fut,
        Fut: Future<Output = ()>,
    {
        for binding in bindings {
            self.authorize(access, &binding.scope)?;
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let mut statuses = Vec::with_capacity(bindings.len());
        for (index, binding) in bindings.iter().enumerate() {
            statuses.push(
                self.revalidate_memory_candidate_tx(
                    &mut transaction,
                    access,
                    binding,
                    now_unix_seconds,
                )
                .await?,
            );
            after_each(index).await;
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(statuses)
    }

    #[cfg(test)]
    pub(crate) async fn revalidate_memory_candidates_with_test_hook<F, Fut>(
        &self,
        access: &CognitiveAccess,
        bindings: &[MemoryRevalidationBinding],
        now_unix_seconds: i64,
        after_each: F,
    ) -> Result<Vec<RevalidationStatus>, CognitiveStoreError>
    where
        F: FnMut(usize) -> Fut,
        Fut: Future<Output = ()>,
    {
        self.revalidate_memory_candidates_with_after_each(
            access,
            bindings,
            now_unix_seconds,
            after_each,
        )
        .await
    }

    async fn revalidate_memory_candidate_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        binding: &MemoryRevalidationBinding,
        now_unix_seconds: i64,
    ) -> Result<RevalidationStatus, CognitiveStoreError> {
        let head =
            sqlx::query_scalar::<_, i64>("SELECT revision FROM memory_heads WHERE memory_id = ?")
                .bind(binding.memory.memory_id.as_str())
                .fetch_optional(&mut **transaction)
                .await
                .map_err(unavailable)?;
        if head != Some(to_i64(binding.memory.revision, "memory revision")?) {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::HeadRevision));
        }
        let explanation = self
            .explain_memory_head_tx(transaction, access, &binding.memory.memory_id)
            .await?;
        let memory = &explanation.memory;
        if memory.scope != binding.scope {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::Scope));
        }
        if memory.content_sha256 != binding.content_sha256 {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::ContentHash));
        }
        if memory.verification != binding.verification {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::Verification));
        }
        if memory.lifecycle != binding.lifecycle {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::Lifecycle));
        }
        if memory.valid_from_unix_seconds != binding.valid_from_unix_seconds
            || memory.valid_to_unix_seconds != binding.valid_to_unix_seconds
        {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::Validity));
        }
        let source_bindings = explanation
            .citations
            .iter()
            .map(|source| SourceRevalidationBinding {
                id: source.id.clone(),
                scope: source.scope.clone(),
                content_sha256: source.content_sha256.clone(),
            })
            .collect::<Vec<_>>();
        if source_bindings
            .iter()
            .map(|source| &source.id)
            .collect::<Vec<_>>()
            != binding
                .citations
                .iter()
                .map(|source| &source.id)
                .collect::<Vec<_>>()
        {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::CitationSet));
        }
        if source_bindings != binding.citations {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::SourceHash));
        }
        if explanation.kg_projection_generation != binding.kg_projection_generation {
            return Ok(RevalidationStatus::Stale(
                RevalidationDrift::KgProjectionGeneration,
            ));
        }
        if !eligible(memory, now_unix_seconds) {
            return Ok(RevalidationStatus::Stale(RevalidationDrift::NotEligible));
        }
        Ok(RevalidationStatus::Current(Box::new(explanation)))
    }

    async fn projection_generation_for_scope_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        scope: &CognitiveScope,
    ) -> Result<Option<ProjectionGeneration>, CognitiveStoreError> {
        let generation = sqlx::query_scalar::<_, i64>(
            "SELECT generation FROM kg_projection WHERE projection_scope = ?",
        )
        .bind(scope.projection_key())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?;
        generation
            .map(|generation| {
                u64::try_from(generation)
                    .map(ProjectionGeneration)
                    .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))
            })
            .transpose()
    }

    async fn memory_fts_channel_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        fts_query: &str,
        now: i64,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        let rows = sqlx::query(
            "SELECT f.memory_id, f.revision FROM memory_fts f
             JOIN memory_heads h ON h.memory_id = f.memory_id AND h.revision = f.revision
             JOIN memory_revisions r ON r.memory_id = f.memory_id AND r.revision = f.revision
             WHERE memory_fts MATCH ? AND r.owner_agent_id = ?
               AND (r.scope_kind = 'agent_private' OR
                    (r.scope_kind = 'workspace_private' AND r.workspace_sha256 = ?))
               AND r.verification = 'verified' AND r.lifecycle = 'active'
               AND r.valid_from_unix_seconds <= ?
               AND (r.valid_to_unix_seconds IS NULL OR ? < r.valid_to_unix_seconds)
             ORDER BY bm25(memory_fts), f.memory_id, f.revision LIMIT ?",
        )
        .bind(fts_query)
        .bind(self.owner_agent_id.as_str())
        .bind(access.workspace_sha256().map(Sha256Digest::as_str))
        .bind(now)
        .bind(now)
        .bind(channel_limit())
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let limit =
            RetrievalLimitObservation::for_rows(rows.len(), MAX_RETRIEVAL_CHANNEL_CANDIDATES);
        Ok(ChannelOutput {
            values: decode_memory_keys(rows)?,
            limit,
        })
    }

    async fn entity_fts_channel_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        fts_query: &str,
        now: i64,
    ) -> Result<ChannelOutput<EntitySeed>, CognitiveStoreError> {
        let workspace_scope = access
            .workspace_sha256()
            .map(|workspace_sha256| CognitiveScope::WorkspacePrivate {
                workspace_sha256: workspace_sha256.clone(),
            })
            .map(|scope| scope.projection_key());
        let rows = sqlx::query(
            "SELECT f.projection_scope, f.generation, f.node_id,
                    i.canonical_entity_id, n.memory_id, n.memory_revision
             FROM kg_entity_fts f
             JOIN kg_projection p ON p.projection_scope = f.projection_scope
                                  AND p.generation = f.generation
             JOIN kg_nodes n ON n.projection_scope = f.projection_scope
                            AND n.generation = f.generation AND n.node_id = f.node_id
             JOIN kg_projection_node_entities i
               ON i.projection_scope = n.projection_scope
              AND i.generation = n.generation AND i.node_id = n.node_id
             JOIN kg_revision_entities k
               ON k.memory_id = n.memory_id AND k.memory_revision = n.memory_revision
              AND k.canonical_entity_id = i.canonical_entity_id
             JOIN memory_heads h ON h.memory_id = n.memory_id
                                AND h.revision = n.memory_revision
             JOIN memory_revisions r ON r.memory_id = n.memory_id
                                    AND r.revision = n.memory_revision
             WHERE kg_entity_fts MATCH ?
               AND (f.projection_scope = 'agent_private' OR f.projection_scope = ?)
               AND n.valid_from_unix_seconds <= ?
               AND (n.valid_to_unix_seconds IS NULL OR ? < n.valid_to_unix_seconds)
               AND r.owner_agent_id = ? AND r.verification = 'verified'
               AND r.lifecycle = 'active' AND r.valid_from_unix_seconds <= ?
               AND (r.valid_to_unix_seconds IS NULL OR ? < r.valid_to_unix_seconds)
             ORDER BY bm25(kg_entity_fts), f.projection_scope, f.node_id, n.memory_id LIMIT ?",
        )
        .bind(fts_query)
        .bind(workspace_scope)
        .bind(now)
        .bind(now)
        .bind(self.owner_agent_id.as_str())
        .bind(now)
        .bind(now)
        .bind(channel_limit())
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let limit =
            RetrievalLimitObservation::for_rows(rows.len(), MAX_RETRIEVAL_CHANNEL_CANDIDATES);
        let mut seen = BTreeSet::new();
        let values = rows
            .into_iter()
            .filter_map(|row| {
                let result = (|| {
                    let memory = decode_memory_key(&row, "memory_id", "memory_revision")?;
                    let projection_scope: String =
                        row.try_get("projection_scope").map_err(unavailable)?;
                    let generation: i64 = row.try_get("generation").map_err(unavailable)?;
                    let canonical_entity_id: String =
                        row.try_get("canonical_entity_id").map_err(unavailable)?;
                    if !seen.insert((
                        projection_scope.clone(),
                        generation,
                        canonical_entity_id.clone(),
                        memory.clone(),
                    )) {
                        return Ok(None);
                    }
                    Ok(Some(EntitySeed {
                        projection_scope,
                        generation,
                        canonical_entity_id,
                        memory,
                    }))
                })();
                result.transpose()
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(ChannelOutput { values, limit })
    }

    async fn graph_channel_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        seeds: &[EntitySeed],
        now: i64,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        let mut queried_canonical_entities = BTreeSet::new();
        let mut seen = BTreeSet::new();
        let mut result = Vec::new();
        let mut limit = RetrievalLimitObservation::Exhausted;
        'seeds: for seed in seeds {
            if result.len() >= MAX_RETRIEVAL_CHANNEL_CANDIDATES {
                limit = RetrievalLimitObservation::LimitReached;
                break;
            }
            if !queried_canonical_entities.insert((
                seed.projection_scope.clone(),
                seed.generation,
                seed.canonical_entity_id.clone(),
            )) {
                continue;
            }
            let remaining = MAX_RETRIEVAL_CHANNEL_CANDIDATES - result.len();
            let rows = sqlx::query(
                "WITH canonical_support_nodes AS (
                     SELECT node_id
                     FROM kg_projection_node_entities
                     WHERE projection_scope = ? AND generation = ?
                       AND canonical_entity_id = ?
                 )
                 SELECT DISTINCT e.edge_id, e.memory_id AS edge_memory_id,
                        e.memory_revision AS edge_memory_revision,
                        n.node_id, n.memory_id AS node_memory_id,
                        n.memory_revision AS node_memory_revision
                 FROM canonical_support_nodes s
                 JOIN kg_edges e
                   ON e.projection_scope = ? AND e.generation = ?
                  AND (e.from_node_id = s.node_id OR e.to_node_id = s.node_id)
                 JOIN kg_nodes n
                   ON n.projection_scope = e.projection_scope AND n.generation = e.generation
                  AND n.node_id = CASE WHEN e.from_node_id = s.node_id
                                       THEN e.to_node_id ELSE e.from_node_id END
                 JOIN memory_heads eh ON eh.memory_id = e.memory_id
                                     AND eh.revision = e.memory_revision
                 JOIN memory_heads nh ON nh.memory_id = n.memory_id
                                     AND nh.revision = n.memory_revision
                 JOIN memory_revisions er ON er.memory_id = e.memory_id
                                         AND er.revision = e.memory_revision
                 JOIN memory_revisions nr ON nr.memory_id = n.memory_id
                                         AND nr.revision = n.memory_revision
                 WHERE e.valid_from_unix_seconds <= ?
                   AND (e.valid_to_unix_seconds IS NULL OR ? < e.valid_to_unix_seconds)
                   AND n.valid_from_unix_seconds <= ?
                   AND (n.valid_to_unix_seconds IS NULL OR ? < n.valid_to_unix_seconds)
                   AND er.verification = 'verified' AND er.lifecycle = 'active'
                   AND nr.verification = 'verified' AND nr.lifecycle = 'active'
                   AND er.valid_from_unix_seconds <= ?
                   AND (er.valid_to_unix_seconds IS NULL OR ? < er.valid_to_unix_seconds)
                   AND nr.valid_from_unix_seconds <= ?
                   AND (nr.valid_to_unix_seconds IS NULL OR ? < nr.valid_to_unix_seconds)
                 ORDER BY e.edge_id, n.node_id
                 LIMIT ?",
            )
            .bind(&seed.projection_scope)
            .bind(seed.generation)
            .bind(&seed.canonical_entity_id)
            .bind(&seed.projection_scope)
            .bind(seed.generation)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(i64::try_from(remaining).map_err(|_| {
                CognitiveStoreError::Invalid("graph retrieval limit exceeds i64".to_string())
            })?)
            .fetch_all(&mut **transaction)
            .await
            .map_err(unavailable)?;
            if rows.len() >= remaining {
                limit = RetrievalLimitObservation::LimitReached;
            }
            for row in rows {
                for key in [
                    decode_memory_key(&row, "edge_memory_id", "edge_memory_revision")?,
                    decode_memory_key(&row, "node_memory_id", "node_memory_revision")?,
                ] {
                    if seen.insert(key.clone()) {
                        result.push(key);
                    }
                    if result.len() >= MAX_RETRIEVAL_CHANNEL_CANDIDATES {
                        limit = RetrievalLimitObservation::LimitReached;
                        break 'seeds;
                    }
                }
            }
        }
        Ok(ChannelOutput {
            values: result,
            limit,
        })
    }

    #[cfg(test)]
    pub(crate) async fn graph_channel_for_test(
        &self,
        seeds: &[(
            CognitiveScope,
            ProjectionGeneration,
            String,
            MemoryRevisionId,
        )],
        now: i64,
    ) -> Result<Vec<MemoryRevisionId>, CognitiveStoreError> {
        let seeds = seeds
            .iter()
            .map(
                |(scope, generation, canonical_entity_id, memory)| -> Result<_, CognitiveStoreError> {
                    Ok(EntitySeed {
                        projection_scope: scope.projection_key(),
                        generation: to_i64(generation.get(), "projection generation")?,
                        canonical_entity_id: canonical_entity_id.clone(),
                        memory: MemoryKey {
                            memory_id: memory.memory_id.as_str().to_string(),
                            revision: memory.revision,
                        },
                    })
                },
            )
            .collect::<Result<Vec<_>, _>>()?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let keys = self.graph_channel_tx(&mut transaction, &seeds, now).await?;
        transaction.commit().await.map_err(unavailable)?;
        keys.values
            .into_iter()
            .map(|key| {
                Ok(MemoryRevisionId {
                    memory_id: StableMemoryId::parse(key.memory_id)
                        .map_err(CognitiveStoreError::Corrupt)?,
                    revision: key.revision,
                })
            })
            .collect()
    }

    async fn recency_channel_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        workspace: Option<&str>,
        now: i64,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        let rows = sqlx::query(
            "SELECT r.memory_id, r.revision FROM memory_heads h
             JOIN memory_revisions r ON r.memory_id = h.memory_id AND r.revision = h.revision
             WHERE r.owner_agent_id = ?
               AND (r.scope_kind = 'agent_private' OR
                    (r.scope_kind = 'workspace_private' AND r.workspace_sha256 = ?))
               AND r.verification = 'verified' AND r.lifecycle = 'active'
               AND r.valid_from_unix_seconds <= ?
               AND (r.valid_to_unix_seconds IS NULL OR ? < r.valid_to_unix_seconds)
             ORDER BY r.recorded_at_unix_seconds DESC, r.memory_id, r.revision LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(workspace)
        .bind(now)
        .bind(now)
        .bind(channel_limit())
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let limit =
            RetrievalLimitObservation::for_rows(rows.len(), MAX_RETRIEVAL_CHANNEL_CANDIDATES);
        Ok(ChannelOutput {
            values: decode_memory_keys(rows)?,
            limit,
        })
    }
}

fn bounded_fts_query(query: &str) -> Option<String> {
    let mut terms = BTreeSet::new();
    for word in query.unicode_words().take(MAX_FTS_TERMS) {
        terms.insert(format!("\"{}\"", word.replace('"', "\"\"")));
    }
    (!terms.is_empty()).then(|| terms.into_iter().collect::<Vec<_>>().join(" OR "))
}

fn add_rrf_channel(
    ranked: &mut BTreeMap<MemoryKey, AggregatedRank>,
    channel: &[MemoryKey],
    source: RetrievalChannel,
) {
    let mut seen = BTreeSet::new();
    for (index, memory) in channel
        .iter()
        .filter(|memory| seen.insert((*memory).clone()))
        .take(MAX_RETRIEVAL_CHANNEL_CANDIDATES)
        .enumerate()
    {
        let rank = u64::try_from(index + 1).unwrap_or(u64::MAX);
        let aggregate = ranked.entry(memory.clone()).or_default();
        aggregate.score += RRF_SCALE / (RRF_K + rank);
        aggregate.channels.insert(source);
    }
}

fn decode_memory_keys(
    rows: Vec<sqlx::sqlite::SqliteRow>,
) -> Result<Vec<MemoryKey>, CognitiveStoreError> {
    rows.iter()
        .map(|row| decode_memory_key(row, "memory_id", "revision"))
        .collect()
}

fn decode_memory_key(
    row: &sqlx::sqlite::SqliteRow,
    memory_column: &str,
    revision_column: &str,
) -> Result<MemoryKey, CognitiveStoreError> {
    let revision: i64 = row.try_get(revision_column).map_err(unavailable)?;
    Ok(MemoryKey {
        memory_id: row.try_get(memory_column).map_err(unavailable)?,
        revision: u64::try_from(revision)
            .map_err(|_| CognitiveStoreError::Corrupt("negative memory revision".to_string()))?,
    })
}

fn binding_from_explanation(explanation: &MemoryExplanation) -> MemoryRevalidationBinding {
    MemoryRevalidationBinding {
        memory: explanation.memory.id.clone(),
        scope: explanation.memory.scope.clone(),
        content_sha256: explanation.memory.content_sha256.clone(),
        verification: explanation.memory.verification,
        lifecycle: explanation.memory.lifecycle.clone(),
        valid_from_unix_seconds: explanation.memory.valid_from_unix_seconds,
        valid_to_unix_seconds: explanation.memory.valid_to_unix_seconds,
        citations: explanation
            .citations
            .iter()
            .map(|source| SourceRevalidationBinding {
                id: source.id.clone(),
                scope: source.scope.clone(),
                content_sha256: source.content_sha256.clone(),
            })
            .collect(),
        kg_projection_generation: explanation.kg_projection_generation,
    }
}

fn eligible(memory: &MemoryRevisionRecord, now: i64) -> bool {
    memory.verification == MemoryVerification::Verified
        && memory.lifecycle == MemoryLifecycleState::Active
        && memory.valid_from_unix_seconds <= now
        && memory.valid_to_unix_seconds.is_none_or(|until| now < until)
}

fn channel_limit() -> i64 {
    i64::try_from(MAX_RETRIEVAL_CHANNEL_CANDIDATES).unwrap_or(i64::MAX)
}

fn to_i64(value: u64, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| CognitiveStoreError::Invalid(format!("{label} exceeds i64")))
}

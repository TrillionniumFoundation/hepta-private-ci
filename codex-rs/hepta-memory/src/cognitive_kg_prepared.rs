//! Prepared cognitive KG publication candidate.
//!
//! This module separates the expensive, read-only projection reconstruction
//! from the short SQLite writer transaction. A prepared plan is bound to the
//! exact current projection generation, complete source cut, predecessor
//! generation and trigger revision. The writer still inserts source facts and
//! advances the selected generation in one `BEGIN IMMEDIATE` transaction; a
//! stale generation fence causes a bounded reprepare rather than publishing a
//! plan against a different cut.
//!
//! The legacy full-rebuild-in-writer path remains available as an independent
//! oracle and compatibility fallback. These APIs do not alter activation,
//! acceptance or release state.

use std::collections::BTreeMap;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgePublicationReceiptV2;
use codex_hepta_kg::publish_generation;
use codex_hepta_types::Digest32;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::CognitiveAccess;
use crate::CognitiveProjectionReceipt;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CognitiveWriteReceipt;
use crate::ForgetMemoryDraft;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryRevisionId;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::ProjectionGeneration;
use crate::SourceDraft;
use crate::SourceEventId;
use crate::SourceRevisionId;
use crate::StableMemoryId;
use crate::cognitive_intelligence_writer::CanonicalFactSet;
use crate::cognitive_intelligence_writer::canonical_entity_id;
use crate::cognitive_intelligence_writer::canonical_relation_id;
use crate::cognitive_intelligence_writer::occurrence_edge_id;
use crate::cognitive_intelligence_writer::occurrence_node_id;
use crate::cognitive_kg_store::MAX_PROJECTION_SCOPES;
use crate::cognitive_kg_store::MAX_SCOPE_EDGES;
use crate::cognitive_kg_store::MAX_SCOPE_HEADS;
use crate::cognitive_kg_store::MAX_SCOPE_NODES;
use crate::cognitive_kg_store::ProjectionEdge;
use crate::cognitive_kg_store::ProjectionHead;
use crate::cognitive_kg_store::ProjectionNode;
use crate::cognitive_kg_store::canonical_generation_from_projection;
use crate::cognitive_kg_store::graph_source_vector_digest_tx;
use crate::cognitive_kg_store::input_heads_digest;
use crate::cognitive_kg_store::load_canonical_generation_tx;
use crate::cognitive_kg_store::output_digest;
use crate::cognitive_kg_store::sha256_from_digest32;
use crate::cognitive_memory_store::validate_revision_draft;
use crate::cognitive_model::MAX_SOURCE_BYTES;
use crate::cognitive_store::unavailable;
use crate::cognitive_store::validate_key;
use crate::framing::frame_part;

const MAX_PREPARED_RETRIES: u64 = 1;
const PREPARED_STORAGE_MODE: &str = "revision_facts_v1";
const TOMBSTONE_CONTENT: &str = "Memory withdrawn by explicit user request.";

/// Operation-local evidence for the prepared writer path.
///
/// Durations are observations on the executing host, not host-independent SLOs.
/// Counts are exact for one successful call, including any stale-plan reprepare.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct CognitiveKgPreparedOperationMetricsV1 {
    pub snapshot_read_nanos: u64,
    pub predecessor_reconstruct_nanos: u64,
    pub build_validate_nanos: u64,
    pub writer_lock_wait_nanos: u64,
    pub writer_hold_nanos: u64,
    pub cas_conflicts: u64,
    pub retry_count: u64,
    pub planned_heads: u64,
    pub planned_nodes: u64,
    pub planned_edges: u64,
}

impl CognitiveKgPreparedOperationMetricsV1 {
    fn add_prepare(&mut self, other: &Self) {
        self.snapshot_read_nanos = self
            .snapshot_read_nanos
            .saturating_add(other.snapshot_read_nanos);
        self.predecessor_reconstruct_nanos = self
            .predecessor_reconstruct_nanos
            .saturating_add(other.predecessor_reconstruct_nanos);
        self.build_validate_nanos = self
            .build_validate_nanos
            .saturating_add(other.build_validate_nanos);
        self.planned_heads = other.planned_heads;
        self.planned_nodes = other.planned_nodes;
        self.planned_edges = other.planned_edges;
    }
}

/// A semantic write plus operation-local prepared-path measurements.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CognitivePreparedWriteReceiptV1 {
    pub write: CognitiveWriteReceipt,
    pub metrics: CognitiveKgPreparedOperationMetricsV1,
}

#[derive(Clone, Debug)]
pub(crate) struct PreparedCognitiveProjectionV1 {
    projection_scope: String,
    expected_generation: i64,
    trigger_memory_id: String,
    trigger_memory_revision: u64,
    trigger_source_id: String,
    trigger_source_revision: u64,
    trigger_fact_set_sha256: Sha256Digest,
    trigger_entity_count: u64,
    trigger_relation_count: u64,
    input_heads_sha256: Sha256Digest,
    output_sha256: Sha256Digest,
    physical_node_count: u64,
    physical_edge_count: u64,
    candidate: KnowledgeGenerationV2,
    publication: KnowledgePublicationReceiptV2,
    metrics: CognitiveKgPreparedOperationMetricsV1,
}

#[derive(Debug)]
enum PreparedFenceError {
    Stale,
    Store(CognitiveStoreError),
}

impl From<CognitiveStoreError> for PreparedFenceError {
    fn from(error: CognitiveStoreError) -> Self {
        Self::Store(error)
    }
}

impl CognitiveStore {
    /// Execute a complete remember mutation through the read-snapshot prepared
    /// writer. The durable source, memory, facts and projection receipt still
    /// commit atomically in one writer transaction.
    pub async fn remember_with_kg_prepared(
        &self,
        access: &CognitiveAccess,
        source: &SourceDraft,
        draft: &MemoryDraft,
        facts: &KgFactSetDraft,
    ) -> Result<CognitivePreparedWriteReceiptV1, CognitiveStoreError> {
        validate_source_binding(source, &draft.revision.scope, &draft.revision.content)?;
        if draft.revision.lifecycle != MemoryLifecycleState::Active {
            return Err(CognitiveStoreError::Invalid(
                "remember requires an active memory revision".to_string(),
            ));
        }
        validate_fact_eligibility(&draft.revision, facts)?;
        self.authorize(access, &draft.revision.scope)?;
        validate_key(&draft.stable_key, "stable memory key")?;
        validate_revision_draft(&draft.revision)?;
        validate_source_shape(source)?;
        if !draft.revision.citations.is_empty() {
            return Err(CognitiveStoreError::Invalid(
                "product cognitive writer owns the exact source citation set".to_string(),
            ));
        }

        let citation = predicted_source(self, source);
        let mut bound_revision = draft.revision.clone();
        bound_revision.citations.push(citation.clone());
        let predicted_memory = predicted_memory_record(
            StableMemoryId::for_key(
                &self.owner_agent_id,
                &bound_revision.scope,
                &draft.stable_key,
            ),
            1,
            None,
            &bound_revision,
        );
        let canonical =
            self.canonicalize_fact_set(&predicted_memory, &citation, facts, "structured_cognitive_kg_v1")?;

        let mut aggregate = CognitiveKgPreparedOperationMetricsV1::default();
        for attempt in 0..=MAX_PREPARED_RETRIES {
            let prepared = self
                .prepare_cognitive_projection_v1(&predicted_memory, &citation, &canonical)
                .await?;
            aggregate.add_prepare(&prepared.metrics);

            let wait_started = Instant::now();
            let mut transaction = self
                .pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(unavailable)?;
            aggregate.writer_lock_wait_nanos = aggregate
                .writer_lock_wait_nanos
                .saturating_add(elapsed_nanos(wait_started.elapsed()));
            let hold_started = Instant::now();

            match prepared
                .verify_generation_fence_tx(&mut transaction)
                .await
            {
                Ok(()) => {}
                Err(PreparedFenceError::Stale) if attempt < MAX_PREPARED_RETRIES => {
                    aggregate.cas_conflicts = aggregate.cas_conflicts.saturating_add(1);
                    aggregate.retry_count = aggregate.retry_count.saturating_add(1);
                    aggregate.writer_hold_nanos = aggregate
                        .writer_hold_nanos
                        .saturating_add(elapsed_nanos(hold_started.elapsed()));
                    transaction.rollback().await.map_err(unavailable)?;
                    continue;
                }
                Err(PreparedFenceError::Stale) => {
                    return Err(CognitiveStoreError::Conflict(
                        "KG projection generation changed during prepared remember".to_string(),
                    ));
                }
                Err(PreparedFenceError::Store(error)) => return Err(error),
            }

            let actual_source = self
                .append_source_tx(&mut transaction, access, source)
                .await?;
            let mut actual_draft = draft.clone();
            actual_draft.revision.citations.push(actual_source.clone());
            let actual_memory = self
                .create_memory_revision_tx(&mut transaction, access, &actual_draft)
                .await?;
            let actual_facts = self.canonicalize_fact_set(
                &actual_memory,
                &actual_source,
                facts,
                "structured_cognitive_kg_v1",
            )?;
            self.insert_revision_facts_tx(
                &mut transaction,
                &actual_memory,
                &actual_source,
                &actual_facts,
            )
            .await?;
            verify_prepared_trigger(
                &predicted_memory,
                &citation,
                &canonical,
                &actual_memory,
                &actual_source,
                &actual_facts,
            )?;
            let projection = self
                .commit_prepared_cognitive_projection_tx(
                    &mut transaction,
                    &actual_memory,
                    &actual_source,
                    &actual_facts,
                    &prepared,
                )
                .await?;
            transaction.commit().await.map_err(unavailable)?;
            aggregate.writer_hold_nanos = aggregate
                .writer_hold_nanos
                .saturating_add(elapsed_nanos(hold_started.elapsed()));
            return Ok(CognitivePreparedWriteReceiptV1 {
                write: CognitiveWriteReceipt {
                    memory: actual_memory,
                    source: actual_source,
                    projection,
                },
                metrics: aggregate,
            });
        }
        unreachable!("bounded prepared remember loop must return")
    }

    /// Execute a correction through the prepared writer. The user supplied
    /// expected revision remains the authoritative CAS; reprepare never advances
    /// it or turns a target-memory conflict into a retry.
    pub async fn correct_with_kg_prepared(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &MemoryRevisionDraft,
        facts: &KgFactSetDraft,
    ) -> Result<CognitivePreparedWriteReceiptV1, CognitiveStoreError> {
        validate_source_binding(source, &draft.scope, &draft.content)?;
        if draft.verification != MemoryVerification::Verified
            || draft.lifecycle != MemoryLifecycleState::Active
        {
            return Err(CognitiveStoreError::Invalid(
                "correction requires a verified active memory revision".to_string(),
            ));
        }
        validate_fact_eligibility(draft, facts)?;
        validate_revision_draft(draft)?;
        validate_source_shape(source)?;
        if !draft.citations.is_empty() {
            return Err(CognitiveStoreError::Invalid(
                "product cognitive writer owns the exact source citation set".to_string(),
            ));
        }

        let mut aggregate = CognitiveKgPreparedOperationMetricsV1::default();
        for attempt in 0..=MAX_PREPARED_RETRIES {
            let current = self.latest_memory(access, memory_id).await?;
            validate_expected_predecessor(&current, expected_revision, &draft.scope)?;
            if current.lifecycle != MemoryLifecycleState::Active {
                return Err(CognitiveStoreError::Conflict(
                    "a tombstoned memory cannot be resurrected by correction".to_string(),
                ));
            }
            let citation = predicted_source(self, source);
            let mut bound_revision = draft.clone();
            bound_revision.citations.push(citation.clone());
            let predicted_memory = predicted_memory_record(
                memory_id.clone(),
                expected_revision.checked_add(1).ok_or_else(|| {
                    CognitiveStoreError::Corrupt("memory revision overflow".to_string())
                })?,
                Some(expected_revision),
                &bound_revision,
            );
            let canonical = self.canonicalize_fact_set(
                &predicted_memory,
                &citation,
                facts,
                "structured_cognitive_kg_v1",
            )?;
            let prepared = self
                .prepare_cognitive_projection_v1(&predicted_memory, &citation, &canonical)
                .await?;
            aggregate.add_prepare(&prepared.metrics);

            let wait_started = Instant::now();
            let mut transaction = self
                .pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(unavailable)?;
            aggregate.writer_lock_wait_nanos = aggregate
                .writer_lock_wait_nanos
                .saturating_add(elapsed_nanos(wait_started.elapsed()));
            let hold_started = Instant::now();
            match prepared
                .verify_generation_fence_tx(&mut transaction)
                .await
            {
                Ok(()) => {}
                Err(PreparedFenceError::Stale) if attempt < MAX_PREPARED_RETRIES => {
                    aggregate.cas_conflicts = aggregate.cas_conflicts.saturating_add(1);
                    aggregate.retry_count = aggregate.retry_count.saturating_add(1);
                    aggregate.writer_hold_nanos = aggregate
                        .writer_hold_nanos
                        .saturating_add(elapsed_nanos(hold_started.elapsed()));
                    transaction.rollback().await.map_err(unavailable)?;
                    continue;
                }
                Err(PreparedFenceError::Stale) => {
                    return Err(CognitiveStoreError::Conflict(
                        "KG projection generation changed during prepared correction".to_string(),
                    ));
                }
                Err(PreparedFenceError::Store(error)) => return Err(error),
            }

            let actual_source = self
                .append_source_tx(&mut transaction, access, source)
                .await?;
            let mut actual_draft = draft.clone();
            actual_draft.citations.push(actual_source.clone());
            let actual_memory = self
                .revise_memory_revision_tx(
                    &mut transaction,
                    access,
                    memory_id,
                    expected_revision,
                    &actual_draft,
                )
                .await?;
            let actual_facts = self.canonicalize_fact_set(
                &actual_memory,
                &actual_source,
                facts,
                "structured_cognitive_kg_v1",
            )?;
            self.insert_revision_facts_tx(
                &mut transaction,
                &actual_memory,
                &actual_source,
                &actual_facts,
            )
            .await?;
            verify_prepared_trigger(
                &predicted_memory,
                &citation,
                &canonical,
                &actual_memory,
                &actual_source,
                &actual_facts,
            )?;
            let projection = self
                .commit_prepared_cognitive_projection_tx(
                    &mut transaction,
                    &actual_memory,
                    &actual_source,
                    &actual_facts,
                    &prepared,
                )
                .await?;
            transaction.commit().await.map_err(unavailable)?;
            aggregate.writer_hold_nanos = aggregate
                .writer_hold_nanos
                .saturating_add(elapsed_nanos(hold_started.elapsed()));
            return Ok(CognitivePreparedWriteReceiptV1 {
                write: CognitiveWriteReceipt {
                    memory: actual_memory,
                    source: actual_source,
                    projection,
                },
                metrics: aggregate,
            });
        }
        unreachable!("bounded prepared correction loop must return")
    }

    /// Execute a tombstone mutation through the prepared writer.
    pub async fn forget_with_kg_prepared(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &ForgetMemoryDraft,
    ) -> Result<CognitivePreparedWriteReceiptV1, CognitiveStoreError> {
        validate_source_binding(source, &draft.scope, &draft.reason)?;
        validate_source_shape(source)?;
        let revision = MemoryRevisionDraft {
            scope: draft.scope.clone(),
            content: TOMBSTONE_CONTENT.to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Tombstoned {
                reason: draft.reason.clone(),
            },
            valid_from_unix_seconds: draft.valid_from_unix_seconds,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        };
        validate_revision_draft(&revision)?;
        let facts = KgFactSetDraft::default();

        let mut aggregate = CognitiveKgPreparedOperationMetricsV1::default();
        for attempt in 0..=MAX_PREPARED_RETRIES {
            let current = self.latest_memory(access, memory_id).await?;
            validate_expected_predecessor(&current, expected_revision, &draft.scope)?;
            let citation = predicted_source(self, source);
            let mut bound_revision = revision.clone();
            bound_revision.citations.push(citation.clone());
            let predicted_memory = predicted_memory_record(
                memory_id.clone(),
                expected_revision.checked_add(1).ok_or_else(|| {
                    CognitiveStoreError::Corrupt("memory revision overflow".to_string())
                })?,
                Some(expected_revision),
                &bound_revision,
            );
            let canonical = self.canonicalize_fact_set(
                &predicted_memory,
                &citation,
                &facts,
                "structured_cognitive_kg_v1",
            )?;
            let prepared = self
                .prepare_cognitive_projection_v1(&predicted_memory, &citation, &canonical)
                .await?;
            aggregate.add_prepare(&prepared.metrics);

            let wait_started = Instant::now();
            let mut transaction = self
                .pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(unavailable)?;
            aggregate.writer_lock_wait_nanos = aggregate
                .writer_lock_wait_nanos
                .saturating_add(elapsed_nanos(wait_started.elapsed()));
            let hold_started = Instant::now();
            match prepared
                .verify_generation_fence_tx(&mut transaction)
                .await
            {
                Ok(()) => {}
                Err(PreparedFenceError::Stale) if attempt < MAX_PREPARED_RETRIES => {
                    aggregate.cas_conflicts = aggregate.cas_conflicts.saturating_add(1);
                    aggregate.retry_count = aggregate.retry_count.saturating_add(1);
                    aggregate.writer_hold_nanos = aggregate
                        .writer_hold_nanos
                        .saturating_add(elapsed_nanos(hold_started.elapsed()));
                    transaction.rollback().await.map_err(unavailable)?;
                    continue;
                }
                Err(PreparedFenceError::Stale) => {
                    return Err(CognitiveStoreError::Conflict(
                        "KG projection generation changed during prepared forget".to_string(),
                    ));
                }
                Err(PreparedFenceError::Store(error)) => return Err(error),
            }

            let actual_source = self
                .append_source_tx(&mut transaction, access, source)
                .await?;
            let mut actual_revision = revision.clone();
            actual_revision.citations.push(actual_source.clone());
            let actual_memory = self
                .revise_memory_revision_tx(
                    &mut transaction,
                    access,
                    memory_id,
                    expected_revision,
                    &actual_revision,
                )
                .await?;
            let actual_facts = self.canonicalize_fact_set(
                &actual_memory,
                &actual_source,
                &facts,
                "structured_cognitive_kg_v1",
            )?;
            self.insert_revision_facts_tx(
                &mut transaction,
                &actual_memory,
                &actual_source,
                &actual_facts,
            )
            .await?;
            verify_prepared_trigger(
                &predicted_memory,
                &citation,
                &canonical,
                &actual_memory,
                &actual_source,
                &actual_facts,
            )?;
            let projection = self
                .commit_prepared_cognitive_projection_tx(
                    &mut transaction,
                    &actual_memory,
                    &actual_source,
                    &actual_facts,
                    &prepared,
                )
                .await?;
            transaction.commit().await.map_err(unavailable)?;
            aggregate.writer_hold_nanos = aggregate
                .writer_hold_nanos
                .saturating_add(elapsed_nanos(hold_started.elapsed()));
            return Ok(CognitivePreparedWriteReceiptV1 {
                write: CognitiveWriteReceipt {
                    memory: actual_memory,
                    source: actual_source,
                    projection,
                },
                metrics: aggregate,
            });
        }
        unreachable!("bounded prepared forget loop must return")
    }

    pub(crate) async fn prepare_cognitive_projection_v1(
        &self,
        trigger_memory: &MemoryRevisionRecord,
        trigger_source: &SourceRevisionId,
        trigger_facts: &CanonicalFactSet,
    ) -> Result<PreparedCognitiveProjectionV1, CognitiveStoreError> {
        if trigger_memory.citations.first() != Some(trigger_source) {
            return Err(CognitiveStoreError::Corrupt(
                "prepared projection trigger source is not the revision's exact citation"
                    .to_string(),
            ));
        }
        let snapshot_started = Instant::now();
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let projection_scope = trigger_memory.scope.projection_key();
        let expected_generation: i64 = sqlx::query_scalar(
            "SELECT generation FROM kg_projection WHERE projection_scope = ?",
        )
        .bind(&projection_scope)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .unwrap_or(0);
        if expected_generation < 0 {
            return Err(CognitiveStoreError::Corrupt(
                "negative KG projection generation".to_string(),
            ));
        }

        let (scope_kind, workspace_sha256) = trigger_memory.scope.database_parts();
        let head_rows = sqlx::query(
            "SELECT r.memory_id, r.revision, r.content_sha256,
                    r.verification, r.lifecycle, s.fact_set_sha256,
                    s.entity_count, s.relation_count,
                    (SELECT COUNT(*) FROM kg_revision_entities e
                     WHERE e.memory_id = r.memory_id
                       AND e.memory_revision = r.revision) AS actual_entity_count,
                    (SELECT COUNT(*) FROM kg_revision_relations q
                     WHERE q.memory_id = r.memory_id
                       AND q.memory_revision = r.revision) AS actual_relation_count
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_fact_sets s
               ON s.memory_id = r.memory_id AND s.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ? AND r.memory_id != ?
             ORDER BY r.memory_id LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(trigger_memory.id.memory_id.as_str())
        .bind(limit_plus_one(MAX_SCOPE_HEADS)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if head_rows.len() >= MAX_SCOPE_HEADS {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_HEADS}-memory scope limit"
            )));
        }
        let mut heads = Vec::with_capacity(head_rows.len().saturating_add(1));
        for row in head_rows {
            let declared_entities: i64 = row.try_get("entity_count").map_err(unavailable)?;
            let actual_entities: i64 = row.try_get("actual_entity_count").map_err(unavailable)?;
            let declared_relations: i64 = row.try_get("relation_count").map_err(unavailable)?;
            let actual_relations: i64 =
                row.try_get("actual_relation_count").map_err(unavailable)?;
            if declared_entities != actual_entities || declared_relations != actual_relations {
                return Err(CognitiveStoreError::Corrupt(
                    "current KG fact-set receipt does not match its immutable facts".to_string(),
                ));
            }
            heads.push(ProjectionHead {
                memory_id: row.try_get("memory_id").map_err(unavailable)?,
                revision: row.try_get("revision").map_err(unavailable)?,
                content_sha256: row.try_get("content_sha256").map_err(unavailable)?,
                verification: row.try_get("verification").map_err(unavailable)?,
                lifecycle: row.try_get("lifecycle").map_err(unavailable)?,
                fact_set_sha256: row.try_get("fact_set_sha256").map_err(unavailable)?,
            });
        }
        let trigger_revision = to_i64(trigger_memory.id.revision, "memory revision")?;
        heads.push(ProjectionHead {
            memory_id: trigger_memory.id.memory_id.as_str().to_string(),
            revision: trigger_revision,
            content_sha256: trigger_memory.content_sha256.as_str().to_string(),
            verification: verification_name(trigger_memory.verification).to_string(),
            lifecycle: lifecycle_name(&trigger_memory.lifecycle).to_string(),
            fact_set_sha256: trigger_facts.digest.as_str().to_string(),
        });
        heads.sort_by(|left, right| left.memory_id.cmp(&right.memory_id));
        let input_heads_sha256 = input_heads_digest(&projection_scope, &heads);
        let source_snapshot_digest: Digest32 = input_heads_sha256
            .as_str()
            .parse()
            .map_err(CognitiveStoreError::Corrupt)?;
        let generation_vector_digest = planned_generation_vector_digest_tx(
            &mut transaction,
            self.owner_agent_id.as_str(),
            &trigger_memory.scope,
            trigger_source,
            &trigger_memory.lifecycle,
            source_snapshot_digest,
        )
        .await?;

        let node_rows = sqlx::query(
            "SELECT e.memory_id, e.memory_revision, e.entity_key,
                    e.canonical_entity_id, e.entity_type, e.label,
                    e.valid_from_unix_seconds, e.valid_to_unix_seconds,
                    e.source_id, e.source_revision
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_entities e
               ON e.memory_id = r.memory_id AND e.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ? AND r.memory_id != ?
               AND r.verification = 'verified' AND r.lifecycle = 'active'
             ORDER BY e.memory_id, e.memory_revision, e.entity_key LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(trigger_memory.id.memory_id.as_str())
        .bind(limit_plus_one(MAX_SCOPE_NODES)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if node_rows.len() > MAX_SCOPE_NODES {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_NODES}-node scope limit"
            )));
        }
        let mut ordered_nodes = Vec::<(String, i64, String, ProjectionNode)>::new();
        let mut canonical_shapes = BTreeMap::<String, (String, String)>::new();
        for row in node_rows {
            let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
            let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
            let entity_key: String = row.try_get("entity_key").map_err(unavailable)?;
            let canonical_entity_id_value: String =
                row.try_get("canonical_entity_id").map_err(unavailable)?;
            if canonical_entity_id_value
                != canonical_entity_id(&self.owner_agent_id, &trigger_memory.scope, &entity_key)
            {
                return Err(CognitiveStoreError::Corrupt(
                    "KG entity identity does not match owner, scope and entity key".to_string(),
                ));
            }
            let entity_type: String = row.try_get("entity_type").map_err(unavailable)?;
            let label: String = row.try_get("label").map_err(unavailable)?;
            observe_shape(
                &mut canonical_shapes,
                &canonical_entity_id_value,
                &entity_type,
                &label,
            )?;
            ordered_nodes.push((
                memory_id.clone(),
                memory_revision,
                entity_key.clone(),
                ProjectionNode {
                    node_id: occurrence_node_id(&memory_id, memory_revision, &entity_key),
                    canonical_entity_id: canonical_entity_id_value,
                    entity_type,
                    label,
                    valid_from: row
                        .try_get("valid_from_unix_seconds")
                        .map_err(unavailable)?,
                    valid_to: row
                        .try_get("valid_to_unix_seconds")
                        .map_err(unavailable)?,
                    memory_id,
                    memory_revision,
                    source_id: row.try_get("source_id").map_err(unavailable)?,
                    source_revision: row.try_get("source_revision").map_err(unavailable)?,
                },
            ));
        }
        if trigger_memory.verification == MemoryVerification::Verified
            && trigger_memory.lifecycle == MemoryLifecycleState::Active
        {
            for entity in &trigger_facts.entities {
                observe_shape(
                    &mut canonical_shapes,
                    &entity.canonical_entity_id,
                    &entity.entity_type,
                    &entity.label,
                )?;
                ordered_nodes.push((
                    trigger_memory.id.memory_id.as_str().to_string(),
                    trigger_revision,
                    entity.key.clone(),
                    ProjectionNode {
                        node_id: occurrence_node_id(
                            trigger_memory.id.memory_id.as_str(),
                            trigger_revision,
                            &entity.key,
                        ),
                        canonical_entity_id: entity.canonical_entity_id.clone(),
                        entity_type: entity.entity_type.clone(),
                        label: entity.label.clone(),
                        valid_from: trigger_memory.valid_from_unix_seconds,
                        valid_to: trigger_memory.valid_to_unix_seconds,
                        memory_id: trigger_memory.id.memory_id.as_str().to_string(),
                        memory_revision: trigger_revision,
                        source_id: trigger_source.source_id.as_str().to_string(),
                        source_revision: to_i64(trigger_source.revision, "source revision")?,
                    },
                ));
            }
        }
        if ordered_nodes.len() > MAX_SCOPE_NODES {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_NODES}-node scope limit"
            )));
        }
        ordered_nodes.sort_by(|left, right| {
            (&left.0, left.1, &left.2).cmp(&(&right.0, right.1, &right.2))
        });
        let nodes = ordered_nodes
            .into_iter()
            .map(|(_, _, _, node)| node)
            .collect::<Vec<_>>();

        let relation_rows = sqlx::query(
            "SELECT q.memory_id, q.memory_revision, q.relation_key,
                    q.canonical_relation_id, q.from_entity_key, q.to_entity_key,
                    q.from_canonical_entity_id, q.to_canonical_entity_id,
                    q.relation, q.valid_from_unix_seconds,
                    q.valid_to_unix_seconds, q.source_id, q.source_revision
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_relations q
               ON q.memory_id = r.memory_id AND q.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ? AND r.memory_id != ?
               AND r.verification = 'verified' AND r.lifecycle = 'active'
             ORDER BY q.memory_id, q.memory_revision, q.relation_key LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(trigger_memory.id.memory_id.as_str())
        .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if relation_rows.len() > MAX_SCOPE_EDGES {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_EDGES}-edge scope limit"
            )));
        }
        let mut ordered_edges = Vec::<(String, i64, String, ProjectionEdge)>::new();
        for row in relation_rows {
            let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
            let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
            let relation_key: String = row.try_get("relation_key").map_err(unavailable)?;
            let from_entity_key: String =
                row.try_get("from_entity_key").map_err(unavailable)?;
            let to_entity_key: String = row.try_get("to_entity_key").map_err(unavailable)?;
            let from_canonical_entity_id: String = row
                .try_get("from_canonical_entity_id")
                .map_err(unavailable)?;
            let to_canonical_entity_id: String = row
                .try_get("to_canonical_entity_id")
                .map_err(unavailable)?;
            let relation: String = row.try_get("relation").map_err(unavailable)?;
            let stored_canonical_relation_id: String = row
                .try_get("canonical_relation_id")
                .map_err(unavailable)?;
            let expected_canonical_relation_id = canonical_relation_id(
                &self.owner_agent_id,
                &trigger_memory.scope,
                &from_canonical_entity_id,
                &relation,
                &to_canonical_entity_id,
            );
            if stored_canonical_relation_id != expected_canonical_relation_id {
                return Err(CognitiveStoreError::Corrupt(
                    "KG relation identity does not match its canonical endpoints".to_string(),
                ));
            }
            ordered_edges.push((
                memory_id.clone(),
                memory_revision,
                relation_key.clone(),
                ProjectionEdge {
                    edge_id: occurrence_edge_id(&memory_id, memory_revision, &relation_key),
                    canonical_relation_id: stored_canonical_relation_id,
                    from_node_id: occurrence_node_id(
                        &memory_id,
                        memory_revision,
                        &from_entity_key,
                    ),
                    to_node_id: occurrence_node_id(
                        &memory_id,
                        memory_revision,
                        &to_entity_key,
                    ),
                    relation,
                    valid_from: row
                        .try_get("valid_from_unix_seconds")
                        .map_err(unavailable)?,
                    valid_to: row
                        .try_get("valid_to_unix_seconds")
                        .map_err(unavailable)?,
                    memory_id,
                    memory_revision,
                    source_id: row.try_get("source_id").map_err(unavailable)?,
                    source_revision: row.try_get("source_revision").map_err(unavailable)?,
                },
            ));
        }
        if trigger_memory.verification == MemoryVerification::Verified
            && trigger_memory.lifecycle == MemoryLifecycleState::Active
        {
            for relation in &trigger_facts.relations {
                let expected_canonical_relation_id = canonical_relation_id(
                    &self.owner_agent_id,
                    &trigger_memory.scope,
                    &relation.from_canonical_entity_id,
                    &relation.relation,
                    &relation.to_canonical_entity_id,
                );
                if relation.canonical_relation_id != expected_canonical_relation_id {
                    return Err(CognitiveStoreError::Corrupt(
                        "prepared KG relation identity failed canonical recomputation".to_string(),
                    ));
                }
                ordered_edges.push((
                    trigger_memory.id.memory_id.as_str().to_string(),
                    trigger_revision,
                    relation.key.clone(),
                    ProjectionEdge {
                        edge_id: occurrence_edge_id(
                            trigger_memory.id.memory_id.as_str(),
                            trigger_revision,
                            &relation.key,
                        ),
                        canonical_relation_id: relation.canonical_relation_id.clone(),
                        from_node_id: occurrence_node_id(
                            trigger_memory.id.memory_id.as_str(),
                            trigger_revision,
                            &relation.from_entity_key,
                        ),
                        to_node_id: occurrence_node_id(
                            trigger_memory.id.memory_id.as_str(),
                            trigger_revision,
                            &relation.to_entity_key,
                        ),
                        relation: relation.relation.clone(),
                        valid_from: trigger_memory.valid_from_unix_seconds,
                        valid_to: trigger_memory.valid_to_unix_seconds,
                        memory_id: trigger_memory.id.memory_id.as_str().to_string(),
                        memory_revision: trigger_revision,
                        source_id: trigger_source.source_id.as_str().to_string(),
                        source_revision: to_i64(trigger_source.revision, "source revision")?,
                    },
                ));
            }
        }
        if ordered_edges.len() > MAX_SCOPE_EDGES {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_EDGES}-edge scope limit"
            )));
        }
        ordered_edges.sort_by(|left, right| {
            (&left.0, left.1, &left.2).cmp(&(&right.0, right.1, &right.2))
        });
        let edges = ordered_edges
            .into_iter()
            .map(|(_, _, _, edge)| edge)
            .collect::<Vec<_>>();
        let output_sha256 = output_digest(&projection_scope, &nodes, &edges);
        let snapshot_read_nanos = elapsed_nanos(snapshot_started.elapsed());

        let predecessor_started = Instant::now();
        let predecessor = if expected_generation == 0 {
            None
        } else {
            Some(
                load_canonical_generation_tx(
                    &mut transaction,
                    &projection_scope,
                    expected_generation,
                )
                .await?,
            )
        };
        let predecessor_reconstruct_nanos = elapsed_nanos(predecessor_started.elapsed());
        transaction.commit().await.map_err(unavailable)?;

        let build_started = Instant::now();
        let next_generation = expected_generation
            .checked_add(1)
            .ok_or_else(|| CognitiveStoreError::Corrupt("KG generation overflow".to_string()))?;
        let candidate = canonical_generation_from_projection(
            u64::try_from(next_generation)
                .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?,
            &input_heads_sha256,
            generation_vector_digest,
            &nodes,
            &edges,
        )?;
        let publication =
            publish_generation(predecessor.as_ref(), &candidate).map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "prepared hepta-kg V2 publication rejected projection: {error}"
                ))
            })?;
        let build_validate_nanos = elapsed_nanos(build_started.elapsed());
        Ok(PreparedCognitiveProjectionV1 {
            projection_scope,
            expected_generation,
            trigger_memory_id: trigger_memory.id.memory_id.as_str().to_string(),
            trigger_memory_revision: trigger_memory.id.revision,
            trigger_source_id: trigger_source.source_id.as_str().to_string(),
            trigger_source_revision: trigger_source.revision,
            trigger_fact_set_sha256: trigger_facts.digest.clone(),
            trigger_entity_count: usize_to_u64(trigger_facts.entities.len()),
            trigger_relation_count: usize_to_u64(trigger_facts.relations.len()),
            input_heads_sha256,
            output_sha256,
            physical_node_count: usize_to_u64(nodes.len()),
            physical_edge_count: usize_to_u64(edges.len()),
            candidate,
            publication,
            metrics: CognitiveKgPreparedOperationMetricsV1 {
                snapshot_read_nanos,
                predecessor_reconstruct_nanos,
                build_validate_nanos,
                planned_heads: usize_to_u64(heads.len()),
                planned_nodes: usize_to_u64(nodes.len()),
                planned_edges: usize_to_u64(edges.len()),
                ..CognitiveKgPreparedOperationMetricsV1::default()
            },
        })
    }

    async fn commit_prepared_cognitive_projection_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        trigger_memory: &MemoryRevisionRecord,
        trigger_source: &SourceRevisionId,
        trigger_facts: &CanonicalFactSet,
        prepared: &PreparedCognitiveProjectionV1,
    ) -> Result<CognitiveProjectionReceipt, CognitiveStoreError> {
        prepared.validate_trigger(trigger_memory, trigger_source, trigger_facts)?;
        prepared.candidate.validate().map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "prepared KG candidate failed commit validation: {error}"
            ))
        })?;
        prepared.publication.validate().map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "prepared KG publication failed commit validation: {error}"
            ))
        })?;
        let source_vector = graph_source_vector_digest_tx(
            transaction,
            self.owner_agent_id.as_str(),
            &trigger_memory.scope,
            prepared.candidate.source_snapshot_digest,
        )
        .await?;
        if source_vector != prepared.candidate.generation_vector_digest {
            return Err(CognitiveStoreError::Conflict(
                "KG source vector changed after prepared projection snapshot".to_string(),
            ));
        }
        verify_committed_trigger_tx(transaction, trigger_memory, trigger_facts).await?;

        let next = to_i64(prepared.candidate.generation.get(), "KG generation")?;
        let generation_sha256 = sha256_from_digest32(prepared.candidate.generation_digest)?;
        let publication_sha256 = sha256_from_digest32(prepared.publication.publication_digest)?;
        sqlx::query(
            "INSERT INTO kg_projection_generation_receipts (
                projection_scope, generation, trigger_memory_id,
                trigger_memory_revision, fact_set_sha256, input_heads_sha256,
                output_sha256, entity_count, relation_count, node_count,
                edge_count, recorded_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch())",
        )
        .bind(&prepared.projection_scope)
        .bind(next)
        .bind(&prepared.trigger_memory_id)
        .bind(to_i64(
            prepared.trigger_memory_revision,
            "trigger memory revision",
        )?)
        .bind(prepared.trigger_fact_set_sha256.as_str())
        .bind(prepared.input_heads_sha256.as_str())
        .bind(prepared.output_sha256.as_str())
        .bind(to_i64(prepared.trigger_entity_count, "entity count")?)
        .bind(to_i64(prepared.trigger_relation_count, "relation count")?)
        .bind(to_i64(prepared.physical_node_count, "projection node count")?)
        .bind(to_i64(prepared.physical_edge_count, "projection edge count")?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        prepared_projection_crash_rendezvous("before_semantic_receipt");
        sqlx::query(
            "INSERT INTO kg_projection_generation_semantics (
                projection_scope, generation, source_snapshot_sha256,
                generation_vector_sha256, graph_profile_sha256,
                generation_sha256, publication_sha256
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&prepared.projection_scope)
        .bind(next)
        .bind(prepared.candidate.source_snapshot_digest.to_string())
        .bind(prepared.candidate.generation_vector_digest.to_string())
        .bind(prepared.candidate.graph_profile_digest.to_string())
        .bind(generation_sha256.as_str())
        .bind(publication_sha256.as_str())
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "INSERT INTO kg_projection_generation_storage (
                projection_scope, generation, storage_mode
             ) VALUES (?, ?, ?)",
        )
        .bind(&prepared.projection_scope)
        .bind(next)
        .bind(PREPARED_STORAGE_MODE)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        prepared_projection_crash_rendezvous(
            "after_semantic_receipt_before_current_pointer",
        );
        let updated = sqlx::query(
            "UPDATE kg_projection SET generation = ?
             WHERE projection_scope = ? AND generation = ?",
        )
        .bind(next)
        .bind(&prepared.projection_scope)
        .bind(prepared.expected_generation)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(CognitiveStoreError::Conflict(
                "KG projection generation changed during prepared commit".to_string(),
            ));
        }
        Ok(CognitiveProjectionReceipt {
            generation: ProjectionGeneration(
                u64::try_from(next).map_err(|_| {
                    CognitiveStoreError::Corrupt("negative KG generation".to_string())
                })?,
            ),
            fact_set_sha256: trigger_facts.digest.clone(),
            input_heads_sha256: prepared.input_heads_sha256.clone(),
            output_sha256: prepared.output_sha256.clone(),
            generation_sha256,
            publication_sha256,
            entity_count: prepared.trigger_entity_count,
            relation_count: prepared.trigger_relation_count,
            node_count: prepared.physical_node_count,
            edge_count: prepared.physical_edge_count,
        })
    }
}

impl PreparedCognitiveProjectionV1 {
    async fn verify_generation_fence_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<(), PreparedFenceError> {
        let existing: Option<i64> = sqlx::query_scalar(
            "SELECT generation FROM kg_projection WHERE projection_scope = ?",
        )
        .bind(&self.projection_scope)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?;
        match existing {
            Some(current) if current == self.expected_generation => Ok(()),
            Some(_) => Err(PreparedFenceError::Stale),
            None if self.expected_generation != 0 => Err(PreparedFenceError::Stale),
            None => {
                let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM kg_projection")
                    .fetch_one(&mut **transaction)
                    .await
                    .map_err(unavailable)?;
                if count >= to_i64(
                    usize_to_u64(MAX_PROJECTION_SCOPES),
                    "projection scope count",
                )? {
                    return Err(PreparedFenceError::Store(CognitiveStoreError::Invalid(
                        format!(
                            "cognitive store exceeds the {MAX_PROJECTION_SCOPES}-projection-scope limit"
                        ),
                    )));
                }
                sqlx::query(
                    "INSERT INTO kg_projection (projection_scope, generation) VALUES (?, 0)",
                )
                .bind(&self.projection_scope)
                .execute(&mut **transaction)
                .await
                .map_err(unavailable)?;
                Ok(())
            }
        }
    }

    fn validate_trigger(
        &self,
        memory: &MemoryRevisionRecord,
        source: &SourceRevisionId,
        facts: &CanonicalFactSet,
    ) -> Result<(), CognitiveStoreError> {
        if self.projection_scope != memory.scope.projection_key()
            || self.trigger_memory_id != memory.id.memory_id.as_str()
            || self.trigger_memory_revision != memory.id.revision
            || self.trigger_source_id != source.source_id.as_str()
            || self.trigger_source_revision != source.revision
            || self.trigger_fact_set_sha256 != facts.digest
            || self.trigger_entity_count != usize_to_u64(facts.entities.len())
            || self.trigger_relation_count != usize_to_u64(facts.relations.len())
            || self.candidate.generation.get()
                != u64::try_from(self.expected_generation)
                    .ok()
                    .and_then(|generation| generation.checked_add(1))
                    .unwrap_or(u64::MAX)
            || self.publication.generation_digest != self.candidate.generation_digest
        {
            return Err(CognitiveStoreError::Corrupt(
                "prepared KG projection does not match committed trigger".to_string(),
            ));
        }
        Ok(())
    }
}

fn predicted_source(store: &CognitiveStore, source: &SourceDraft) -> SourceRevisionId {
    SourceRevisionId::new(SourceEventId::for_event(
        &store.owner_agent_id,
        &source.scope,
        source.kind,
        &source.event_key,
    ))
}

fn predicted_memory_record(
    memory_id: StableMemoryId,
    revision: u64,
    supersedes_revision: Option<u64>,
    draft: &MemoryRevisionDraft,
) -> MemoryRevisionRecord {
    MemoryRevisionRecord {
        id: MemoryRevisionId {
            memory_id,
            revision,
        },
        scope: draft.scope.clone(),
        content: draft.content.clone(),
        content_sha256: Sha256Digest::for_bytes(draft.content.as_bytes()),
        verification: draft.verification,
        lifecycle: draft.lifecycle.clone(),
        valid_from_unix_seconds: draft.valid_from_unix_seconds,
        valid_to_unix_seconds: draft.valid_to_unix_seconds,
        supersedes_revision,
        citations: draft.citations.clone(),
    }
}

fn validate_source_shape(source: &SourceDraft) -> Result<(), CognitiveStoreError> {
    validate_key(&source.event_key, "source event key")?;
    if source.content.is_empty() || source.content.len() > MAX_SOURCE_BYTES {
        return Err(CognitiveStoreError::Invalid(format!(
            "source content must contain 1..={MAX_SOURCE_BYTES} bytes"
        )));
    }
    Ok(())
}

fn validate_source_binding(
    source: &SourceDraft,
    scope: &CognitiveScope,
    expected_content: &str,
) -> Result<(), CognitiveStoreError> {
    if &source.scope != scope {
        return Err(CognitiveStoreError::AccessDenied(
            "source and memory revision must have the same scope".to_string(),
        ));
    }
    if source.content != expected_content.as_bytes() {
        return Err(CognitiveStoreError::Invalid(
            "source content must exactly bind the product mutation input".to_string(),
        ));
    }
    Ok(())
}

fn validate_fact_eligibility(
    revision: &MemoryRevisionDraft,
    facts: &KgFactSetDraft,
) -> Result<(), CognitiveStoreError> {
    if (revision.verification != MemoryVerification::Verified
        || revision.lifecycle != MemoryLifecycleState::Active)
        && (!facts.entities.is_empty() || !facts.relations.is_empty())
    {
        return Err(CognitiveStoreError::Invalid(
            "only verified active memory revisions may carry structured KG facts".to_string(),
        ));
    }
    Ok(())
}

fn validate_expected_predecessor(
    current: &MemoryRevisionRecord,
    expected_revision: u64,
    requested_scope: &CognitiveScope,
) -> Result<(), CognitiveStoreError> {
    if current.id.revision != expected_revision {
        return Err(CognitiveStoreError::Conflict(format!(
            "expected memory revision {expected_revision}, found {}",
            current.id.revision
        )));
    }
    if &current.scope != requested_scope {
        return Err(CognitiveStoreError::AccessDenied(
            "memory scope cannot change across revisions".to_string(),
        ));
    }
    Ok(())
}

fn verify_prepared_trigger(
    expected_memory: &MemoryRevisionRecord,
    expected_source: &SourceRevisionId,
    expected_facts: &CanonicalFactSet,
    actual_memory: &MemoryRevisionRecord,
    actual_source: &SourceRevisionId,
    actual_facts: &CanonicalFactSet,
) -> Result<(), CognitiveStoreError> {
    if expected_memory != actual_memory
        || expected_source != actual_source
        || !canonical_fact_sets_equal(expected_facts, actual_facts)
    {
        return Err(CognitiveStoreError::Conflict(
            "prepared cognitive mutation no longer matches committed source facts".to_string(),
        ));
    }
    Ok(())
}

fn canonical_fact_sets_equal(left: &CanonicalFactSet, right: &CanonicalFactSet) -> bool {
    left.extractor_contract == right.extractor_contract
        && left.digest == right.digest
        && left.entities.len() == right.entities.len()
        && left.relations.len() == right.relations.len()
        && left.entities.iter().zip(&right.entities).all(|(left, right)| {
            left.key == right.key
                && left.canonical_entity_id == right.canonical_entity_id
                && left.entity_type == right.entity_type
                && left.label == right.label
        })
        && left
            .relations
            .iter()
            .zip(&right.relations)
            .all(|(left, right)| {
                left.key == right.key
                    && left.canonical_relation_id == right.canonical_relation_id
                    && left.from_entity_key == right.from_entity_key
                    && left.from_canonical_entity_id == right.from_canonical_entity_id
                    && left.to_entity_key == right.to_entity_key
                    && left.to_canonical_entity_id == right.to_canonical_entity_id
                    && left.relation == right.relation
            })
}

async fn planned_generation_vector_digest_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    owner_agent_id: &str,
    scope: &CognitiveScope,
    trigger_source: &SourceRevisionId,
    trigger_lifecycle: &MemoryLifecycleState,
    source_snapshot_digest: Digest32,
) -> Result<Digest32, CognitiveStoreError> {
    let (scope_kind, workspace_sha256) = scope.database_parts();
    let memory_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM memory_revisions
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let knowledge_fact_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM kg_revision_fact_sets f
         JOIN memory_revisions r
           ON r.memory_id = f.memory_id AND r.revision = f.memory_revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let tombstone_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM memory_revisions
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?
           AND lifecycle = 'tombstoned'",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let source_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM source_ledger s
         WHERE s.owner_agent_id = ? AND s.scope_kind = ? AND s.workspace_sha256 IS ?
           AND EXISTS (SELECT 1 FROM memory_citations c
                       WHERE c.source_id = s.source_id AND c.source_revision = s.source_revision)",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let source_already_cited: i64 = sqlx::query_scalar(
        "SELECT EXISTS(
             SELECT 1 FROM memory_citations c
             JOIN source_ledger s
               ON s.source_id = c.source_id AND s.source_revision = c.source_revision
             WHERE s.owner_agent_id = ? AND s.scope_kind = ?
               AND s.workspace_sha256 IS ? AND s.source_id = ?
               AND s.source_revision = ?
         )",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .bind(trigger_source.source_id.as_str())
    .bind(to_i64(trigger_source.revision, "source revision")?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;

    let memory = nonnegative_frontier(memory_frontier, "memory")?.saturating_add(1);
    let facts = nonnegative_frontier(knowledge_fact_frontier, "knowledge-fact")?
        .saturating_add(1);
    let tombstones = nonnegative_frontier(tombstone_frontier, "tombstone")?
        .saturating_add(u64::from(matches!(
            trigger_lifecycle,
            MemoryLifecycleState::Tombstoned { .. }
        )));
    let sources = nonnegative_frontier(source_frontier, "source")?
        .saturating_add(u64::from(source_already_cited == 0));
    Ok(source_vector_digest(
        owner_agent_id,
        scope,
        [memory, facts, tombstones, sources],
        source_snapshot_digest,
    ))
}

fn source_vector_digest(
    owner_agent_id: &str,
    scope: &CognitiveScope,
    frontiers: [u64; 4],
    source_snapshot_digest: Digest32,
) -> Digest32 {
    let frontier_bytes = frontiers.map(u64::to_be_bytes);
    let projection_key = scope.projection_key();
    let parts = [
        owner_agent_id.as_bytes(),
        projection_key.as_bytes(),
        frontier_bytes[0].as_slice(),
        frontier_bytes[1].as_slice(),
        frontier_bytes[2].as_slice(),
        frontier_bytes[3].as_slice(),
        source_snapshot_digest.as_array().as_slice(),
    ];
    framed_digest32(b"hepta:cognitive:kg-source-vector:v1", &parts)
}

async fn verify_committed_trigger_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    trigger_memory: &MemoryRevisionRecord,
    trigger_facts: &CanonicalFactSet,
) -> Result<(), CognitiveStoreError> {
    let row = sqlx::query(
        "SELECT r.content_sha256, r.verification, r.lifecycle,
                s.fact_set_sha256, s.entity_count, s.relation_count
         FROM memory_heads h
         JOIN memory_revisions r
           ON r.memory_id = h.memory_id AND r.revision = h.revision
         JOIN kg_revision_fact_sets s
           ON s.memory_id = r.memory_id AND s.memory_revision = r.revision
         WHERE h.memory_id = ? AND h.revision = ?",
    )
    .bind(trigger_memory.id.memory_id.as_str())
    .bind(to_i64(trigger_memory.id.revision, "memory revision")?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or_else(|| {
        CognitiveStoreError::Conflict(
            "prepared trigger is not the current committed memory head".to_string(),
        )
    })?;
    let content_sha256: String = row.try_get("content_sha256").map_err(unavailable)?;
    let verification: String = row.try_get("verification").map_err(unavailable)?;
    let lifecycle: String = row.try_get("lifecycle").map_err(unavailable)?;
    let fact_set_sha256: String = row.try_get("fact_set_sha256").map_err(unavailable)?;
    let entity_count: i64 = row.try_get("entity_count").map_err(unavailable)?;
    let relation_count: i64 = row.try_get("relation_count").map_err(unavailable)?;
    if content_sha256 != trigger_memory.content_sha256.as_str()
        || verification != verification_name(trigger_memory.verification)
        || lifecycle != lifecycle_name(&trigger_memory.lifecycle)
        || fact_set_sha256 != trigger_facts.digest.as_str()
        || entity_count != to_i64(usize_to_u64(trigger_facts.entities.len()), "entity count")?
        || relation_count
            != to_i64(
                usize_to_u64(trigger_facts.relations.len()),
                "relation count",
            )?
    {
        return Err(CognitiveStoreError::Conflict(
            "prepared trigger row differs from committed source facts".to_string(),
        ));
    }
    Ok(())
}

fn observe_shape(
    shapes: &mut BTreeMap<String, (String, String)>,
    canonical_entity_id: &str,
    entity_type: &str,
    label: &str,
) -> Result<(), CognitiveStoreError> {
    let shape = (entity_type.to_string(), label.to_string());
    if shapes
        .insert(canonical_entity_id.to_string(), shape.clone())
        .is_some_and(|old| old != shape)
    {
        return Err(CognitiveStoreError::Conflict(format!(
            "current KG supports disagree on canonical entity {canonical_entity_id}"
        )));
    }
    Ok(())
}

fn verification_name(value: MemoryVerification) -> &'static str {
    match value {
        MemoryVerification::Verified => "verified",
        MemoryVerification::Provisional => "provisional",
    }
}

fn lifecycle_name(value: &MemoryLifecycleState) -> &'static str {
    match value {
        MemoryLifecycleState::Active => "active",
        MemoryLifecycleState::Tombstoned { .. } => "tombstoned",
    }
}

fn nonnegative_frontier(value: i64, label: &str) -> Result<u64, CognitiveStoreError> {
    u64::try_from(value)
        .map_err(|_| CognitiveStoreError::Corrupt(format!("negative {label} frontier")))
}

fn framed_digest32(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    let output = hasher.finalize();
    let mut bytes = [0_u8; 32];
    bytes.copy_from_slice(&output);
    Digest32::from_array(bytes)
}

fn to_i64(value: u64, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| CognitiveStoreError::Invalid(format!("{label} exceeds i64")))
}

fn limit_plus_one(value: usize) -> Result<i64, CognitiveStoreError> {
    value
        .checked_add(1)
        .and_then(|value| i64::try_from(value).ok())
        .ok_or_else(|| CognitiveStoreError::Invalid("KG scope limit exceeds i64".to_string()))
}

fn usize_to_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

fn elapsed_nanos(duration: Duration) -> u64 {
    u64::try_from(duration.as_nanos()).unwrap_or(u64::MAX)
}

#[cfg(test)]
fn prepared_projection_crash_rendezvous(stage: &str) {
    use std::fs::OpenOptions;
    use std::io::Write;
    use std::path::PathBuf;
    use std::thread;

    if std::env::var("HEPTA_KG_CRASH_STAGE").ok().as_deref() != Some(stage) {
        return;
    }
    let marker = std::env::var_os("HEPTA_KG_CRASH_MARKER")
        .map(PathBuf::from)
        .expect("KG crash probe marker path");
    let parent = marker.parent().expect("KG crash marker parent");
    std::fs::create_dir_all(parent).expect("create KG crash marker parent");
    let temporary = marker.with_extension(format!("tmp-{}", std::process::id()));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .expect("create KG crash marker");
    file.write_all(stage.as_bytes())
        .expect("write KG crash marker");
    file.sync_all().expect("sync KG crash marker");
    drop(file);
    std::fs::rename(&temporary, &marker).expect("publish KG crash marker");
    if let Ok(directory) = std::fs::File::open(parent) {
        let _ = directory.sync_all();
    }
    loop {
        thread::sleep(Duration::from_secs(60));
    }
}

#[cfg(not(test))]
fn prepared_projection_crash_rendezvous(_stage: &str) {}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use crate::CognitiveAccess;
    use crate::CognitiveScope;
    use crate::CognitiveStore;
    use crate::KgEntityFactDraft;
    use crate::KgFactSetDraft;
    use crate::LedgerSourceKind;
    use crate::MemoryDraft;
    use crate::MemoryLifecycleState;
    use crate::MemoryRevisionDraft;
    use crate::MemoryVerification;
    use crate::SourceDraft;
    use crate::cognitive_test_support;

    #[tokio::test]
    async fn prepared_writer_preserves_atomic_generation_semantics() {
        let temp = TempDir::new().expect("temporary directory");
        let agent_id = cognitive_test_support::agent_id(91);
        let layout = cognitive_test_support::layout(&temp, &agent_id);
        let store = CognitiveStore::open(&layout).await.expect("open store");
        let access = CognitiveAccess::agent_private(agent_id);
        let scope = CognitiveScope::AgentPrivate;
        let content = "prepared knowledge graph fact";
        let source = SourceDraft {
            scope: scope.clone(),
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "prepared-remember".to_string(),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: 100,
        };
        let draft = MemoryDraft {
            stable_key: "prepared-memory".to_string(),
            revision: MemoryRevisionDraft {
                scope: scope.clone(),
                content: content.to_string(),
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 100,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
        };
        let facts = KgFactSetDraft {
            entities: vec![KgEntityFactDraft {
                key: "prepared-entity".to_string(),
                entity_type: "concept".to_string(),
                label: "Prepared Entity".to_string(),
            }],
            relations: Vec::new(),
        };
        let receipt = store
            .remember_with_kg_prepared(&access, &source, &draft, &facts)
            .await
            .expect("prepared write");
        assert_eq!(receipt.write.projection.generation.get(), 1);
        assert_eq!(receipt.metrics.planned_heads, 1);
        assert_eq!(receipt.metrics.planned_nodes, 1);
        assert_eq!(receipt.metrics.planned_edges, 0);
        assert_eq!(receipt.metrics.cas_conflicts, 0);

        let reopened = CognitiveStore::open(&layout).await.expect("reopen store");
        let latest = reopened
            .latest_memory(&access, &receipt.write.memory.id.memory_id)
            .await
            .expect("latest memory");
        assert_eq!(latest, receipt.write.memory);
    }
}

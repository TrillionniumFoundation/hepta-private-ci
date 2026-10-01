//! Indexed scope witness for request-hot exact-ID Lane C reads.
//!
//! The witness is maintained by SQLite triggers in the same physical owner. It
//! replaces repeated whole-scope counts and full head scans, but it never
//! replaces selected-row validation, authorization or final-use reacquisition.

use std::collections::BTreeMap;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::QueryBuilder;
use sqlx::Row;
use sqlx::Sqlite;

use super::super::CognitiveOwnerFrontiers;
use super::super::DurableCognitiveSnapshot;
use super::super::MAX_LANE_C_PAGE_ANCESTRY_REVISIONS;
use super::super::MAX_LANE_C_PAGE_CITATIONS;
use super::super::corrupt;
use super::super::push_stable_id;
use super::DurableCognitiveSelectionSnapshot;
use super::generation;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::DURABLE_SQLITE_MEMORY_KIND;
use crate::cognitive_store::unavailable;

const OWNER_WITNESS_DOMAIN: &[u8] = b"hepta.sqlite.lane-c.scope-witness.v1";

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct ScopeWitness {
    state_revision: u64,
    memory_revision_count: u64,
    source_count: u64,
    citation_count: u64,
    tombstone_count: u64,
    knowledge_fact_count: u64,
    head_count: u64,
}

impl ScopeWitness {
    fn validate(self) -> Result<Self, CognitiveStoreError> {
        if self.head_count > self.memory_revision_count
            || self.tombstone_count > self.memory_revision_count
            || self.knowledge_fact_count > self.memory_revision_count
        {
            return Err(corrupt("invalid Lane C scope witness counts"));
        }
        let minimum_revision = u128::from(self.memory_revision_count)
            + u128::from(self.source_count)
            + u128::from(self.citation_count)
            + u128::from(self.knowledge_fact_count)
            + u128::from(self.head_count);
        if u128::from(self.state_revision) < minimum_revision {
            return Err(corrupt("Lane C scope witness revision regressed"));
        }
        Ok(self)
    }
}

pub(super) async fn load_selection(
    store: &CognitiveStore,
    scope: &CognitiveScope,
    now_unix_seconds: i64,
    record_ids: &[StableId],
) -> Result<DurableCognitiveSelectionSnapshot, CognitiveStoreError> {
    if now_unix_seconds < 0 {
        return Err(CognitiveStoreError::Invalid(
            "negative snapshot time".to_string(),
        ));
    }
    let (scope_kind, workspace) = scope.database_parts();
    let workspace_key = workspace.unwrap_or("");
    let scope_id = StableId::new(format!(
        "cognitive:{}:{}",
        store.owner_agent_id.as_str(),
        Digest32::of_bytes(scope.projection_key().as_bytes())
    ))
    .map_err(corrupt)?;
    let mut transaction = store.pool.begin().await.map_err(unavailable)?;

    let witness_row = sqlx::query(
        "SELECT state_revision, memory_revision_count, source_count,
                citation_count, tombstone_count, knowledge_fact_count, head_count
         FROM lane_c_scope_witness
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_key = ?",
    )
    .bind(store.owner_agent_id.as_str())
    .bind(scope_kind)
    .bind(workspace_key)
    .fetch_optional(&mut *transaction)
    .await
    .map_err(unavailable)?;
    let witness = match witness_row.as_ref() {
        Some(row) => ScopeWitness {
            state_revision: nonnegative(row, "state_revision")?,
            memory_revision_count: nonnegative(row, "memory_revision_count")?,
            source_count: nonnegative(row, "source_count")?,
            citation_count: nonnegative(row, "citation_count")?,
            tombstone_count: nonnegative(row, "tombstone_count")?,
            knowledge_fact_count: nonnegative(row, "knowledge_fact_count")?,
            head_count: nonnegative(row, "head_count")?,
        }
        .validate()?,
        None => ScopeWitness::default(),
    };

    let graph_generation: Option<i64> =
        sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
            .bind(scope.projection_key())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(unavailable)?;
    let graph_generation = graph_generation.unwrap_or(0);
    if graph_generation < 0 {
        return Err(corrupt("negative knowledge graph generation"));
    }
    let knowledge_graph = Generation::new(
        u64::try_from(graph_generation)
            .map_err(corrupt)?
            .checked_add(1)
            .ok_or_else(|| corrupt("graph generation overflow"))?,
    )
    .map_err(corrupt)?;

    // These indexed regime frontiers change exactly when any verified active
    // current head enters or leaves eligibility. Revalidation therefore still
    // notices unselected expiry/start transitions without scanning every head.
    let start_row = sqlx::query(
        "SELECT MAX(valid_from_unix_seconds) AS boundary
         FROM lane_c_head_validity
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_key = ?
           AND verification = 'verified' AND lifecycle = 'active'
           AND valid_from_unix_seconds <= ?",
    )
    .bind(store.owner_agent_id.as_str())
    .bind(scope_kind)
    .bind(workspace_key)
    .bind(now_unix_seconds)
    .fetch_one(&mut *transaction)
    .await
    .map_err(unavailable)?;
    let active_from_frontier: Option<i64> = start_row.try_get("boundary").map_err(unavailable)?;
    let expiry_row = sqlx::query(
        "SELECT MAX(valid_to_unix_seconds) AS boundary
         FROM lane_c_head_validity
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_key = ?
           AND verification = 'verified' AND lifecycle = 'active'
           AND valid_to_unix_seconds IS NOT NULL
           AND valid_to_unix_seconds <= ?",
    )
    .bind(store.owner_agent_id.as_str())
    .bind(scope_kind)
    .bind(workspace_key)
    .bind(now_unix_seconds)
    .fetch_one(&mut *transaction)
    .await
    .map_err(unavailable)?;
    let expiry_frontier: Option<i64> = expiry_row.try_get("boundary").map_err(unavailable)?;

    let mut rows = Vec::new();
    let mut citation_rows = Vec::new();
    if !record_ids.is_empty() {
        let ancestry_limit =
            i64::try_from(MAX_LANE_C_PAGE_ANCESTRY_REVISIONS + 1).map_err(|_| {
                CognitiveStoreError::Invalid("Lane C ancestry limit exceeds i64".to_string())
            })?;
        let mut revision_query = QueryBuilder::<Sqlite>::new(
            "SELECT r.memory_id, r.revision, r.content_sha256, r.verification,
                    r.lifecycle, r.valid_from_unix_seconds, r.valid_to_unix_seconds,
                    r.supersedes_revision, h.revision AS head_revision
             FROM memory_revisions r LEFT JOIN memory_heads h
               ON h.memory_id = r.memory_id
             WHERE r.owner_agent_id = ",
        );
        revision_query
            .push_bind(store.owner_agent_id.as_str())
            .push(" AND r.scope_kind = ")
            .push_bind(scope_kind)
            .push(" AND r.workspace_sha256 IS ")
            .push_bind(workspace)
            .push(" AND r.memory_id IN (");
        {
            let mut separated = revision_query.separated(", ");
            for record_id in record_ids {
                separated.push_bind(record_id.as_str());
            }
        }
        revision_query
            .push(") ORDER BY r.memory_id, r.revision LIMIT ")
            .push_bind(ancestry_limit);
        rows = revision_query
            .build()
            .fetch_all(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if rows.len() > MAX_LANE_C_PAGE_ANCESTRY_REVISIONS {
            return Err(CognitiveStoreError::Unavailable(format!(
                "Lane C selected IDs exceed {MAX_LANE_C_PAGE_ANCESTRY_REVISIONS} ancestry revisions; retry with fewer IDs"
            )));
        }

        let citation_limit = i64::try_from(MAX_LANE_C_PAGE_CITATIONS + 1).map_err(|_| {
            CognitiveStoreError::Invalid("Lane C citation limit exceeds i64".to_string())
        })?;
        let mut citation_query = QueryBuilder::<Sqlite>::new(
            "SELECT c.memory_id, c.memory_revision, s.source_id, s.content_sha256
             FROM memory_citations c
             JOIN memory_revisions r
               ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
             JOIN source_ledger s
               ON s.source_id = c.source_id AND s.source_revision = c.source_revision
             WHERE r.owner_agent_id = ",
        );
        citation_query
            .push_bind(store.owner_agent_id.as_str())
            .push(" AND r.scope_kind = ")
            .push_bind(scope_kind)
            .push(" AND r.workspace_sha256 IS ")
            .push_bind(workspace)
            .push(" AND r.memory_id IN (");
        {
            let mut separated = citation_query.separated(", ");
            for record_id in record_ids {
                separated.push_bind(record_id.as_str());
            }
        }
        citation_query
            .push(") ORDER BY c.memory_id, c.memory_revision, c.ordinal LIMIT ")
            .push_bind(citation_limit);
        citation_rows = citation_query
            .build()
            .fetch_all(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if citation_rows.len() > MAX_LANE_C_PAGE_CITATIONS {
            return Err(CognitiveStoreError::Unavailable(format!(
                "Lane C selected IDs exceed {MAX_LANE_C_PAGE_CITATIONS} citations; retry with fewer IDs"
            )));
        }
    }

    if witness_row.is_none() && (!rows.is_empty() || !citation_rows.is_empty()) {
        return Err(corrupt("Lane C source rows exist without a scope witness"));
    }
    if u64::try_from(rows.len()).unwrap_or(u64::MAX) > witness.memory_revision_count
        || u64::try_from(citation_rows.len()).unwrap_or(u64::MAX) > witness.citation_count
    {
        return Err(corrupt("Lane C selected rows exceed the scope witness"));
    }

    let mut citations = BTreeMap::<(String, i64), Vec<Citation>>::new();
    for row in citation_rows {
        let key = (
            row.try_get("memory_id").map_err(unavailable)?,
            row.try_get("memory_revision").map_err(unavailable)?,
        );
        let source_id: String = row.try_get("source_id").map_err(unavailable)?;
        let source_digest: String = row.try_get("content_sha256").map_err(unavailable)?;
        citations.entry(key).or_default().push(Citation {
            source_id: StableId::new(source_id).map_err(corrupt)?,
            source_digest: source_digest.parse().map_err(corrupt)?,
        });
    }

    let mut visible_heads = Vec::new();
    let mut previous: Option<MemoryRecord> = None;
    let mut previous_head = 0_i64;
    for row in rows {
        let raw_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let revision: i64 = row.try_get("revision").map_err(unavailable)?;
        let head_revision: i64 = row.try_get("head_revision").map_err(unavailable)?;
        if revision <= 0 || head_revision <= 0 || head_revision < revision {
            return Err(corrupt("invalid cognitive head revision"));
        }
        let predecessor: Option<i64> = row.try_get("supersedes_revision").map_err(unavailable)?;
        let record_id = StableId::new(raw_id.clone()).map_err(corrupt)?;
        let prior = previous
            .as_ref()
            .filter(|record| record.record_id == record_id);
        if prior.is_none()
            && previous
                .as_ref()
                .is_some_and(|record| record.revision.get() != previous_head as u64)
        {
            return Err(corrupt("memory head is not the latest committed revision"));
        }
        if (revision == 1 && predecessor.is_some())
            || (revision > 1
                && !prior.is_some_and(|record| {
                    predecessor == Some(revision - 1)
                        && record.revision.get() == (revision - 1) as u64
                }))
        {
            return Err(corrupt("broken cognitive revision ancestry"));
        }
        let lifecycle: String = row.try_get("lifecycle").map_err(unavailable)?;
        let state = match lifecycle.as_str() {
            "active" => RecordState::Live,
            "tombstoned" => RecordState::Tombstone,
            _ => return Err(corrupt("invalid cognitive lifecycle")),
        };
        if state == RecordState::Live
            && prior.is_some_and(|record| record.state == RecordState::Tombstone)
        {
            return Err(corrupt("tombstoned memory resurrection"));
        }
        let content_digest: String = row.try_get("content_sha256").map_err(unavailable)?;
        let mut record_citations = citations
            .remove(&(raw_id, revision))
            .ok_or_else(|| corrupt("missing cognitive citations"))?;
        record_citations.sort();
        let record = MemoryRecord {
            record_id,
            revision: Revision::new(u64::try_from(revision).map_err(corrupt)?).map_err(corrupt)?,
            kind: DURABLE_SQLITE_MEMORY_KIND,
            content_digest: content_digest.parse().map_err(corrupt)?,
            predecessor_digest: prior.map(MemoryRecord::record_digest),
            citations: record_citations,
            state,
        };
        record.validate().map_err(corrupt)?;
        let verification: String = row.try_get("verification").map_err(unavailable)?;
        if !matches!(verification.as_str(), "verified" | "provisional") {
            return Err(corrupt("invalid cognitive verification state"));
        }
        let valid_from: i64 = row
            .try_get("valid_from_unix_seconds")
            .map_err(unavailable)?;
        let valid_to: Option<i64> = row.try_get("valid_to_unix_seconds").map_err(unavailable)?;
        if revision == head_revision
            && (state == RecordState::Tombstone
                || (verification == "verified"
                    && valid_from <= now_unix_seconds
                    && valid_to.is_none_or(|until| now_unix_seconds < until)))
        {
            visible_heads.push(record.clone());
        }
        previous_head = head_revision;
        previous = Some(record);
    }
    if previous
        .as_ref()
        .is_some_and(|record| record.revision.get() != previous_head as u64)
    {
        return Err(corrupt("memory head is not the latest committed revision"));
    }
    if !citations.is_empty() {
        return Err(corrupt("unmatched cognitive citations"));
    }

    let frontiers = CognitiveOwnerFrontiers {
        memory: witness.memory_revision_count,
        source: witness.source_count,
        tombstone: witness.tombstone_count,
        knowledge_facts: witness.knowledge_fact_count,
        knowledge_graph,
    };
    let snapshot = build_snapshot(generation(&frontiers)?, visible_heads).map_err(corrupt)?;
    let owner_state_digest = owner_state_digest(
        &scope_id,
        witness,
        active_from_frontier,
        expiry_frontier,
        knowledge_graph,
    );
    transaction.commit().await.map_err(unavailable)?;

    Ok(DurableCognitiveSelectionSnapshot {
        owner: DurableCognitiveSnapshot {
            scope_id,
            frontiers,
            snapshot,
            observed_at_unix_seconds: now_unix_seconds,
        },
        record_ids: record_ids.to_vec(),
        owner_state_digest,
    })
}

fn nonnegative(row: &sqlx::sqlite::SqliteRow, column: &str) -> Result<u64, CognitiveStoreError> {
    let value: i64 = row.try_get(column).map_err(unavailable)?;
    u64::try_from(value).map_err(|_| corrupt(format!("negative Lane C witness {column}")))
}

fn owner_state_digest(
    scope_id: &StableId,
    witness: ScopeWitness,
    active_from_frontier: Option<i64>,
    expiry_frontier: Option<i64>,
    knowledge_graph: Generation,
) -> Digest32 {
    let mut bytes = OWNER_WITNESS_DOMAIN.to_vec();
    push_stable_id(&mut bytes, scope_id);
    for value in [
        witness.state_revision,
        witness.memory_revision_count,
        witness.source_count,
        witness.citation_count,
        witness.tombstone_count,
        witness.knowledge_fact_count,
        witness.head_count,
        knowledge_graph.get(),
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    push_optional_i64(&mut bytes, active_from_frontier);
    push_optional_i64(&mut bytes, expiry_frontier);
    Digest32::of_bytes(&bytes)
}

fn push_optional_i64(bytes: &mut Vec<u8>, value: Option<i64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

//! Shared owner projection inside an already-opened SQLite transaction.
//!
//! This helper does not acquire or finish a transaction. All metadata guards,
//! capacity checks, ancestry validation and eligibility rules share one cut.

use super::*;
use sqlx::SqliteConnection;

pub(super) async fn project_in_transaction(
    store: &CognitiveStore,
    access: &CognitiveAccess,
    scope: &CognitiveScope,
    now_unix_seconds: i64,
    projection: LaneCProjection,
    connection: &mut SqliteConnection,
) -> Result<(DurableCognitiveSnapshot, LaneCLineageCapture), CognitiveStoreError> {
    store.authorize(access, scope)?;
    if now_unix_seconds < 0 {
        return Err(CognitiveStoreError::Invalid(
            "negative snapshot time".to_string(),
        ));
    }
    let (scope_kind, workspace) = scope.database_parts();
    validate_scope_metadata(
        &mut *connection,
        store.owner_agent_id.as_str(),
        scope_kind,
        workspace,
    )
    .await?;
    let rows = sqlx::query(
        "SELECT r.memory_id, r.revision, r.content_sha256, r.verification,
                r.lifecycle, r.valid_from_unix_seconds, r.valid_to_unix_seconds,
                r.supersedes_revision, h.revision AS head_revision
         FROM memory_revisions r LEFT JOIN memory_heads h ON h.memory_id = r.memory_id
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
         ORDER BY r.memory_id, r.revision LIMIT ?",
    )
    .bind(store.owner_agent_id.as_str())
    .bind(scope_kind)
    .bind(workspace)
    .bind((MAX_REVISIONS + 1) as i64)
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    if rows.len() > MAX_REVISIONS {
        return Err(CognitiveStoreError::Unavailable(
            "Lane C revision capacity exceeded".to_string(),
        ));
    }
    let citation_rows = sqlx::query(
        "SELECT c.memory_id, c.memory_revision, s.source_id, s.content_sha256,
                (s.owner_agent_id = r.owner_agent_id AND s.scope_kind = r.scope_kind
                 AND s.workspace_sha256 IS r.workspace_sha256) AS source_authorized
         FROM memory_citations c
         JOIN memory_revisions r ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
         LEFT JOIN source_ledger s ON s.source_id = c.source_id AND s.source_revision = c.source_revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
         ORDER BY c.memory_id, c.memory_revision, c.ordinal LIMIT ?",
    )
    .bind(store.owner_agent_id.as_str()).bind(scope_kind).bind(workspace)
    .bind((MAX_CITATIONS + 1) as i64)
    .fetch_all(&mut *connection).await.map_err(unavailable)?;
    if citation_rows.len() > MAX_CITATIONS {
        return Err(CognitiveStoreError::Unavailable(
            "Lane C citation capacity exceeded".to_string(),
        ));
    }
    let mut citations = BTreeMap::<(String, i64), Vec<Citation>>::new();
    for row in citation_rows {
        validate_citation_owner(&row)?;
        let key = (
            row.try_get("memory_id").map_err(unavailable)?,
            row.try_get("memory_revision").map_err(unavailable)?,
        );
        let source: String = row.try_get("source_id").map_err(unavailable)?;
        let digest: String = row.try_get("content_sha256").map_err(unavailable)?;
        citations.entry(key).or_default().push(Citation {
            source_id: StableId::new(source).map_err(corrupt)?,
            source_digest: digest.parse().map_err(corrupt)?,
        });
    }
    let source_count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM (SELECT 1 FROM source_ledger WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ? LIMIT 65537)",
    ).bind(store.owner_agent_id.as_str()).bind(scope_kind).bind(workspace)
        .fetch_one(&mut *connection).await.map_err(unavailable)?;
    if source_count > MAX_SOURCES {
        return Err(CognitiveStoreError::Unavailable(
            "Lane C source capacity exceeded".to_string(),
        ));
    }
    let fact_count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM kg_revision_fact_sets f JOIN memory_revisions r
         ON r.memory_id = f.memory_id AND r.revision = f.memory_revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?",
    )
    .bind(store.owner_agent_id.as_str())
    .bind(scope_kind)
    .bind(workspace)
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    let graph_generation: Option<i64> =
        sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
            .bind(scope.projection_key())
            .fetch_optional(&mut *connection)
            .await
            .map_err(unavailable)?;
    let memory_frontier = rows.len() as u64;
    let mut tombstones = 0_u64;
    let mut previous: Option<MemoryRecord> = None;
    let mut heads = Vec::new();
    let mut lineage = Vec::new();
    let mut capture = LaneCLineageCapture::default();
    let mut last_head = 0_i64;
    for row in rows {
        let id: String = row.try_get("memory_id").map_err(unavailable)?;
        let revision: i64 = row.try_get("revision").map_err(unavailable)?;
        let predecessor: Option<i64> = row.try_get("supersedes_revision").map_err(unavailable)?;
        let state: String = row.try_get("lifecycle").map_err(unavailable)?;
        let record_id = StableId::new(id.clone()).map_err(corrupt)?;
        let prior = previous
            .as_ref()
            .filter(|record| record.record_id == record_id);
        if prior.is_none()
            && previous
                .as_ref()
                .is_some_and(|record| record.revision.get() != last_head as u64)
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
        let state = match state.as_str() {
            "active" => RecordState::Live,
            "tombstoned" => {
                tombstones += 1;
                RecordState::Tombstone
            }
            _ => return Err(corrupt("invalid cognitive lifecycle")),
        };
        if state == RecordState::Live
            && prior.is_some_and(|record| record.state == RecordState::Tombstone)
        {
            return Err(corrupt("tombstoned memory resurrection"));
        }
        let digest: String = row.try_get("content_sha256").map_err(unavailable)?;
        let record = MemoryRecord {
            record_id,
            revision: Revision::new(u64::try_from(revision).map_err(corrupt)?).map_err(corrupt)?,
            kind: DURABLE_SQLITE_MEMORY_KIND,
            content_digest: digest.parse().map_err(corrupt)?,
            predecessor_digest: prior.map(MemoryRecord::record_digest),
            citations: citations
                .remove(&(id, revision))
                .ok_or_else(|| corrupt("missing cognitive citations"))?,
            state,
        };
        record.validate().map_err(corrupt)?;
        let head: i64 = row.try_get("head_revision").map_err(unavailable)?;
        if head < revision {
            return Err(corrupt("memory head regressed behind committed revision"));
        }
        last_head = head;
        let verification: String = row.try_get("verification").map_err(unavailable)?;
        let valid_from: i64 = row
            .try_get("valid_from_unix_seconds")
            .map_err(unavailable)?;
        let valid_to: Option<i64> = row.try_get("valid_to_unix_seconds").map_err(unavailable)?;
        let eligible = revision == head
            && (state == RecordState::Tombstone
                || (verification == "verified"
                    && valid_from <= now_unix_seconds
                    && valid_to.is_none_or(|until| now_unix_seconds < until)));
        if projection == LaneCProjection::EligibleLineage {
            lineage.push(record.clone());
            if revision == head {
                capture
                    .physical_head_digests
                    .push(crate::lane_c_lineage::physical_head_digest(
                        &record,
                        &verification,
                        valid_from,
                        valid_to,
                    )?);
                if eligible {
                    capture.records.append(&mut lineage);
                } else {
                    lineage.clear();
                }
            }
        }
        if eligible {
            heads.push(record.clone());
        }
        previous = Some(record);
    }
    if previous
        .as_ref()
        .is_some_and(|record| record.revision.get() != last_head as u64)
    {
        return Err(corrupt("memory head is not the latest committed revision"));
    }
    let frontiers = CognitiveOwnerFrontiers {
        memory: memory_frontier,
        source: u64::try_from(source_count).map_err(corrupt)?,
        tombstone: tombstones,
        knowledge_facts: u64::try_from(fact_count).map_err(corrupt)?,
        knowledge_graph: Generation::new(
            u64::try_from(graph_generation.unwrap_or(0))
                .map_err(corrupt)?
                .checked_add(1)
                .ok_or_else(|| corrupt("graph generation overflow"))?,
        )
        .map_err(corrupt)?,
    };
    let snapshot = build_snapshot(
        Generation::new(memory_frontier + 1).map_err(corrupt)?,
        heads,
    )
    .map_err(corrupt)?;
    let scope_id = StableId::new(format!(
        "cognitive:{}:{}",
        store.owner_agent_id.as_str(),
        Digest32::of_bytes(scope.projection_key().as_bytes())
    ))
    .map_err(corrupt)?;
    Ok((
        DurableCognitiveSnapshot {
            scope_id,
            frontiers,
            snapshot,
            observed_at_unix_seconds: now_unix_seconds,
        },
        capture,
    ))
}

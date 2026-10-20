//! Bounded selected-ID materialization sharing the existing paged owner reader.
//! Full owner identity is independent of selection and binds global visibility.

use super::*;

impl CognitiveStore {
    /// Acquire at most 512 requested owner heads with complete ancestry/citations.
    /// Missing or invisible IDs remain explicit through `read_ids`. The global
    /// cut binds all owner frontiers and heads, including unselected visibility;
    /// historical rows are neither deleted nor materialized outside the selection.
    pub async fn lane_c_snapshot_ids(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        mut record_ids: Vec<StableId>,
    ) -> Result<DurableCognitiveSnapshot, CognitiveStoreError> {
        self.authorize(access, scope)?;
        if now_unix_seconds < 0 || record_ids.len() > MAX_LANE_C_SNAPSHOT_PAGE_HEADS {
            return Err(CognitiveStoreError::Invalid(
                "invalid selected Lane C snapshot bounds".to_string(),
            ));
        }
        record_ids.sort();
        if record_ids.windows(2).any(|ids| ids[0] == ids[1]) {
            return Err(CognitiveStoreError::Invalid(
                "selected Lane C IDs must be unique".to_string(),
            ));
        }
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let (scope_id, frontiers, _, _, owner_digest) = self
            .lane_c_owner_cut(&mut transaction, scope, now_unix_seconds)
            .await?;
        let ids = record_ids
            .iter()
            .map(|id| id.as_str().to_string())
            .collect::<Vec<_>>();
        let records = self
            .lane_c_selected_records(&mut transaction, scope, now_unix_seconds, &ids)
            .await?;
        let generation = frontiers
            .memory
            .checked_add(1)
            .ok_or_else(|| corrupt("snapshot generation overflow"))?;
        let snapshot = build_snapshot(Generation::new(generation).map_err(corrupt)?, records)
            .map_err(corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(DurableCognitiveSnapshot {
            scope_id,
            frontiers,
            snapshot,
            observed_at_unix_seconds: now_unix_seconds,
            selection: Some((record_ids, owner_digest)),
        })
    }

    pub(super) async fn lane_c_owner_cut(
        &self,
        transaction: &mut sqlx::Transaction<'_, Sqlite>,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<(StableId, CognitiveOwnerFrontiers, u64, Digest32, Digest32), CognitiveStoreError>
    {
        let (scope_kind, workspace) = scope.database_parts();
        let scope_id = StableId::new(format!(
            "cognitive:{}:{}",
            self.owner_agent_id.as_str(),
            Digest32::of_bytes(scope.projection_key().as_bytes())
        ))
        .map_err(corrupt)?;
        let memory_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM memory_revisions
             WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let source_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM source_ledger
             WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let citation_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM memory_citations c
             JOIN memory_revisions r ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let tombstone_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM memory_revisions
             WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?
               AND lifecycle = 'tombstoned'",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let fact_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM kg_revision_fact_sets f JOIN memory_revisions r
             ON r.memory_id = f.memory_id AND r.revision = f.memory_revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let graph_generation: Option<i64> =
            sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
                .bind(scope.projection_key())
                .fetch_optional(&mut **transaction)
                .await
                .map_err(unavailable)?;
        let frontiers = CognitiveOwnerFrontiers {
            memory: u64::try_from(memory_count).map_err(corrupt)?,
            source: u64::try_from(source_count).map_err(corrupt)?,
            tombstone: u64::try_from(tombstone_count).map_err(corrupt)?,
            knowledge_facts: u64::try_from(fact_count).map_err(corrupt)?,
            knowledge_graph: Generation::new(
                u64::try_from(graph_generation.unwrap_or(0))
                    .map_err(corrupt)?
                    .checked_add(1)
                    .ok_or_else(|| corrupt("graph generation overflow"))?,
            )
            .map_err(corrupt)?,
        };

        // Bind every mutable head pointer without materializing record payloads.
        // Revisions, citations, sources and fact sets are immutable; their
        // append-only counts above change whenever those ledgers advance.
        let mut head_set_digest = Digest32::of_bytes(b"hepta.sqlite.lane-c.head-set.v1");
        let mut owner_head_digest = Digest32::of_bytes(b"hepta.sqlite.lane-c.owner-heads.v1");
        let mut digest_after = String::new();
        loop {
            let head_rows = sqlx::query(
                "SELECT h.memory_id, h.revision, r.content_sha256, r.lifecycle, r.verification,
                        r.valid_from_unix_seconds, r.valid_to_unix_seconds
                 FROM memory_heads h JOIN memory_revisions r
                   ON r.memory_id = h.memory_id AND r.revision = h.revision
                 WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
                   AND h.memory_id > ?
                 ORDER BY h.memory_id LIMIT ?",
            )
            .bind(self.owner_agent_id.as_str())
            .bind(scope_kind)
            .bind(workspace)
            .bind(&digest_after)
            .bind(LANE_C_HEAD_DIGEST_BATCH)
            .fetch_all(&mut **transaction)
            .await
            .map_err(unavailable)?;
            if head_rows.is_empty() {
                break;
            }
            for row in &head_rows {
                let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
                let revision: i64 = row.try_get("revision").map_err(unavailable)?;
                if revision <= 0 {
                    return Err(corrupt("non-positive memory head revision"));
                }
                let mut step = b"hepta.sqlite.lane-c.head-step.v1".to_vec();
                step.extend_from_slice(head_set_digest.as_array());
                step.extend_from_slice(&(memory_id.len() as u64).to_be_bytes());
                step.extend_from_slice(memory_id.as_bytes());
                step.extend_from_slice(&revision.to_be_bytes());
                head_set_digest = Digest32::of_bytes(&step);
                let lifecycle: String = row.try_get("lifecycle").map_err(unavailable)?;
                let verification: String = row.try_get("verification").map_err(unavailable)?;
                let valid_from: i64 = row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?;
                let valid_to: Option<i64> =
                    row.try_get("valid_to_unix_seconds").map_err(unavailable)?;
                let visible = lifecycle == "tombstoned"
                    || (verification == "verified"
                        && valid_from <= now_unix_seconds
                        && valid_to.is_none_or(|until| now_unix_seconds < until));
                let content: String = row.try_get("content_sha256").map_err(unavailable)?;
                let content: Digest32 = content.parse().map_err(corrupt)?;
                let mut observed = b"hepta.sqlite.lane-c.owner-head-step.v1".to_vec();
                observed.extend_from_slice(owner_head_digest.as_array());
                push_stable_id(
                    &mut observed,
                    &StableId::new(memory_id.clone()).map_err(corrupt)?,
                );
                observed.extend_from_slice(&revision.to_be_bytes());
                observed.extend_from_slice(content.as_array());
                observed.push(u8::from(visible));
                owner_head_digest = Digest32::of_bytes(&observed);
                digest_after = memory_id;
            }
            if head_rows.len() < usize::try_from(LANE_C_HEAD_DIGEST_BATCH).unwrap_or(usize::MAX) {
                break;
            }
        }

        let citation_count = u64::try_from(citation_count).map_err(corrupt)?;
        let mut owner = b"hepta.sqlite.lane-c.selected-owner-cut.v1".to_vec();
        push_stable_id(&mut owner, &scope_id);
        push_frontiers(&mut owner, &frontiers);
        owner.extend_from_slice(&citation_count.to_be_bytes());
        owner.extend_from_slice(owner_head_digest.as_array());
        Ok((
            scope_id,
            frontiers,
            citation_count,
            head_set_digest,
            Digest32::of_bytes(&owner),
        ))
    }

    pub(super) async fn lane_c_selected_records(
        &self,
        transaction: &mut sqlx::Transaction<'_, Sqlite>,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        head_ids: &[String],
    ) -> Result<Vec<MemoryRecord>, CognitiveStoreError> {
        let (scope_kind, workspace) = scope.database_parts();
        let mut records = Vec::new();
        if !head_ids.is_empty() {
            let ancestry_limit =
                i64::try_from(MAX_LANE_C_PAGE_ANCESTRY_REVISIONS + 1).map_err(|_| {
                    CognitiveStoreError::Invalid("Lane C ancestry limit exceeds i64".to_string())
                })?;
            let mut revision_query = QueryBuilder::<Sqlite>::new(
                "SELECT r.memory_id, r.revision, r.content_sha256, r.verification,
                        r.lifecycle, r.valid_from_unix_seconds, r.valid_to_unix_seconds,
                        r.supersedes_revision, h.revision AS head_revision
                 FROM memory_revisions r LEFT JOIN memory_heads h ON h.memory_id = r.memory_id
                 WHERE r.owner_agent_id = ",
            );
            revision_query
                .push_bind(self.owner_agent_id.as_str())
                .push(" AND r.scope_kind = ")
                .push_bind(scope_kind)
                .push(" AND r.workspace_sha256 IS ")
                .push_bind(workspace)
                .push(" AND r.memory_id IN (");
            {
                let mut separated = revision_query.separated(", ");
                for memory_id in head_ids {
                    separated.push_bind(memory_id);
                }
            }
            revision_query
                .push(") ORDER BY r.memory_id, r.revision LIMIT ")
                .push_bind(ancestry_limit);
            let rows = revision_query
                .build()
                .fetch_all(&mut **transaction)
                .await
                .map_err(unavailable)?;
            if rows.len() > MAX_LANE_C_PAGE_ANCESTRY_REVISIONS {
                return Err(CognitiveStoreError::Unavailable(format!(
                    "Lane C selected page exceeds {MAX_LANE_C_PAGE_ANCESTRY_REVISIONS} ancestry revisions; retry with fewer heads"
                )));
            }

            let citation_limit = i64::try_from(MAX_LANE_C_PAGE_CITATIONS + 1).map_err(|_| {
                CognitiveStoreError::Invalid("Lane C citation limit exceeds i64".to_string())
            })?;
            let mut citation_query = QueryBuilder::<Sqlite>::new(
                "SELECT c.memory_id, c.memory_revision, s.source_id, s.content_sha256
                 FROM memory_citations c
                 JOIN memory_revisions r ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
                 JOIN source_ledger s ON s.source_id = c.source_id AND s.source_revision = c.source_revision
                 WHERE r.owner_agent_id = ",
            );
            citation_query
                .push_bind(self.owner_agent_id.as_str())
                .push(" AND r.scope_kind = ")
                .push_bind(scope_kind)
                .push(" AND r.workspace_sha256 IS ")
                .push_bind(workspace)
                .push(" AND r.memory_id IN (");
            {
                let mut separated = citation_query.separated(", ");
                for memory_id in head_ids {
                    separated.push_bind(memory_id);
                }
            }
            citation_query
                .push(") ORDER BY c.memory_id, c.memory_revision, c.ordinal LIMIT ")
                .push_bind(citation_limit);
            let citation_rows = citation_query
                .build()
                .fetch_all(&mut **transaction)
                .await
                .map_err(unavailable)?;
            if citation_rows.len() > MAX_LANE_C_PAGE_CITATIONS {
                return Err(CognitiveStoreError::Unavailable(format!(
                    "Lane C selected page exceeds {MAX_LANE_C_PAGE_CITATIONS} citations; retry with fewer heads"
                )));
            }
            let mut citations = BTreeMap::<(String, i64), Vec<Citation>>::new();
            for row in citation_rows {
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

            let mut previous: Option<MemoryRecord> = None;
            let mut last_head = 0_i64;
            for row in rows {
                let id: String = row.try_get("memory_id").map_err(unavailable)?;
                let revision: i64 = row.try_get("revision").map_err(unavailable)?;
                let predecessor: Option<i64> =
                    row.try_get("supersedes_revision").map_err(unavailable)?;
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
                    "tombstoned" => RecordState::Tombstone,
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
                    revision: Revision::new(u64::try_from(revision).map_err(corrupt)?)
                        .map_err(corrupt)?,
                    kind: MemoryKind::Fact,
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
                let valid_to: Option<i64> =
                    row.try_get("valid_to_unix_seconds").map_err(unavailable)?;
                if revision == head
                    && (state == RecordState::Tombstone
                        || (verification == "verified"
                            && valid_from <= now_unix_seconds
                            && valid_to.is_none_or(|until| now_unix_seconds < until)))
                {
                    records.push(record.clone());
                }
                previous = Some(record);
            }
            if previous
                .as_ref()
                .is_some_and(|record| record.revision.get() != last_head as u64)
            {
                return Err(corrupt("memory head is not the latest committed revision"));
            }
        }

        Ok(records)
    }
}

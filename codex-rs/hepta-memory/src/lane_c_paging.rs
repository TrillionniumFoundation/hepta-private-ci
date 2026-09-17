//! Bounded lineage paging over the existing cognitive SQLite owner.
//!
//! Pages contain whole memory histories: a single memory ID is never split
//! across page boundaries. Each page is read in one SQLite snapshot and bound
//! to a scope-local monotonic frontier digest. A second frontier observation
//! after the read rejects an owner mutation that raced page acquisition, while
//! the caller carries the digest into the next page so different cuts cannot be
//! silently combined.
//!
//! This is a traversal primitive, not physical retention or erasure. Immutable
//! authoritative rows remain in the owner until an archive/pruning format can
//! prove predecessor and tombstone-frontier continuity.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Generation;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;

use crate::CognitiveAccess;
use crate::CognitiveOwnerFrontiers;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionRecord;
use crate::StableMemoryId;
use crate::cognitive_memory_store::decode_revision;
use crate::cognitive_store::unavailable;
use crate::framing::frame_part;

pub const MAX_LANE_C_LINEAGE_PAGE_MEMORY_IDS: u16 = 256;
pub const MAX_LANE_C_LINEAGE_PAGE_REVISIONS: usize = 4_096;
const LINEAGE_CUT_DOMAIN: &[u8] = b"hepta:cognitive:lane-c-lineage-cut:v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCognitiveLineagePage {
    pub frontiers: CognitiveOwnerFrontiers,
    /// Integrity binding for this exact scoped frontier vector. This is not a
    /// signature or proof that the caller retained the newest cut.
    pub cut_digest: Sha256Digest,
    pub records: Vec<MemoryRevisionRecord>,
    /// Present only when another complete memory history remains after this
    /// page. Supply this value as `after_memory_id` for the next page.
    pub next_after_memory_id: Option<StableMemoryId>,
}

impl CognitiveStore {
    /// Read complete immutable histories from one exact scoped owner cut.
    ///
    /// `expected_cut_digest` is optional for the first page and mandatory for a
    /// caller that wants a coherent multi-page traversal. A later page fails
    /// closed if the scope frontiers changed between pages. The digest binds
    /// owner, scope, memory/source/tombstone/fact frontiers and KG generation;
    /// it is an integrity cursor, not host authentication or recovery authority.
    pub async fn lane_c_lineage_page(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected_cut_digest: Option<&Sha256Digest>,
        after_memory_id: Option<&StableMemoryId>,
        maximum_memory_ids: u16,
    ) -> Result<DurableCognitiveLineagePage, CognitiveStoreError> {
        self.authorize(access, scope)?;
        if maximum_memory_ids == 0 || maximum_memory_ids > MAX_LANE_C_LINEAGE_PAGE_MEMORY_IDS {
            return Err(CognitiveStoreError::Invalid(format!(
                "lineage page memory IDs must be in 1..={MAX_LANE_C_LINEAGE_PAGE_MEMORY_IDS}"
            )));
        }

        let (scope_kind, workspace) = scope.database_parts();
        let cursor = after_memory_id.map(StableMemoryId::as_str);
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let frontiers = read_frontiers(
            &mut *transaction,
            self.owner_agent_id.as_str(),
            scope,
            scope_kind,
            workspace,
        )
        .await?;
        let cut_digest = lineage_cut_digest(self.owner_agent_id.as_str(), scope, &frontiers);
        if expected_cut_digest.is_some_and(|expected| expected != &cut_digest) {
            return Err(CognitiveStoreError::Conflict(
                "cognitive lineage cursor belongs to a different owner cut".to_string(),
            ));
        }

        let id_limit = i64::from(maximum_memory_ids) + 1;
        let id_rows = sqlx::query(
            "SELECT DISTINCT memory_id FROM memory_revisions
             WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?
               AND (? IS NULL OR memory_id > ?)
             ORDER BY memory_id LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .bind(cursor)
        .bind(cursor)
        .bind(id_limit)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;

        let requested = usize::from(maximum_memory_ids);
        let has_more = id_rows.len() > requested;
        let page_ids = id_rows
            .into_iter()
            .take(requested)
            .map(|row| row.try_get::<String, _>("memory_id").map_err(unavailable))
            .collect::<Result<Vec<_>, _>>()?;

        let mut records = Vec::new();
        let next_after_memory_id = if let Some(last_id) = page_ids.last() {
            let revision_rows = sqlx::query(
                "SELECT r.* FROM memory_revisions r
                 WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
                   AND (? IS NULL OR r.memory_id > ?) AND r.memory_id <= ?
                 ORDER BY r.memory_id, r.revision LIMIT ?",
            )
            .bind(self.owner_agent_id.as_str())
            .bind(scope_kind)
            .bind(workspace)
            .bind(cursor)
            .bind(cursor)
            .bind(last_id)
            .bind(i64::try_from(MAX_LANE_C_LINEAGE_PAGE_REVISIONS + 1).map_err(|error| {
                CognitiveStoreError::Invalid(error.to_string())
            })?)
            .fetch_all(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if revision_rows.len() > MAX_LANE_C_LINEAGE_PAGE_REVISIONS {
                return Err(CognitiveStoreError::Unavailable(format!(
                    "selected lineage page exceeds {MAX_LANE_C_LINEAGE_PAGE_REVISIONS} revisions; reduce maximum_memory_ids"
                )));
            }
            for row in revision_rows {
                records.push(decode_revision(&mut *transaction, row, scope.clone()).await?);
            }
            validate_complete_histories(&records)?;
            if has_more {
                Some(
                    StableMemoryId::parse(last_id.clone())
                        .map_err(CognitiveStoreError::Corrupt)?,
                )
            } else {
                None
            }
        } else {
            None
        };
        transaction.commit().await.map_err(unavailable)?;

        // Observe the same scoped monotonic frontiers after releasing the read
        // snapshot. Any committed source/memory/fact/tombstone/KG mutation in
        // this scope changes at least one component under the single-writer
        // owner invariants and therefore invalidates the acquired page.
        let mut after_transaction = self.pool.begin().await.map_err(unavailable)?;
        let after_frontiers = read_frontiers(
            &mut *after_transaction,
            self.owner_agent_id.as_str(),
            scope,
            scope_kind,
            workspace,
        )
        .await?;
        after_transaction.commit().await.map_err(unavailable)?;
        if after_frontiers != frontiers {
            return Err(CognitiveStoreError::Conflict(
                "cognitive owner changed while lineage page was acquired".to_string(),
            ));
        }

        Ok(DurableCognitiveLineagePage {
            frontiers,
            cut_digest,
            records,
            next_after_memory_id,
        })
    }
}

fn lineage_cut_digest(
    owner: &str,
    scope: &CognitiveScope,
    frontiers: &CognitiveOwnerFrontiers,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, LINEAGE_CUT_DOMAIN);
    frame_part(&mut hasher, owner.as_bytes());
    frame_part(&mut hasher, scope.projection_key().as_bytes());
    for value in [
        frontiers.memory,
        frontiers.source,
        frontiers.tombstone,
        frontiers.knowledge_facts,
        frontiers.knowledge_graph.get(),
    ] {
        frame_part(&mut hasher, &value.to_be_bytes());
    }
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn validate_complete_histories(records: &[MemoryRevisionRecord]) -> Result<(), CognitiveStoreError> {
    let mut current_id: Option<&StableMemoryId> = None;
    let mut previous_revision = 0_u64;
    let mut tombstoned = false;
    for record in records {
        if current_id != Some(&record.id.memory_id) {
            current_id = Some(&record.id.memory_id);
            previous_revision = 0;
            tombstoned = false;
        }
        let expected = previous_revision.checked_add(1).ok_or_else(|| {
            CognitiveStoreError::Corrupt("lineage revision overflow".to_string())
        })?;
        if record.id.revision != expected
            || record.supersedes_revision != (expected > 1).then_some(expected - 1)
        {
            return Err(CognitiveStoreError::Corrupt(
                "lineage page contains broken or partial ancestry".to_string(),
            ));
        }
        if tombstoned && record.lifecycle == MemoryLifecycleState::Active {
            return Err(CognitiveStoreError::Corrupt(
                "lineage page contains tombstone resurrection".to_string(),
            ));
        }
        tombstoned = matches!(
            &record.lifecycle,
            MemoryLifecycleState::Tombstoned { .. }
        );
        previous_revision = record.id.revision;
    }
    Ok(())
}

async fn read_frontiers(
    connection: &mut sqlx::SqliteConnection,
    owner: &str,
    scope: &CognitiveScope,
    scope_kind: &str,
    workspace: Option<&str>,
) -> Result<CognitiveOwnerFrontiers, CognitiveStoreError> {
    let memory: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM memory_revisions
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
    )
    .bind(owner)
    .bind(scope_kind)
    .bind(workspace)
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    let source: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM source_ledger
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
    )
    .bind(owner)
    .bind(scope_kind)
    .bind(workspace)
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    let tombstone: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM memory_revisions
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?
           AND lifecycle = 'tombstoned'",
    )
    .bind(owner)
    .bind(scope_kind)
    .bind(workspace)
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    let knowledge_facts: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM kg_revision_fact_sets f
         JOIN memory_revisions r
           ON r.memory_id = f.memory_id AND r.revision = f.memory_revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?",
    )
    .bind(owner)
    .bind(scope_kind)
    .bind(workspace)
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    let graph_generation: Option<i64> = sqlx::query_scalar(
        "SELECT generation FROM kg_projection WHERE projection_scope = ?",
    )
    .bind(scope.projection_key())
    .fetch_optional(&mut *connection)
    .await
    .map_err(unavailable)?;

    let nonnegative = |name: &str, value: i64| {
        u64::try_from(value).map_err(|_| {
            CognitiveStoreError::Corrupt(format!("negative {name} frontier"))
        })
    };
    let graph = nonnegative("knowledge graph", graph_generation.unwrap_or(0))?
        .checked_add(1)
        .ok_or_else(|| CognitiveStoreError::Corrupt("graph generation overflow".to_string()))?;
    Ok(CognitiveOwnerFrontiers {
        memory: nonnegative("memory", memory)?,
        source: nonnegative("source", source)?,
        tombstone: nonnegative("tombstone", tombstone)?,
        knowledge_facts: nonnegative("knowledge fact", knowledge_facts)?,
        knowledge_graph: Generation::new(graph)
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
    })
}

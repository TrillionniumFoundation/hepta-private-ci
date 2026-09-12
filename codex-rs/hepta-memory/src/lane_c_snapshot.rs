//! Read-only Lane C projection of the existing canonical SQLite owner.
//!
//! No database, schema or writer is added. One SQLite read transaction binds
//! revisions, citations, heads and source/projection frontiers. Only verified,
//! currently valid heads are exposed as facts; tombstones remain visible.

use std::collections::BTreeMap;

use codex_hepta_cognitive_read::AuthoritativeSnapshotV1;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_cognitive_read::ReadResultV2;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_read::read_v2;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;

const MAX_REVISIONS: usize = 16_384;
const MAX_CITATIONS: usize = 65_536;
const MAX_SOURCES: i64 = 65_536;

/// Owner-observed frontiers in one exact scope. Counters count immutable rows;
/// graph generation is the existing SQLite generation plus one (empty = one).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveOwnerFrontiers {
    pub memory: u64,
    pub source: u64,
    pub tombstone: u64,
    pub knowledge_facts: u64,
    pub knowledge_graph: Generation,
}

/// Immutable, digest-only view acquired from the existing physical store.
/// This value has no writer, SQL handle or effect authority. It is a historical
/// cut, not an assertion that revocation remained unchanged after acquisition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCognitiveSnapshot {
    scope_id: StableId,
    frontiers: CognitiveOwnerFrontiers,
    snapshot: CognitiveSnapshot,
    observed_at_unix_seconds: i64,
}

impl DurableCognitiveSnapshot {
    pub fn scope_id(&self) -> &StableId {
        &self.scope_id
    }

    pub fn frontiers(&self) -> &CognitiveOwnerFrontiers {
        &self.frontiers
    }

    pub fn snapshot(&self) -> &CognitiveSnapshot {
        &self.snapshot
    }

    /// Persist this exact digest in an independent host witness to detect an
    /// older valid database after reopen. The digest does not authenticate its
    /// own provenance or establish that the host retained the latest witness.
    pub fn cut_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.sqlite.lane-c.cut.v1".to_vec();
        bytes.extend_from_slice(&(self.scope_id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(self.scope_id.as_str().as_bytes());
        for value in [
            self.frontiers.memory,
            self.frontiers.source,
            self.frontiers.tombstone,
            self.frontiers.knowledge_facts,
            self.frontiers.knowledge_graph.get(),
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(self.snapshot.snapshot_digest.as_array());
        Digest32::of_bytes(&bytes)
    }

    /// Consume the new read module against an owner-acquired SQLite cut.
    pub fn read(&self, request: ReadRequestV2) -> Result<ReadResultV2, SnapshotProviderError> {
        read_v2(&self.snapshot, request).map_err(SnapshotProviderError::Read)
    }

    /// Attach a host-frozen external context without inventing other owners'
    /// generations. Every cognitive-owned component must match this exact cut.
    pub fn bind_context(
        &self,
        vector: LaneCGenerationVectorV1,
        acquired_at_unix_ms: u64,
        lease_expires_unix_ms: u64,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError> {
        if vector.scope_id != self.scope_id {
            return Err(SnapshotProviderError::ScopeMismatch);
        }
        if vector.memory_ledger_frontier != self.frontiers.memory
            || vector.source_ledger_frontier != self.frontiers.source
            || vector.tombstone_frontier != self.frontiers.tombstone
            || vector.knowledge_fact_frontier != self.frontiers.knowledge_facts
            || vector.knowledge_graph_generation != self.frontiers.knowledge_graph
        {
            return Err(SnapshotProviderError::GenerationGone);
        }
        if lease_expires_unix_ms
            .checked_sub(acquired_at_unix_ms)
            .is_none_or(|duration| duration == 0 || duration > 300_000)
        {
            return Err(SnapshotProviderError::InvalidLeaseWindow);
        }
        if acquired_at_unix_ms / 1000
            != u64::try_from(self.observed_at_unix_seconds)
                .map_err(|_| SnapshotProviderError::InvalidLeaseWindow)?
        {
            return Err(SnapshotProviderError::InvalidLeaseWindow);
        }
        AuthoritativeSnapshotV1::new(
            self.scope_id.clone(),
            CognitiveSnapshotKeyV1::new(vector).map_err(SnapshotProviderError::Contract)?,
            self.snapshot.clone(),
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        )
    }
}

impl CognitiveStore {
    /// Acquire one scope from the existing owner database. The host supplies
    /// authenticated access and its clock; source content never leaves here.
    /// There is no fallback to the in-memory V2 writer or a second database.
    pub async fn lane_c_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, CognitiveStoreError> {
        self.authorize(access, scope)?;
        if now_unix_seconds < 0 {
            return Err(CognitiveStoreError::Invalid(
                "negative snapshot time".to_string(),
            ));
        }
        let (scope_kind, workspace) = scope.database_parts();
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let rows = sqlx::query(
            "SELECT r.memory_id, r.revision, r.content_sha256, r.verification,
                    r.lifecycle, r.valid_from_unix_seconds, r.valid_to_unix_seconds,
                    r.supersedes_revision, h.revision AS head_revision
             FROM memory_revisions r LEFT JOIN memory_heads h ON h.memory_id = r.memory_id
             WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
             ORDER BY r.memory_id, r.revision LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .bind((MAX_REVISIONS + 1) as i64)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if rows.len() > MAX_REVISIONS {
            return Err(CognitiveStoreError::Unavailable(
                "Lane C revision capacity exceeded".to_string(),
            ));
        }
        let citation_rows = sqlx::query(
            "SELECT c.memory_id, c.memory_revision, s.source_id, s.content_sha256
             FROM memory_citations c
             JOIN memory_revisions r ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
             JOIN source_ledger s ON s.source_id = c.source_id AND s.source_revision = c.source_revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
             ORDER BY c.memory_id, c.memory_revision, c.ordinal LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str()).bind(scope_kind).bind(workspace)
        .bind((MAX_CITATIONS + 1) as i64)
        .fetch_all(&mut *transaction).await.map_err(unavailable)?;
        if citation_rows.len() > MAX_CITATIONS {
            return Err(CognitiveStoreError::Unavailable(
                "Lane C citation capacity exceeded".to_string(),
            ));
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
        let source_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM (SELECT 1 FROM source_ledger WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ? LIMIT 65537)",
        ).bind(self.owner_agent_id.as_str()).bind(scope_kind).bind(workspace)
            .fetch_one(&mut *transaction).await.map_err(unavailable)?;
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
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let graph_generation: Option<i64> =
            sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
                .bind(scope.projection_key())
                .fetch_optional(&mut *transaction)
                .await
                .map_err(unavailable)?;
        let memory_frontier = rows.len() as u64;
        let mut tombstones = 0_u64;
        let mut previous: Option<MemoryRecord> = None;
        let mut heads = Vec::new();
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
        transaction.commit().await.map_err(unavailable)?;
        let scope_id = StableId::new(format!(
            "cognitive:{}:{}",
            self.owner_agent_id.as_str(),
            Digest32::of_bytes(scope.projection_key().as_bytes())
        ))
        .map_err(corrupt)?;
        Ok(DurableCognitiveSnapshot {
            scope_id,
            frontiers,
            snapshot,
            observed_at_unix_seconds: now_unix_seconds,
        })
    }

    /// Compare an independently retained exact witness against this already
    /// opened owner. This never opens/migrates a file or bypasses the separate
    /// full-database descriptor-safe recovery gate.
    pub async fn revalidate_lane_c_cut(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected_digest: Digest32,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, CognitiveStoreError> {
        let current = self
            .lane_c_snapshot(access, scope, now_unix_seconds)
            .await?;
        if current.cut_digest() != expected_digest {
            return Err(CognitiveStoreError::Conflict(
                "cognitive snapshot changed or rolled back".to_string(),
            ));
        }
        Ok(current)
    }

    /// Reacquire the owner cut before use. An old cut never suppresses a newer
    /// correction/tombstone. An independently retained exact cut can also detect
    /// rollback after an ordinary database reopen; this does not replace the
    /// descriptor-safe full-database recovery admission contract.
    pub async fn revalidate_lane_c_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected: &DurableCognitiveSnapshot,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, CognitiveStoreError> {
        if now_unix_seconds < expected.observed_at_unix_seconds {
            return Err(CognitiveStoreError::Invalid(
                "snapshot clock regressed".to_string(),
            ));
        }
        let current = self
            .lane_c_snapshot(access, scope, now_unix_seconds)
            .await?;
        if current.scope_id != expected.scope_id
            || current.frontiers != expected.frontiers
            || current.snapshot != expected.snapshot
        {
            return Err(CognitiveStoreError::Conflict(
                "cognitive snapshot changed or rolled back".to_string(),
            ));
        }
        Ok(current)
    }
}

fn corrupt(error: impl std::fmt::Display) -> CognitiveStoreError {
    CognitiveStoreError::Corrupt(format!("Lane C snapshot: {error}"))
}

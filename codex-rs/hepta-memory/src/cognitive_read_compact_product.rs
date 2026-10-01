//! Existing SQLite owner composition for `cognitive.read -> compact.engine`.
//!
//! The caller supplies only exact record identities and retention-policy
//! metadata. The owner resolves complete immutable ancestry, obtains an exact
//! all-or-error cognitive read, builds the deterministic compaction candidate,
//! and reacquires the selected owner cut before publication.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::CognitiveReadCompactionCandidateV1;
use codex_hepta_compact_engine::CognitiveReadCompactionRetentionV1;
use codex_hepta_compact_engine::CompactionInputRecordV2;
use codex_hepta_compact_engine::CompactionPolicyV2;
use codex_hepta_compact_engine::MAX_COGNITIVE_READ_COMPACTION_IDS;
use codex_hepta_compact_engine::build_qualified_candidate;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::QueryBuilder;
use sqlx::Row;
use sqlx::Sqlite;

use super::checked_ids;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::DURABLE_SQLITE_MEMORY_KIND;
use crate::MAX_LANE_C_PAGE_ANCESTRY_REVISIONS;
use crate::MAX_LANE_C_PAGE_CITATIONS;
use crate::cognitive_store::unavailable;

pub const COGNITIVE_READ_COMPACTION_PURPOSE_ID: &str = "purpose:cognitive-compaction";

impl CognitiveStore {
    /// Build one authority-free compaction candidate through the normal durable
    /// owner and exact cognitive read path.
    ///
    /// This function never persists a checkpoint and never grants selection or
    /// mutation authority. Publication/persistence remains with the existing
    /// compact checkpoint owner after independent qualification.
    #[allow(clippy::too_many_arguments)]
    pub async fn build_cognitive_read_compaction_candidate(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        generation_vector: LaneCGenerationVectorV1,
        candidate_generation: Generation,
        predecessor_checkpoint_digest: Option<Digest32>,
        policy: &CompactionPolicyV2,
        retentions: Vec<CognitiveReadCompactionRetentionV1>,
    ) -> Result<CognitiveReadCompactionCandidateV1, CognitiveStoreError> {
        self.authorize(access, scope)?;
        if retentions.is_empty() || retentions.len() > MAX_COGNITIVE_READ_COMPACTION_IDS {
            return Err(CognitiveStoreError::Invalid(format!(
                "cognitive compaction requires 1..={MAX_COGNITIVE_READ_COMPACTION_IDS} exact IDs"
            )));
        }
        let expected_purpose = StableId::new(COGNITIVE_READ_COMPACTION_PURPOSE_ID)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        if generation_vector.purpose_id != expected_purpose {
            return Err(CognitiveStoreError::Invalid(
                "cognitive compaction generation vector has the wrong purpose".to_string(),
            ));
        }

        let mut retention_by_id = BTreeMap::new();
        for retention in retentions {
            retention
                .validate()
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
            let record_id = retention.record_id.clone();
            if retention_by_id
                .insert(record_id.clone(), retention)
                .is_some()
            {
                return Err(CognitiveStoreError::Invalid(format!(
                    "duplicate cognitive compaction ID {record_id}"
                )));
            }
        }
        let record_ids = retention_by_id.keys().cloned().collect::<Vec<_>>();
        let record_ids = checked_ids(&record_ids)?;
        let selected = self
            .lane_c_snapshot_ids(access, scope, now_unix_seconds, &record_ids)
            .await?;

        let read = selected
            .owner_snapshot()
            .read_ids(ReadIdsRequestV1 {
                snapshot_digest: selected.snapshot().snapshot_digest,
                record_ids: record_ids.clone(),
                fields: vec![
                    ReadFieldV1::ContentDigest,
                    ReadFieldV1::PredecessorDigest,
                    ReadFieldV1::Citations,
                ],
                maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
            })
            .map_err(|error| {
                CognitiveStoreError::Invalid(format!(
                    "cognitive compaction exact read failed: {error}"
                ))
            })?;
        if !read.missing_ids().is_empty() || read.records().len() != record_ids.len() {
            return Err(CognitiveStoreError::Conflict(
                "cognitive compaction source set is missing or unavailable".to_string(),
            ));
        }

        let lineage = load_exact_lineage(self, scope, &record_ids).await?;
        verify_read_matches_lineage(read.records(), &lineage, &record_ids)?;
        let inputs = lineage
            .into_iter()
            .map(|record| {
                let retention = retention_by_id.get(&record.record_id).ok_or_else(|| {
                    CognitiveStoreError::Corrupt(
                        "owner lineage escaped the cognitive compaction request".to_string(),
                    )
                })?;
                Ok(CompactionInputRecordV2 {
                    record,
                    retention_priority: retention.retention_priority,
                    retention_reason_digest: retention.retention_reason_digest,
                })
            })
            .collect::<Result<Vec<_>, CognitiveStoreError>>()?;

        let acquired_at_unix_ms = u64::try_from(now_unix_seconds)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
            .checked_mul(1_000)
            .ok_or_else(|| {
                CognitiveStoreError::Invalid(
                    "cognitive compaction acquisition time overflow".to_string(),
                )
            })?;
        let lease_expires_unix_ms = acquired_at_unix_ms.checked_add(1_000).ok_or_else(|| {
            CognitiveStoreError::Invalid("cognitive compaction lease overflow".to_string())
        })?;
        let authoritative = selected
            .owner_snapshot()
            .bind_context(
                generation_vector,
                acquired_at_unix_ms,
                lease_expires_unix_ms,
            )
            .map_err(|error| {
                CognitiveStoreError::Invalid(format!(
                    "cognitive compaction snapshot binding failed: {error}"
                ))
            })?;
        let candidate = build_qualified_candidate(
            authoritative.snapshot_key().clone(),
            candidate_generation,
            predecessor_checkpoint_digest,
            policy,
            inputs,
        )
        .map_err(|error| {
            CognitiveStoreError::Invalid(format!(
                "cognitive compaction candidate rejected: {error}"
            ))
        })?;
        let product = CognitiveReadCompactionCandidateV1::new(
            candidate,
            selected.cut_digest(),
            read.receipt_digest(),
        )
        .map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "cognitive compaction product binding failed: {error}"
            ))
        })?;

        #[cfg(test)]
        pause_before_compaction_revalidation_for_test().await;
        self.revalidate_lane_c_selection(access, scope, &selected, now_unix_seconds)
            .await?;
        product.validate().map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "cognitive compaction product validation failed: {error}"
            ))
        })?;
        Ok(product)
    }
}

async fn load_exact_lineage(
    store: &CognitiveStore,
    scope: &CognitiveScope,
    record_ids: &[StableId],
) -> Result<Vec<MemoryRecord>, CognitiveStoreError> {
    let (scope_kind, workspace) = scope.database_parts();
    let mut transaction = store.pool.begin().await.map_err(unavailable)?;
    let ancestry_limit = i64::try_from(MAX_LANE_C_PAGE_ANCESTRY_REVISIONS + 1).map_err(|_| {
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
    let rows = revision_query
        .build()
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
    if rows.len() > MAX_LANE_C_PAGE_ANCESTRY_REVISIONS {
        return Err(CognitiveStoreError::Unavailable(format!(
            "cognitive compaction source exceeds {MAX_LANE_C_PAGE_ANCESTRY_REVISIONS} ancestry revisions"
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
    let citation_rows = citation_query
        .build()
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
    if citation_rows.len() > MAX_LANE_C_PAGE_CITATIONS {
        return Err(CognitiveStoreError::Unavailable(format!(
            "cognitive compaction source exceeds {MAX_LANE_C_PAGE_CITATIONS} citations"
        )));
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
            source_id: StableId::new(source_id)
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            source_digest: source_digest
                .parse()
                .map_err(|error| CognitiveStoreError::Corrupt(format!("{error}")))?,
        });
    }

    let mut lineages = Vec::with_capacity(rows.len());
    let mut previous: Option<MemoryRecord> = None;
    let mut previous_head = 0_i64;
    let mut observed_ids = BTreeSet::new();
    for row in rows {
        let raw_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let revision: i64 = row.try_get("revision").map_err(unavailable)?;
        let predecessor: Option<i64> = row.try_get("supersedes_revision").map_err(unavailable)?;
        let lifecycle: String = row.try_get("lifecycle").map_err(unavailable)?;
        let record_id = StableId::new(raw_id.clone())
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let prior = previous
            .as_ref()
            .filter(|record| record.record_id == record_id);
        if prior.is_none()
            && previous
                .as_ref()
                .is_some_and(|record| record.revision.get() != previous_head as u64)
        {
            return Err(CognitiveStoreError::Corrupt(
                "memory head is not the latest committed revision".to_string(),
            ));
        }
        if (revision == 1 && predecessor.is_some())
            || (revision > 1
                && !prior.is_some_and(|record| {
                    predecessor == Some(revision - 1)
                        && record.revision.get() == (revision - 1) as u64
                }))
        {
            return Err(CognitiveStoreError::Corrupt(
                "broken cognitive revision ancestry".to_string(),
            ));
        }
        let state = match lifecycle.as_str() {
            "active" => RecordState::Live,
            "tombstoned" => RecordState::Tombstone,
            _ => {
                return Err(CognitiveStoreError::Corrupt(
                    "invalid cognitive lifecycle".to_string(),
                ));
            }
        };
        if state == RecordState::Live
            && prior.is_some_and(|record| record.state == RecordState::Tombstone)
        {
            return Err(CognitiveStoreError::Corrupt(
                "tombstoned memory resurrection".to_string(),
            ));
        }
        let content_digest: String = row.try_get("content_sha256").map_err(unavailable)?;
        let mut record_citations = citations.remove(&(raw_id, revision)).ok_or_else(|| {
            CognitiveStoreError::Corrupt("missing cognitive citations".to_string())
        })?;
        record_citations.sort();
        let record = MemoryRecord {
            record_id: record_id.clone(),
            revision: Revision::new(
                u64::try_from(revision)
                    .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            )
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            kind: DURABLE_SQLITE_MEMORY_KIND,
            content_digest: content_digest
                .parse()
                .map_err(|error| CognitiveStoreError::Corrupt(format!("{error}")))?,
            predecessor_digest: prior.map(MemoryRecord::record_digest),
            citations: record_citations,
            state,
        };
        record
            .validate()
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let head_revision: i64 = row.try_get("head_revision").map_err(unavailable)?;
        if head_revision < revision {
            return Err(CognitiveStoreError::Corrupt(
                "memory head regressed behind committed revision".to_string(),
            ));
        }
        previous_head = head_revision;
        observed_ids.insert(record_id);
        previous = Some(record.clone());
        lineages.push(record);
    }
    if previous
        .as_ref()
        .is_some_and(|record| record.revision.get() != previous_head as u64)
    {
        return Err(CognitiveStoreError::Corrupt(
            "memory head is not the latest committed revision".to_string(),
        ));
    }
    if observed_ids.len() != record_ids.len()
        || record_ids
            .iter()
            .any(|record_id| !observed_ids.contains(record_id))
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive compaction lineage set changed during acquisition".to_string(),
        ));
    }
    transaction.commit().await.map_err(unavailable)?;
    Ok(lineages)
}

fn verify_read_matches_lineage(
    read_records: &[codex_hepta_cognitive_read::ReadProjectionRecordV1],
    lineage: &[MemoryRecord],
    record_ids: &[StableId],
) -> Result<(), CognitiveStoreError> {
    let mut heads = BTreeMap::<StableId, &MemoryRecord>::new();
    for record in lineage {
        heads.insert(record.record_id.clone(), record);
    }
    let read_by_id = read_records
        .iter()
        .map(|record| (record.record_id.clone(), record))
        .collect::<BTreeMap<_, _>>();
    if heads.len() != record_ids.len() || read_by_id.len() != record_ids.len() {
        return Err(CognitiveStoreError::Conflict(
            "cognitive compaction head set changed during acquisition".to_string(),
        ));
    }
    for record_id in record_ids {
        let head = heads.get(record_id).ok_or_else(|| {
            CognitiveStoreError::Conflict(
                "cognitive compaction owner lineage lost a head".to_string(),
            )
        })?;
        let read = read_by_id.get(record_id).ok_or_else(|| {
            CognitiveStoreError::Conflict("cognitive compaction exact read lost a head".to_string())
        })?;
        let mut citations = head.citations.clone();
        citations.sort();
        if read.revision != head.revision
            || read.kind != head.kind
            || read.state != head.state
            || read.content_digest != Some(head.content_digest)
            || read.predecessor_digest != head.predecessor_digest
            || read.citations != citations
        {
            return Err(CognitiveStoreError::Conflict(
                "cognitive compaction exact read and owner lineage disagree".to_string(),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
struct CompactionFinalRevalidationHook {
    reached: tokio::sync::Notify,
    release: tokio::sync::Notify,
}

#[cfg(test)]
static COMPACTION_FINAL_REVALIDATION_HOOK: std::sync::OnceLock<
    std::sync::Mutex<Option<std::sync::Arc<CompactionFinalRevalidationHook>>>,
> = std::sync::OnceLock::new();

#[cfg(test)]
fn install_compaction_final_revalidation_hook(
    hook: std::sync::Arc<CompactionFinalRevalidationHook>,
) {
    *COMPACTION_FINAL_REVALIDATION_HOOK
        .get_or_init(|| std::sync::Mutex::new(None))
        .lock()
        .expect("compaction revalidation hook lock") = Some(hook);
}

#[cfg(test)]
async fn pause_before_compaction_revalidation_for_test() {
    let hook = COMPACTION_FINAL_REVALIDATION_HOOK
        .get_or_init(|| std::sync::Mutex::new(None))
        .lock()
        .expect("compaction revalidation hook lock")
        .take();
    if let Some(hook) = hook {
        hook.reached.notify_one();
        hook.release.notified().await;
    }
}

#[cfg(test)]
#[path = "cognitive_read_compact_product_tests.rs"]
mod tests;

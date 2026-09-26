//! Candidate-directed Lane C cut for the Agentd retrieval hot path.
//!
//! The physical SQLite owner and its existing keyset page API remain the only
//! source of facts. This host bridge selects only owner-observed candidate
//! heads from one globally bound page cut, so unrelated immutable history no
//! longer has to fit the legacy whole-scope snapshot ceiling.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_read::AuthoritativeSnapshotV1;
use codex_hepta_cognitive_read::ReadIdsError;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_read::read_ids_v1;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveOwnerFrontiers;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MAX_LANE_C_SNAPSHOT_PAGE_HEADS;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const RETRIEVAL_PAGE_HEADS: usize = 32;
const PAGED_RETRIEVAL_CUT_DOMAIN: &[u8] = b"hepta.agentd.paged-retrieval-cut.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PagedRetrievalOwnerCutV1 {
    scope_id: StableId,
    frontiers: CognitiveOwnerFrontiers,
    snapshot: CognitiveSnapshot,
    observed_at_unix_seconds: i64,
}

impl PagedRetrievalOwnerCutV1 {
    pub(crate) async fn acquire(
        store: &CognitiveStore,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        record_ids: impl IntoIterator<Item = StableId>,
    ) -> Result<Self, CognitiveStoreError> {
        if now_unix_seconds < 0 {
            return Err(CognitiveStoreError::Invalid(
                "negative retrieval cut time".to_string(),
            ));
        }
        let requested = record_ids.into_iter().collect::<BTreeSet<_>>();
        if requested.len() > 512 {
            return Err(CognitiveStoreError::Invalid(
                "retrieval owner cut accepts at most 512 exact record ids".to_string(),
            ));
        }

        let mut cursor = None;
        let mut page_heads = u32::try_from(
            RETRIEVAL_PAGE_HEADS.min(MAX_LANE_C_SNAPSHOT_PAGE_HEADS),
        )
        .map_err(|_| CognitiveStoreError::Invalid("retrieval page bound overflow".to_string()))?;
        let mut selected = BTreeMap::<StableId, MemoryRecord>::new();
        let mut identity: Option<(StableId, CognitiveOwnerFrontiers, i64, Digest32)> = None;

        loop {
            let page = loop {
                match store
                    .lane_c_snapshot_page(
                        access,
                        scope,
                        now_unix_seconds,
                        page_heads,
                        cursor.clone(),
                    )
                    .await
                {
                    Ok(page) => break page,
                    Err(CognitiveStoreError::Unavailable(message))
                        if page_heads > 1 && message.contains("retry with fewer heads") =>
                    {
                        page_heads = (page_heads / 2).max(1);
                    }
                    Err(error) => return Err(error),
                }
            };
            if page.authority().grants_any() {
                return Err(CognitiveStoreError::Corrupt(
                    "Lane C retrieval page unexpectedly grants authority".to_string(),
                ));
            }
            let observed = (
                page.scope_id().clone(),
                page.frontiers().clone(),
                page.observed_at_unix_seconds(),
                page.cut_digest(),
            );
            if let Some(expected) = &identity {
                if expected != &observed {
                    return Err(CognitiveStoreError::Conflict(
                        "Lane C retrieval pages do not share one owner cut".to_string(),
                    ));
                }
            } else {
                identity = Some(observed);
            }
            for record in page.records() {
                if requested.contains(&record.record_id)
                    && selected
                        .insert(record.record_id.clone(), record.clone())
                        .is_some()
                {
                    return Err(CognitiveStoreError::Corrupt(
                        "Lane C retrieval cut returned a duplicate current head".to_string(),
                    ));
                }
            }
            if selected.len() == requested.len() || page.is_complete() {
                break;
            }
            cursor = Some(page.next().cloned().ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "Lane C retrieval page omitted its continuation".to_string(),
                )
            })?);
        }

        let (scope_id, frontiers, observed_at_unix_seconds, _) = identity.ok_or_else(|| {
            CognitiveStoreError::Corrupt(
                "Lane C retrieval paging did not produce an owner cut".to_string(),
            )
        })?;
        let generation = frontiers
            .memory
            .checked_add(1)
            .ok_or_else(|| CognitiveStoreError::Corrupt("memory frontier overflow".to_string()))?;
        let snapshot = build_snapshot(
            Generation::new(generation)
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            selected.into_values().collect(),
        )
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        Ok(Self {
            scope_id,
            frontiers,
            snapshot,
            observed_at_unix_seconds,
        })
    }

    pub(crate) fn snapshot(&self) -> &CognitiveSnapshot {
        &self.snapshot
    }

    /// Stable semantic cut used in public response binding.
    ///
    /// The page cursor's observation timestamp is intentionally excluded so a
    /// final-use revalidation in a later wall-clock second can prove the same
    /// owner state. Any memory/source/tombstone/fact/KG frontier change still
    /// invalidates the cut, and selected record changes alter the snapshot.
    pub(crate) fn cut_digest(&self) -> Digest32 {
        let mut bytes = PAGED_RETRIEVAL_CUT_DOMAIN.to_vec();
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

    pub(crate) fn read_ids(
        &self,
        request: ReadIdsRequestV1,
    ) -> Result<ReadIdsResultV1, ReadIdsError> {
        read_ids_v1(&self.snapshot, request)
    }

    pub(crate) fn bind_context(
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

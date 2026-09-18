//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::future::Future;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory_retrieval::RetrievalCandidate as BoundRetrievalCandidate;
use codex_hepta_memory_retrieval::RetrievalRequest as BoundRetrievalRequest;
use codex_hepta_memory_retrieval::retrieve_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;

const MAX_CONTEXT_JSON_BYTES: usize = 24 * 1024;

/// Only storage failures may invalidate the canonical SQLite owner. A revoked
/// or unavailable optional ranker closes the ranked read, not other store ports.
#[derive(Debug)]
pub(crate) enum CognitiveContextError {
    Store(CognitiveStoreError),
    RankerUnavailable,
}

impl From<CognitiveStoreError> for CognitiveContextError {
    fn from(error: CognitiveStoreError) -> Self {
        Self::Store(error)
    }
}

/// `body_generation` is the process launch identity, not the separately fenced
/// fleet lifecycle epoch (Starting -> Running advances that epoch).
pub(crate) async fn read(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_before_revalidate(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        || async {},
    )
    .await
}

async fn read_with_before_revalidate<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    mut before_revalidate: F,
) -> Result<CognitiveContextSnapshot, CognitiveContextError>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = ()>,
{
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, now_seconds()?)
        .await?;
    let read = cut
        .read(ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: cut.snapshot().snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 1024,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 1024 * 1024,
        })
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let candidates = store
        .retrieve_memory_candidates_for_ranking(&access, &RetrievalRequest::new(query, now_seconds()?))
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };

    // The SQLite owner is the only candidate generator. The retrieval module
    // receives only exact records admitted by the coherent Lane-C cut and binds
    // the complete owner-supplied set through V2 before any learned reordering.
    // The legacy lexical score field carries the already-aggregated owner RRF
    // score here; graph/freshness stay zero so the bridge never double-counts.
    let mut bound_candidates = Vec::with_capacity(candidates.candidates.len());
    for candidate in &candidates.candidates {
        let memory = &candidate.memory;
        let Some(record) = read.records().iter().find(|record| {
            record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record.content_digest.to_string() == memory.content_sha256.as_str()
                && memory.scope == scope
        }) else {
            continue;
        };
        let owner_score = i64::try_from(candidate.reciprocal_rank_score).map_err(|_| {
            CognitiveStoreError::Corrupt("retrieval owner score exceeds i64".to_string())
        })?;
        bound_candidates.push(BoundRetrievalCandidate {
            record: record.clone(),
            snapshot_digest: read.snapshot_digest(),
            lexical_score: FixedQ32::from_raw(owner_score),
            graph_score: FixedQ32::ZERO,
            freshness_score: FixedQ32::ZERO,
        });
    }
    let query_digest = Digest32::of_bytes(query.as_bytes());
    let query_id = StableId::new(format!("memory-query-{query_digest}"))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let bound = retrieve_v2(BoundRetrievalRequest {
        query_id,
        query_digest,
        snapshot_digest: read.snapshot_digest(),
        maximum_results: 16,
        candidates: bound_candidates,
    })
    .map_err(|error| CognitiveStoreError::Corrupt(format!("memory retrieval binding: {error}")))?;

    // Ranking sees the complete owner batch admitted above before the response
    // byte/result budget. The optional learned ranker is deliberately downstream
    // of the deterministic owner+memory.retrieval ordering and cannot add items.
    let mut admitted_items = Vec::new();
    for result in &bound.retrieval.results {
        let Some(record) = read.records().iter().find(|record| {
            record.record_id == result.record_id && record.record_digest() == result.record_digest
        }) else {
            return Err(CognitiveStoreError::Corrupt(
                "bound retrieval result left the admitted snapshot".to_string(),
            )
            .into());
        };
        let Some(candidate) = candidates.candidates.iter().find(|candidate| {
            candidate.memory.id.memory_id.as_str() == record.record_id.as_str()
                && candidate.memory.id.revision == record.revision.get()
        }) else {
            return Err(CognitiveStoreError::Corrupt(
                "bound retrieval result left the owner candidate set".to_string(),
            )
            .into());
        };
        let memory = &candidate.memory;
        admitted_items.push(CognitiveContextItem {
            memory_id: memory.id.memory_id.as_str().to_string(),
            revision: memory.id.revision,
            content: memory.content.clone(),
            content_sha256: memory.content_sha256.as_str().to_string(),
        });
    }
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        let rank_owner = owner.clone();
        let rank_query = query.to_string();
        admitted_items = tokio::task::spawn_blocking(move || {
            ranker.rank(
                &rank_owner,
                body_generation,
                &rank_query,
                &mut admitted_items,
            )?;
            Ok::<_, String>(admitted_items)
        })
        .await
        .map_err(|_| CognitiveContextError::RankerUnavailable)?
        .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    // Bound the complete payload, including JSON escaping and envelope, only
    // after ranking.  This preserves the highest-ranked item when the legacy
    // byte cut would otherwise discard it.  Oversized winners are skipped so
    // they cannot consume the only result slot.
    for item in admitted_items {
        response.items.push(item);
        let encoded_bytes = serde_json::to_vec(&response)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
            .len();
        if encoded_bytes > MAX_CONTEXT_JSON_BYTES - 1024 {
            response.items.pop();
            continue;
        }
        if response.items.len() == usize::from(limit) {
            break;
        }
    }
    let encoded_context = serde_json::to_vec(&response)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let now_micros = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
            .as_micros(),
    )
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    let plan = plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: read.snapshot_digest(),
        read_digest: read.receipt_digest(),
        verified_item_count: response.items.len() as u32,
        encoded_context: &encoded_context,
        maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
        observed_at_micros: now_micros,
        expires_at_micros: now_micros.checked_add(1_000_000).ok_or_else(|| {
            CognitiveStoreError::Invalid("context plan expiry overflow".to_string())
        })?,
    })
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    if !plan.read_allowed {
        response.items.clear();
    }
    response.plan = Some(CognitiveContextPlan {
        evaluated_context_digest: plan.context_digest.to_string(),
        plan_receipt_digest: plan.evaluation.plan.receipt_digest().to_string(),
        read_allowed: plan.read_allowed,
    });
    if serde_json::to_vec(&response)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
        .len()
        > MAX_CONTEXT_JSON_BYTES
    {
        return Err(CognitiveStoreError::Invalid(
            "planned context exceeds response budget".to_string(),
        )
        .into());
    }
    // A concurrent correction, deletion, changed citation, expiry or restored
    // older database must not leak a stale projection into the response.
    before_revalidate().await;
    store
        .revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)
        .await?;
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    Ok(response)
}

fn now_seconds() -> Result<i64, CognitiveStoreError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_secs();
    i64::try_from(seconds).map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

#[cfg(test)]
#[path = "cognitive_context_tests.rs"]
mod tests;

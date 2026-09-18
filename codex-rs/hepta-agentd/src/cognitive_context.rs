//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::collections::BTreeMap;
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
use codex_hepta_memory::MemoryRevalidationBinding;
use codex_hepta_memory::RetrievalRequest as StoreRetrievalRequest;
use codex_hepta_memory::RevalidationStatus;
use codex_hepta_memory_retrieval::MAX_GENERATION_BOUND_RESULTS;
use codex_hepta_memory_retrieval::RetrievalCandidate as RankedRetrievalCandidate;
use codex_hepta_memory_retrieval::RetrievalRequest as RankedRetrievalRequest;
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
    read_with_after_ranking(
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

async fn read_with_after_ranking<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    mut after_ranking: F,
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
    let now = now_seconds()?;
    let cut = store.lane_c_snapshot(&access, &scope, now).await?;
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

    // The canonical owner generates candidates. memory.retrieval then binds the
    // complete bounded owner observation and deterministically orders the exact
    // revisions admitted by the coherent Lane C read. The optional learned
    // ranker is only a secondary permutation of this already-admitted set.
    let observation = store
        .observe_memory_retrieval(&access, &StoreRetrievalRequest::new(query, now))
        .await?;
    let owner_bindings = observation
        .candidates()
        .iter()
        .map(|candidate| candidate.revalidation.clone())
        .collect::<Vec<_>>();
    let owner_statuses = if owner_bindings.is_empty() {
        Vec::new()
    } else {
        store
            .revalidate_memory_candidates(&access, &owner_bindings, now)
            .await?
    };

    let mut candidates = Vec::new();
    let mut item_by_result = BTreeMap::new();
    let mut binding_by_item = BTreeMap::new();
    for (observed, status) in observation.candidates().iter().zip(owner_statuses) {
        let RevalidationStatus::Current(explanation) = status else {
            continue;
        };
        let memory = &explanation.memory;
        if memory.scope != scope {
            continue;
        }
        let Some(record) = read.records().iter().find(|record| {
            record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record.content_digest.to_string() == memory.content_sha256.as_str()
        }) else {
            continue;
        };
        let score = i64::try_from(observed.reciprocal_rank_score).map_err(|_| {
            CognitiveStoreError::Corrupt("owner retrieval score exceeds i64".to_string())
        })?;
        candidates.push(RankedRetrievalCandidate {
            record: record.clone(),
            snapshot_digest: read.snapshot_digest(),
            // The SQLite owner has already fused its four generator channels
            // with RRF. V2 preserves that order by carrying the aggregate in
            // the legacy score slot while query_digest binds the full owner
            // observation (including channel identities and limit signals).
            lexical_score: FixedQ32::from_raw(score),
            graph_score: FixedQ32::ZERO,
            freshness_score: FixedQ32::ZERO,
        });
        let item = CognitiveContextItem {
            memory_id: memory.id.memory_id.as_str().to_string(),
            revision: memory.id.revision,
            content: memory.content.clone(),
            content_sha256: memory.content_sha256.as_str().to_string(),
        };
        let result_key = (
            record.record_id.to_string(),
            record.record_digest().to_string(),
        );
        let item_key = item_binding_key(&item);
        item_by_result.insert(result_key, item);
        binding_by_item.insert(item_key, observed.revalidation.clone());
    }

    let mut admitted_items = Vec::new();
    if !candidates.is_empty() {
        let observation_digest =
            Digest32::of_bytes(observation.observation_sha256().as_str().as_bytes());
        let query_id = StableId::new(format!("cognitive-context:{observation_digest}"))
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let maximum_results = candidates.len().min(MAX_GENERATION_BOUND_RESULTS);
        let bound = retrieve_v2(RankedRetrievalRequest {
            query_id,
            query_digest: observation_digest,
            snapshot_digest: read.snapshot_digest(),
            maximum_results,
            candidates,
        })
        .map_err(|error| {
            CognitiveStoreError::Corrupt(format!("memory.retrieval rejected owner input: {error}"))
        })?;
        for result in bound.retrieval.results {
            if let Some(item) = item_by_result.remove(&(
                result.record_id.to_string(),
                result.record_digest.to_string(),
            )) {
                admitted_items.push(item);
            }
        }
    }

    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };

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

    // Test-only callers can race a real correction/deletion at exactly the
    // product boundary. Production passes a no-op here.
    after_ranking().await;

    // Revalidate the exact ranked attachment set after every ranking stage.
    // A correction, tombstone, citation/source change, validity change or KG
    // generation drift cannot be delivered merely because it ranked earlier.
    let mut ranked_items = Vec::new();
    let mut ranked_bindings = Vec::<MemoryRevalidationBinding>::new();
    for item in admitted_items {
        if let Some(binding) = binding_by_item.get(&item_binding_key(&item)) {
            ranked_items.push(item);
            ranked_bindings.push(binding.clone());
        }
    }
    let ranked_statuses = if ranked_bindings.is_empty() {
        Vec::new()
    } else {
        store
            .revalidate_memory_candidates(&access, &ranked_bindings, now_seconds()?)
            .await?
    };
    let mut admitted_items = Vec::new();
    for (item, status) in ranked_items.into_iter().zip(ranked_statuses) {
        let RevalidationStatus::Current(explanation) = status else {
            continue;
        };
        if explanation.memory.id.memory_id.as_str() == item.memory_id
            && explanation.memory.id.revision == item.revision
            && explanation.memory.content_sha256.as_str() == item.content_sha256
            && explanation.memory.scope == scope
        {
            admitted_items.push(item);
        }
    }

    // Bound the complete payload, including JSON escaping and envelope, only
    // after retrieval and optional learned ranking. Oversized winners are
    // skipped so they cannot consume the only result slot.
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

#[cfg(test)]
pub(super) async fn read_with_test_hook<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    after_ranking: F,
) -> Result<CognitiveContextSnapshot, CognitiveContextError>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = ()>,
{
    read_with_after_ranking(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        after_ranking,
    )
    .await
}

fn item_binding_key(item: &CognitiveContextItem) -> (String, u64, String) {
    (
        item.memory_id.clone(),
        item.revision,
        item.content_sha256.clone(),
    )
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

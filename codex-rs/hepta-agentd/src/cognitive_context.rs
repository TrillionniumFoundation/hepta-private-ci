//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

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
use codex_hepta_memory::RetrievalChannel;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::RetrievalSemanticRelation;
use codex_hepta_memory::RevalidationStatus;
use codex_hepta_memory_retrieval::MAX_OWNER_RANK_RESULTS;
use codex_hepta_memory_retrieval::OwnerEvidenceChannelV1;
use codex_hepta_memory_retrieval::OwnerRankCandidateV1;
use codex_hepta_memory_retrieval::OwnerRankRequestV1;
use codex_hepta_memory_retrieval::rank_owner_candidates;
use codex_hepta_types::Digest32;
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
    read_inner(
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

#[cfg(test)]
pub(crate) async fn read_with_test_after_selection<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    after_selection: F,
) -> Result<CognitiveContextSnapshot, CognitiveContextError>
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = ()>,
{
    read_inner(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        after_selection,
    )
    .await
}

async fn read_inner<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    after_selection: F,
) -> Result<CognitiveContextSnapshot, CognitiveContextError>
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = ()>,
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
    // The SQLite owner is the only candidate generator. memory.retrieval then
    // binds and deterministically ranks the complete bounded owner observation;
    // the optional learned ranker may only permute that admitted result set.
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new(query, now_seconds()?))
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };
    // Intersect every owner-observed candidate with the exact Lane C read cut
    // before ranking. The scalar score below is the owner's already-aggregated
    // RRF score; no synthetic per-channel semantics are invented here.
    let mut bounded_candidates = Vec::new();
    let mut candidate_bindings = Vec::<MemoryRevalidationBinding>::new();
    for observed in observation.candidates() {
        let Some(record) = read.records().iter().find(|record| {
            record.record_id.as_str() == observed.revalidation.memory.memory_id.as_str()
                && record.revision.get() == observed.revalidation.memory.revision
                && record.content_digest.to_string()
                    == observed.revalidation.content_sha256.as_str()
        }) else {
            continue;
        };
        bounded_candidates.push(OwnerRankCandidateV1 {
            record: record.clone(),
            snapshot_digest: read.snapshot_digest(),
            owner_score: observed.reciprocal_rank_score,
            support_digest: Digest32::of_bytes(
                observation.observation_sha256().as_str().as_bytes(),
            ),
            evidence_channels: owner_evidence_channels(
                &observed.channels,
                &observed.semantic_relations,
            ),
        });
        candidate_bindings.push(observed.revalidation.clone());
    }

    let mut query_binding = b"hepta.agentd.owner-retrieval.v1".to_vec();
    query_binding.extend_from_slice(query.as_bytes());
    query_binding.extend_from_slice(observation.observation_sha256().as_str().as_bytes());
    let query_digest = Digest32::of_bytes(&query_binding);
    let query_id = StableId::new(format!("query:{query_digest}"))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let bounded = rank_owner_candidates(OwnerRankRequestV1 {
        query_id,
        query_digest,
        snapshot_digest: read.snapshot_digest(),
        maximum_results: MAX_OWNER_RANK_RESULTS,
        candidates: bounded_candidates,
    })
    .map_err(|error| CognitiveStoreError::Corrupt(format!("bounded retrieval failed: {error}")))?;

    let mut ranked_bindings = Vec::with_capacity(bounded.results.len());
    for result in &bounded.results {
        let Some(binding) = candidate_bindings
            .iter()
            .find(|binding| binding.memory.memory_id.as_str() == result.record_id.as_str())
        else {
            return Err(CognitiveStoreError::Corrupt(
                "bounded retrieval returned an unknown owner candidate".to_string(),
            )
            .into());
        };
        ranked_bindings.push(binding.clone());
    }

    // Resolve content and revalidate source/citation/KG support for all
    // deliverable candidates in one SQLite read transaction.
    let ranked_statuses = store
        .revalidate_memory_candidates(&access, &ranked_bindings, now_seconds()?)
        .await?;
    let mut admitted_items = Vec::with_capacity(ranked_statuses.len());
    for status in ranked_statuses {
        match status {
            RevalidationStatus::Current(explanation) => {
                let memory = explanation.memory;
                admitted_items.push(CognitiveContextItem {
                    memory_id: memory.id.memory_id.as_str().to_string(),
                    revision: memory.id.revision,
                    content: memory.content,
                    content_sha256: memory.content_sha256.as_str().to_string(),
                });
            }
            RevalidationStatus::Stale(drift) => {
                return Err(CognitiveStoreError::Conflict(format!(
                    "retrieval candidate became stale before ranking: {drift:?}"
                ))
                .into());
            }
        }
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
    after_selection().await;

    // Revalidate the exact post-ranking attachment set. Tail candidates do not
    // participate in this gate, while any correction, deletion, citation drift
    // or KG-generation change affecting a selected item fails the read closed.
    let mut selected_bindings = Vec::with_capacity(response.items.len());
    for item in &response.items {
        let Some(binding) = candidate_bindings.iter().find(|binding| {
            binding.memory.memory_id.as_str() == item.memory_id.as_str()
                && binding.memory.revision == item.revision
        }) else {
            return Err(CognitiveStoreError::Corrupt(
                "selected context item has no owner revalidation binding".to_string(),
            )
            .into());
        };
        selected_bindings.push(binding.clone());
    }
    for status in store
        .revalidate_memory_candidates(&access, &selected_bindings, now_seconds()?)
        .await?
    {
        if let RevalidationStatus::Stale(drift) = status {
            return Err(CognitiveStoreError::Conflict(format!(
                "selected memory changed before context delivery: {drift:?}"
            ))
            .into());
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

fn owner_evidence_channels(
    channels: &[RetrievalChannel],
    semantic_relations: &[RetrievalSemanticRelation],
) -> Vec<OwnerEvidenceChannelV1> {
    let mut result = channels
        .iter()
        .map(|channel| match channel {
            RetrievalChannel::MemoryFts => OwnerEvidenceChannelV1::Lexical,
            RetrievalChannel::EntityFts => OwnerEvidenceChannelV1::Entity,
            RetrievalChannel::GraphOneHop => OwnerEvidenceChannelV1::GraphOneHop,
            RetrievalChannel::Recency => OwnerEvidenceChannelV1::Recency,
        })
        .collect::<Vec<_>>();
    for relation in semantic_relations {
        let channel = match relation {
            RetrievalSemanticRelation::TemporalBefore
            | RetrievalSemanticRelation::TemporalAfter => Some(OwnerEvidenceChannelV1::Temporal),
            RetrievalSemanticRelation::Causes | RetrievalSemanticRelation::Enables => {
                Some(OwnerEvidenceChannelV1::Causal)
            }
            RetrievalSemanticRelation::ProcedureStep => Some(OwnerEvidenceChannelV1::Procedural),
            RetrievalSemanticRelation::Contradicts => {
                Some(OwnerEvidenceChannelV1::ContradictionSupport)
            }
            RetrievalSemanticRelation::Supports
            | RetrievalSemanticRelation::PromptComplements
            | RetrievalSemanticRelation::PromptSubstitutes
            | RetrievalSemanticRelation::PromptConflicts => None,
        };
        if let Some(channel) = channel {
            result.push(channel);
        }
    }
    result.sort();
    result.dedup();
    result
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

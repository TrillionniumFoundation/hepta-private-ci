//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::collections::BTreeMap;
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
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::RevalidationStatus;
use codex_hepta_memory::execute_owner_observation;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
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
    RetrievalContextUnavailable,
    RetrievalLearningUnavailable,
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
    read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        None,
        None,
        None,
    )
    .await
}

pub(crate) async fn read_with_retrieval_context(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    current_retrieval: Option<&std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        current_retrieval,
        None,
        None,
    )
    .await
}

pub(crate) async fn read_with_retrieval_context_and_learning(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    current_retrieval: Option<&std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    learning_sink: Option<&std::sync::Arc<crate::CognitiveRetrievalLearningSink>>,
    request_id: Option<u64>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    let now = now_seconds()?;
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let retrieval_context = match current_retrieval {
        Some(current) => Some(load_retrieval_context(current, owner, body_generation).await?),
        None => None,
    };
    let expected_retrieval_context_digest = retrieval_context
        .as_ref()
        .map(RetrievalExecutionContextV1::binding_digest);
    if learning_sink.is_some() && retrieval_context.is_none() {
        return Err(CognitiveContextError::RetrievalLearningUnavailable);
    }
    let mut pending_assignment = None;

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
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new(query, now))
        .await?;
    let mut observed = observation.candidates().to_vec();

    if let Some(context) = &retrieval_context {
        let acquired_at_unix_ms = u64::try_from(now)
            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
            .checked_mul(1000)
            .ok_or_else(|| {
                CognitiveStoreError::Unavailable(
                    "retrieval context acquisition time overflow".to_string(),
                )
            })?;
        let lease_expires_unix_ms = acquired_at_unix_ms.checked_add(5_000).ok_or_else(|| {
            CognitiveStoreError::Unavailable("retrieval context lease overflow".to_string())
        })?;
        let execution = execute_owner_observation(
            &observation,
            &cut,
            context,
            Digest32::of_bytes(query.as_bytes()),
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        )?;
        let selection_order = execution
            .recall
            .packet
            .selections
            .iter()
            .enumerate()
            .map(|(index, selection)| {
                (
                    (
                        selection.record_id.as_str().to_string(),
                        selection.record_revision.get(),
                    ),
                    index,
                )
            })
            .collect::<BTreeMap<_, _>>();
        pending_assignment = Some(execution.assignment);
        observed.retain(|candidate| {
            selection_order.contains_key(&(
                candidate.revalidation.memory.memory_id.as_str().to_string(),
                candidate.revalidation.memory.revision,
            ))
        });
        observed.sort_by_key(|candidate| {
            selection_order
                .get(&(
                    candidate.revalidation.memory.memory_id.as_str().to_string(),
                    candidate.revalidation.memory.revision,
                ))
                .copied()
                .unwrap_or(usize::MAX)
        });
    } else {
        observed.sort_by(|left, right| {
            right
                .reciprocal_rank_score
                .cmp(&left.reciprocal_rank_score)
                .then_with(|| {
                    left.revalidation
                        .memory
                        .memory_id
                        .cmp(&right.revalidation.memory.memory_id)
                })
                .then_with(|| {
                    left.revalidation
                        .memory
                        .revision
                        .cmp(&right.revalidation.memory.revision)
                })
        });
    }

    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };
    // Admit the entire bounded owner observation before any final result
    // truncation. With a current HNMF context, the set has already passed
    // generation-bound recall. The optional learned ranker may only permute
    // that admitted set; it cannot add records.
    let mut admitted_items = Vec::new();
    let mut bindings = BTreeMap::new();
    for candidate in observed {
        let binding = candidate.revalidation;
        let accepted = read.records().iter().any(|record| {
            record.record_id.as_str() == binding.memory.memory_id.as_str()
                && record.revision.get() == binding.memory.revision
                && record.content_digest.to_string() == binding.content_sha256.as_str()
                && binding.scope == scope
        });
        if !accepted {
            continue;
        }
        let key = (
            binding.memory.memory_id.as_str().to_string(),
            binding.memory.revision,
        );
        bindings.insert(key.clone(), binding.clone());
        admitted_items.push(CognitiveContextItem {
            memory_id: key.0,
            revision: key.1,
            // Ranking binds exact ID/revision/content hash and does not inspect
            // raw text. Content is materialized only after final ordering.
            content: String::new(),
            content_sha256: binding.content_sha256.as_str().to_string(),
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

    let ordered_bindings = admitted_items
        .iter()
        .map(|item| {
            bindings
                .get(&(item.memory_id.clone(), item.revision))
                .cloned()
                .ok_or_else(|| {
                    CognitiveStoreError::Corrupt(
                        "ranked cognitive item lost its owner revalidation binding".to_string(),
                    )
                })
        })
        .collect::<Result<Vec<_>, _>>()?;
    let statuses = store
        .revalidate_memory_candidates(&access, &ordered_bindings, now_seconds()?)
        .await?;

    // Materialize raw text only after final ordering and revalidation. The
    // complete JSON budget is still enforced before response publication.
    for (mut item, status) in admitted_items.into_iter().zip(statuses) {
        let RevalidationStatus::Current(explanation) = status else {
            continue;
        };
        let memory = explanation.memory;
        let accepted = read.records().iter().any(|record| {
            record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record.content_digest.to_string() == memory.content_sha256.as_str()
                && memory.scope == scope
        });
        if !accepted
            || item.memory_id != memory.id.memory_id.as_str()
            || item.revision != memory.id.revision
            || item.content_sha256 != memory.content_sha256.as_str()
        {
            continue;
        }
        item.content = memory.content;
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
    if let (Some(current), Some(expected)) = (current_retrieval, expected_retrieval_context_digest)
    {
        let actual = load_retrieval_context(current, owner, body_generation)
            .await?
            .binding_digest();
        if actual != expected {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    if let Some(sink) = learning_sink {
        let assignment =
            pending_assignment.ok_or(CognitiveContextError::RetrievalLearningUnavailable)?;
        let request_id = request_id.ok_or(CognitiveContextError::RetrievalLearningUnavailable)?;
        let selected = assignment
            .selected_candidates
            .iter()
            .map(|candidate| {
                (
                    (
                        candidate.record_id.as_str().to_string(),
                        candidate.record_revision.get(),
                    ),
                    candidate.clone(),
                )
            })
            .collect::<BTreeMap<_, _>>();
        let delivered_candidates = response
            .items
            .iter()
            .map(|item| {
                selected
                    .get(&(item.memory_id.clone(), item.revision))
                    .cloned()
                    .ok_or(CognitiveContextError::RetrievalLearningUnavailable)
            })
            .collect::<Result<Vec<RetrievalCandidateIdentityV1>, _>>()?;
        let context_exposed = !delivered_candidates.is_empty();
        let sink = std::sync::Arc::clone(sink);
        let owner = owner.clone();
        tokio::task::spawn_blocking(move || {
            sink.append_with_delivery(
                &owner,
                body_generation,
                request_id,
                &assignment,
                &delivered_candidates,
                context_exposed,
            )
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?;
    }
    Ok(response)
}

async fn load_retrieval_context(
    current: &std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>,
    owner: &AgentId,
    body_generation: u64,
) -> Result<RetrievalExecutionContextV1, CognitiveContextError> {
    let current = std::sync::Arc::clone(current);
    let owner = owner.clone();
    let context = tokio::task::spawn_blocking(move || current.current(&owner, body_generation))
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    context
        .validate()
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    Ok(context)
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

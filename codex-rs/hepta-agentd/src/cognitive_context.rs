//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::collections::BTreeMap;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::retrieval_executor::RetrievalBlockingKind;
use crate::retrieval_executor::RetrievalExecutor;
use crate::retrieval_executor::RetrievalRequestWork;
use crate::retrieval_executor::RetrievalWorkClass;
use codex_hepta_agent_components::cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_agent_components::cognitive_read::ReadFieldV1;
use codex_hepta_agent_components::cognitive_read::ReadIdsError;
use codex_hepta_agent_components::cognitive_read::ReadIdsRequestV1;
use codex_hepta_agent_components::cognitive_read::ReadIdsResultV1;
use codex_hepta_agent_components::cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_agent_components::cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::contracts::Sha256Digest;
use codex_hepta_agent_components::memory::CognitiveAccess;
use codex_hepta_agent_components::memory::CognitiveScope;
use codex_hepta_agent_components::memory::DurableCognitiveSnapshot;
use codex_hepta_agent_components::memory::RetrievalCandidateIdentityV1;
use codex_hepta_agent_components::memory::RetrievalRequest;
use codex_hepta_agent_components::memory::RevalidationStatus;
use codex_hepta_agent_components::memory::execute_owner_observation_controlled;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::ProbabilityQ32;
use codex_hepta_agent_components::types::StableId;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextRevalidation;
use crate::CognitiveContextSnapshot;

#[path = "cognitive_retrieval_lease.rs"]
mod retrieval_lease;
use retrieval_lease::AcquiredRetrievalContext;

const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;
const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";

/// Only storage failures may invalidate the canonical SQLite owner. A revoked
/// or unavailable optional ranker closes the ranked read, not other store ports.
#[derive(Debug)]
pub(crate) enum CognitiveContextError {
    Store(CognitiveStoreError),
    RankerUnavailable,
    ReadUnavailable(String),
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
#[cfg(test)]
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

#[cfg(test)]
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

#[cfg(test)]
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
    read_with_retrieval_executor(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        current_retrieval,
        learning_sink,
        request_id,
        &RetrievalExecutor::new(),
    )
    .await
}

pub(crate) async fn read_with_retrieval_executor(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    current_retrieval: Option<&std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    learning_sink: Option<&std::sync::Arc<crate::CognitiveRetrievalLearningSink>>,
    request_id: Option<u64>,
    executor: &RetrievalExecutor,
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
    let delivers_hnmf = current_retrieval.is_some_and(|current| current.delivers_hnmf(owner));
    let request_work = executor.begin(RetrievalWorkClass::Delivery);
    let shadow_work = executor.begin_shadow(&request_work);
    let retrieval_work = if delivers_hnmf {
        &request_work
    } else {
        &shadow_work
    };
    let retrieval_context = match current_retrieval {
        Some(current) => {
            match load_retrieval_context(current, owner, body_generation, executor, retrieval_work)
                .await
            {
                Ok(context) => Some(context),
                Err(error) if delivers_hnmf => return Err(error),
                Err(_) => None, // An unavailable shadow cannot poison compatibility delivery.
            }
        }
        None => None,
    };
    let expected_retrieval_context_digest = retrieval_context
        .as_ref()
        .filter(|_| delivers_hnmf)
        .map(AcquiredRetrievalContext::binding_digest);
    if learning_sink.is_some() && current_retrieval.is_none() {
        return Err(CognitiveContextError::RetrievalLearningUnavailable);
    }
    let mut pending_assignment = None;

    let cut = executor
        .run_async(&request_work, {
            let store = store.clone();
            let access = access.clone();
            let scope = scope.clone();
            async move { store.lane_c_snapshot(&access, &scope, now).await }
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;
    let observation = executor
        .run_async(&request_work, {
            let store = store.clone();
            let access = access.clone();
            let query = query.to_string();
            async move {
                store
                    .observe_memory_retrieval(&access, &RetrievalRequest::new(&query, now))
                    .await
            }
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;
    let mut record_ids = observation
        .candidates()
        .iter()
        .map(|candidate| {
            StableId::new(candidate.revalidation.memory.memory_id.as_str())
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))
        })
        .collect::<Result<Vec<_>, _>>()?;
    record_ids.sort();
    record_ids.dedup();
    request_work
        .checkpoint()
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    let admission_read = cut
        .read_ids(ReadIdsRequestV1 {
            snapshot_digest: cut.snapshot().snapshot_digest,
            record_ids,
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        })
        .map_err(map_read_ids_error)?;
    let mut observed = observation.candidates().to_vec();

    let execution = match &retrieval_context {
        Some(context) => (|| -> Result<_, CognitiveContextError> {
            let acquired_at_unix_ms = u64::try_from(now)
                .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
                .checked_mul(1000)
                .ok_or_else(|| {
                    CognitiveStoreError::Unavailable(
                        "retrieval context acquisition time overflow".to_string(),
                    )
                })?;
            let lease_expires_unix_ms =
                acquired_at_unix_ms.checked_add(5_000).ok_or_else(|| {
                    CognitiveStoreError::Unavailable("retrieval context lease overflow".to_string())
                })?;
            let lease_expires_unix_ms = context.bound_deadline(lease_expires_unix_ms);
            if lease_expires_unix_ms <= acquired_at_unix_ms {
                return Err(CognitiveContextError::RetrievalContextUnavailable);
            }
            Ok((acquired_at_unix_ms, lease_expires_unix_ms))
        })(),
        None => Err(CognitiveContextError::RetrievalContextUnavailable),
    };
    let execution = match (execution, retrieval_context.as_ref()) {
        (Ok((acquired_at, expires_at)), Some(context)) => {
            let observation = observation.clone();
            let cut = cut.clone();
            let context = context.context.clone();
            let query_digest = Digest32::of_bytes(query.as_bytes());
            executor
                .run(retrieval_work, RetrievalBlockingKind::Core, move |work| {
                    execute_owner_observation_controlled(
                        &observation,
                        &cut,
                        &context,
                        query_digest,
                        acquired_at,
                        expires_at,
                        &work,
                    )
                    .map_err(|error| error.to_string())
                })
                .await
                .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)
        }
        (Err(error), _) => Err(error),
        (Ok(_), None) => Err(CognitiveContextError::RetrievalContextUnavailable),
    };
    match execution {
        Ok(execution) => {
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
            if delivers_hnmf {
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
            }
        }
        Err(error) if delivers_hnmf => return Err(error),
        Err(_) => {}
    }
    if !delivers_hnmf {
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
        snapshot_digest: admission_read.snapshot_digest().to_string(),
        read_digest: admission_read.receipt_digest().to_string(),
        omitted_records: 0,
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
        let accepted = admission_read.records().iter().any(|record| {
            record.is_live()
                && record.record_id.as_str() == binding.memory.memory_id.as_str()
                && record.revision.get() == binding.memory.revision
                && record
                    .content_digest
                    .is_some_and(|digest| digest.to_string() == binding.content_sha256.as_str())
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

    let mut downstream_policy_digest = None;
    let mut delivery_propensity = ProbabilityQ32::ONE;
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        let rank_owner = owner.clone();
        let rank_query = query.to_string();
        let (ranked_items, rank_observation) = executor
            .run(&request_work, RetrievalBlockingKind::Ranker, move |work| {
                work.checkpoint().map_err(|error| error.to_string())?;
                let observation = ranker.rank(
                    &rank_owner,
                    body_generation,
                    &rank_query,
                    &mut admitted_items,
                )?;
                work.checkpoint().map_err(|error| error.to_string())?;
                Ok((admitted_items, observation))
            })
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
        admitted_items = ranked_items;
        if rank_observation.applied {
            downstream_policy_digest = Some(rank_observation.policy_digest);
            delivery_propensity = rank_observation.propensity;
        }
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
    let revalidation_now = now_seconds()?;
    let statuses = executor
        .run_async(&request_work, {
            let store = store.clone();
            let access = access.clone();
            let ordered_bindings = ordered_bindings.clone();
            async move {
                store
                    .revalidate_memory_candidates(&access, &ordered_bindings, revalidation_now)
                    .await
            }
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;

    // Materialize raw text only after final ordering and revalidation. The
    // complete JSON budget is still enforced before response publication.
    for (mut item, status) in admitted_items.into_iter().zip(statuses) {
        let RevalidationStatus::Current(explanation) = status else {
            continue;
        };
        let memory = explanation.memory;
        let accepted = admission_read.records().iter().any(|record| {
            record.is_live()
                && record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record
                    .content_digest
                    .is_some_and(|digest| digest.to_string() == memory.content_sha256.as_str())
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

    let selected_read = read_selected_items(&cut, &response.items)?;
    let selected_read_binding =
        bind_selected_read(&cut, &selected_read, expected_retrieval_context_digest);
    response.snapshot_digest = selected_read.snapshot_digest().to_string();
    response.read_digest = selected_read_binding.to_string();
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
        source_snapshot_digest: selected_read.snapshot_digest(),
        read_digest: selected_read_binding,
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
    let final_fence_now = now_seconds()?;
    executor
        .run_async(&request_work, {
            let store = store.clone();
            let access = access.clone();
            let scope = scope.clone();
            let cut = cut.clone();
            async move {
                store
                    .revalidate_lane_c_snapshot(&access, &scope, &cut, final_fence_now)
                    .await
            }
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        executor
            .run(&request_work, RetrievalBlockingKind::Ranker, move |work| {
                work.checkpoint().map_err(|error| error.to_string())?;
                ranker.revalidate()?;
                work.checkpoint().map_err(|error| error.to_string())?;
                Ok(())
            })
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    if let (Some(current), Some(expected)) = (current_retrieval, expected_retrieval_context_digest)
    {
        let actual =
            load_retrieval_context(current, owner, body_generation, executor, &request_work)
                .await?
                .binding_digest();
        if actual != expected {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    // Append only a separately tagged, unexposed preparation. The append may
    // outlive a cancelled waiter; final freshness is checked again afterwards.
    // Neither this event nor an equal digest authenticates consumer publication.
    if let Some(sink) = learning_sink.filter(|_| pending_assignment.is_some()) {
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
            .filter(|_| delivers_hnmf)
            .map(|item| {
                selected
                    .get(&(item.memory_id.clone(), item.revision))
                    .cloned()
                    .ok_or(CognitiveContextError::RetrievalLearningUnavailable)
            })
            .collect::<Result<Vec<RetrievalCandidateIdentityV1>, _>>()?;
        // A shadow assignment is evidence only. Neither compatibility records
        // nor a compatibility ranker may be labeled as HNMF treatment/exposure.
        if !delivers_hnmf {
            downstream_policy_digest = None;
            delivery_propensity = ProbabilityQ32::ONE;
        }
        let has_prepared_context = !delivered_candidates.is_empty();
        let prepared_context_digest = if has_prepared_context {
            Some(Digest32::of_bytes(&serde_json::to_vec(&response).map_err(
                |error| CognitiveStoreError::Invalid(error.to_string()),
            )?))
        } else {
            None
        };
        let sink = std::sync::Arc::clone(sink);
        let owner = owner.clone();
        let appended = executor
            .run(retrieval_work, RetrievalBlockingKind::Ledger, move |work| {
                work.checkpoint().map_err(|error| error.to_string())?;
                let receipt = sink.append_preparation(
                    &owner,
                    body_generation,
                    request_id,
                    &assignment,
                    &delivered_candidates,
                    prepared_context_digest,
                    downstream_policy_digest,
                    delivery_propensity,
                )?;
                work.checkpoint().map_err(|error| error.to_string())?;
                Ok(receipt)
            })
            .await
            .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable);
        if delivers_hnmf {
            appended?;
        } else if appended.is_err() {
            eprintln!("shadow retrieval assignment append unavailable; no exposure recorded");
        }
    }
    // An immutable preparation is allowed to survive failure. It cannot be
    // interpreted as publication, so freshness must not be weakened to avoid
    // recording an unexposed attempt whose response was never delivered.
    // A concurrent correction, deletion, changed citation, expiry or restored
    // older database must not leak a stale projection into the response.
    let final_fence_now = now_seconds()?;
    executor
        .run_async(&request_work, {
            let store = store.clone();
            let access = access.clone();
            let scope = scope.clone();
            let cut = cut.clone();
            async move {
                store
                    .revalidate_lane_c_snapshot(&access, &scope, &cut, final_fence_now)
                    .await
            }
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        executor
            .run(&request_work, RetrievalBlockingKind::Ranker, move |work| {
                work.checkpoint().map_err(|error| error.to_string())?;
                ranker.revalidate()?;
                work.checkpoint().map_err(|error| error.to_string())?;
                Ok(())
            })
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    if let (Some(current), Some(expected)) = (current_retrieval, expected_retrieval_context_digest)
    {
        let actual =
            load_retrieval_context(current, owner, body_generation, executor, &request_work)
                .await?
                .binding_digest();
        if actual != expected {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    request_work
        .checkpoint()
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    Ok(response)
}

#[cfg(test)]
pub(crate) async fn revalidate(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    revalidate_with_retrieval_context(
        store,
        owner,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        plan,
        ranker,
        1,
        None,
    )
    .await
}

#[cfg(test)]
pub(crate) async fn revalidate_with_retrieval_context(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    body_generation: u64,
    current_retrieval: Option<&std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>>,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    revalidate_with_retrieval_executor(
        store,
        owner,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        plan,
        ranker,
        body_generation,
        current_retrieval,
        &RetrievalExecutor::new(),
    )
    .await
}

pub(crate) async fn revalidate_with_retrieval_executor(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    body_generation: u64,
    current_retrieval: Option<&std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    executor: &RetrievalExecutor,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    let request_work = executor.begin(RetrievalWorkClass::Delivery);
    if items.len() > 4 {
        return Err(CognitiveStoreError::Invalid(
            "context revalidation accepts at most four items".to_string(),
        )
        .into());
    }
    let expected_snapshot: Digest32 = snapshot_digest.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid snapshot digest: {error}"))
    })?;
    let expected_read: Digest32 = read_digest
        .parse()
        .map_err(|error| CognitiveStoreError::Invalid(format!("invalid read digest: {error}")))?;
    let plan = plan.ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive context final use requires a plan".to_string())
    })?;
    if plan.read_allowed == items.is_empty() {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context plan/item disposition mismatch".to_string(),
        )
        .into());
    }
    if plan.read_allowed {
        let pre_plan = CognitiveContextSnapshot {
            snapshot_digest: snapshot_digest.to_string(),
            read_digest: read_digest.to_string(),
            omitted_records,
            items: items.to_vec(),
            plan: None,
        };
        let encoded = serde_json::to_vec(&pre_plan)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        if Digest32::of_bytes(&encoded).to_string() != plan.evaluated_context_digest {
            return Err(CognitiveStoreError::Conflict(
                "cognitive context ordered payload changed before final use".to_string(),
            )
            .into());
        }
    }
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let revalidation_snapshot_now = now_seconds()?;
    let cut = executor
        .run_async(&request_work, {
            let store = store.clone();
            let access = access.clone();
            let scope = scope.clone();
            async move {
                store
                    .lane_c_snapshot(&access, &scope, revalidation_snapshot_now)
                    .await
            }
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;
    if cut.snapshot().snapshot_digest != expected_snapshot {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context snapshot is stale".to_string(),
        )
        .into());
    }

    let read = read_selected_items(&cut, items)?;
    let retrieval_context_digest =
        match current_retrieval.filter(|reader| reader.delivers_hnmf(owner)) {
            Some(current) => Some(
                load_retrieval_context(current, owner, body_generation, executor, &request_work)
                    .await?
                    .binding_digest(),
            ),
            None => None,
        };
    let current_read_binding = bind_selected_read(&cut, &read, retrieval_context_digest);
    if current_read_binding != expected_read {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context owner cut or read receipt is stale".to_string(),
        )
        .into());
    }
    if !read.missing_ids().is_empty() || read.records().len() != items.len() {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context item set is stale".to_string(),
        )
        .into());
    }
    let records = read
        .records()
        .iter()
        .map(|record| (record.record_id.as_str(), record))
        .collect::<BTreeMap<_, _>>();
    for item in items {
        let content_digest = Sha256Digest::for_bytes(item.content.as_bytes());
        if content_digest.as_str() != item.content_sha256.as_str() {
            return Err(CognitiveStoreError::Invalid(
                "cognitive context content hash mismatch".to_string(),
            )
            .into());
        }
        let expected_content: Digest32 = item.content_sha256.parse().map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid cognitive content digest: {error}"))
        })?;
        let current = records.get(item.memory_id.as_str()).ok_or_else(|| {
            CognitiveStoreError::Conflict("cognitive context item disappeared".to_string())
        })?;
        if !current.is_live()
            || current.revision.get() != item.revision
            || current.content_digest != Some(expected_content)
        {
            return Err(CognitiveStoreError::Conflict(
                "cognitive context item changed before final use".to_string(),
            )
            .into());
        }
    }

    // Ranking is part of the selected context semantics. A registry/model
    // revocation after response publication must close final use even when the
    // underlying memory rows remain unchanged.
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        executor
            .run(&request_work, RetrievalBlockingKind::Ranker, move |work| {
                work.checkpoint().map_err(|error| error.to_string())?;
                ranker.revalidate()?;
                work.checkpoint().map_err(|error| error.to_string())?;
                Ok(())
            })
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }

    // The optional ranker above may await. Recheck both owners after that gap.
    let final_fence_now = now_seconds()?;
    executor
        .run_async(&request_work, {
            let store = store.clone();
            let access = access.clone();
            let scope = scope.clone();
            let cut = cut.clone();
            async move {
                store
                    .revalidate_lane_c_snapshot(&access, &scope, &cut, final_fence_now)
                    .await
            }
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;
    if let (Some(current), Some(expected)) = (current_retrieval, retrieval_context_digest) {
        if load_retrieval_context(current, owner, body_generation, executor, &request_work)
            .await?
            .binding_digest()
            != expected
        {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    Ok(CognitiveContextRevalidation {
        snapshot_digest: expected_snapshot.to_string(),
        read_digest: current_read_binding.to_string(),
        verified_item_count: u16::try_from(items.len()).map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid context item count: {error}"))
        })?,
    })
}

/// Bind the selected exact-ID receipt to the complete durable owner cut.
///
/// The public Agentd response keeps its existing read_digest field, but that
/// field now invalidates on source/tombstone/KG frontier drift even when the
/// selected memory heads themselves remain byte-identical.
fn bind_selected_read(
    cut: &DurableCognitiveSnapshot,
    read: &ReadIdsResultV1,
    retrieval_context: Option<Digest32>,
) -> Digest32 {
    let mut bytes = CONTEXT_READ_BINDING_DOMAIN.to_vec();
    bytes.extend_from_slice(cut.cut_digest().as_array());
    bytes.extend_from_slice(read.receipt_digest().as_array());
    if let Some(context) = retrieval_context {
        bytes.extend_from_slice(context.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn read_selected_items(
    cut: &DurableCognitiveSnapshot,
    items: &[CognitiveContextItem],
) -> Result<ReadIdsResultV1, CognitiveContextError> {
    let record_ids = items
        .iter()
        .map(|item| {
            StableId::new(item.memory_id.as_str())
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
        })
        .collect::<Result<Vec<_>, _>>()?;
    cut.read_ids(ReadIdsRequestV1 {
        snapshot_digest: cut.snapshot().snapshot_digest,
        record_ids,
        fields: vec![ReadFieldV1::ContentDigest],
        maximum_encoded_bytes: MAX_CONTEXT_JSON_BYTES,
    })
    .map_err(map_read_ids_error)
}

fn map_read_ids_error(error: ReadIdsError) -> CognitiveContextError {
    let message = error.to_string();
    match error {
        ReadIdsError::Read(error) => {
            CognitiveContextError::Store(CognitiveStoreError::Corrupt(error.to_string()))
        }
        ReadIdsError::InvalidCanonicalEncoding => CognitiveContextError::Store(
            CognitiveStoreError::Corrupt("invalid canonical exact-id cognitive read".to_string()),
        ),
        ReadIdsError::TooManyRecordIds { .. }
        | ReadIdsError::DuplicateRecordId
        | ReadIdsError::DuplicateField
        | ReadIdsError::InvalidMaximumEncodedBytes { .. } => {
            CognitiveContextError::Store(CognitiveStoreError::Invalid(message))
        }
        ReadIdsError::EncodedResultTooLarge { .. } => {
            CognitiveContextError::ReadUnavailable(message)
        }
    }
}

async fn load_retrieval_context(
    current: &std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>,
    owner: &AgentId,
    body_generation: u64,
    executor: &RetrievalExecutor,
    request_work: &RetrievalRequestWork,
) -> Result<AcquiredRetrievalContext, CognitiveContextError> {
    let current = std::sync::Arc::clone(current);
    let owner = owner.clone();
    let deadline = request_work.deadline();
    let (context, lifecycle_binding, lease_expires_unix_ms) = executor
        .run(request_work, RetrievalBlockingKind::Core, move |_| {
            current.acquire_context_before(&owner, body_generation, deadline)
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    if lifecycle_binding.is_zero() {
        return Err(CognitiveContextError::RetrievalContextUnavailable);
    }
    let mut binding = b"hepta.retrieval.executor-lifecycle.v1".to_vec();
    binding.extend_from_slice(lifecycle_binding.as_array());
    binding.extend_from_slice(executor.profile_digest().as_array());
    let lifecycle_binding = Digest32::of_bytes(&binding);
    context
        .validate()
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    if lifecycle_binding.is_zero() {
        return Err(CognitiveContextError::RetrievalContextUnavailable);
    }
    if let Some(lease) = lease_expires_unix_ms {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?
            .as_millis();
        if u128::from(lease) <= now {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    Ok(AcquiredRetrievalContext {
        context,
        lifecycle_binding,
        lease_expires_unix_ms,
    })
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

//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

#[path = "cognitive_context_final_use.rs"]
mod final_use;
#[path = "cognitive_context_observation.rs"]
mod observation;
#[path = "cognitive_context_plan.rs"]
mod plan_binding;
#[path = "cognitive_read_view.rs"]
mod read_view;

use std::collections::BTreeMap;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsError;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_cognitive_read::ReadProjectionRecordV1;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::DurableCognitiveSelectionSnapshot as DurableCognitiveSnapshot;
use codex_hepta_memory::RetrievalCandidateIdentityV1;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::RevalidationStatus;
use codex_hepta_memory::execute_owner_observation;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

pub(crate) use self::final_use::revalidate_with_retrieval_context;
use self::observation::OperationObservation;
use self::observation::Phase;
use self::read_view::OwnerCutReadView;
use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextRevalidation;
use crate::CognitiveContextSnapshot;
use crate::cognitive_context_metrics;

const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;
const MAX_SELECTED_CONTEXT_RECORDS: u16 = 4;
const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";
type AdmissionKey = (String, u64, String);

fn admitted_record_index(
    records: &[ReadProjectionRecordV1],
) -> BTreeMap<AdmissionKey, &ReadProjectionRecordV1> {
    records
        .iter()
        .filter_map(|record| {
            record.content_digest.map(|digest| {
                (
                    (
                        record.record_id.as_str().to_string(),
                        record.revision.get(),
                        digest.to_string(),
                    ),
                    record,
                )
            })
        })
        .collect()
}

fn planned_context_encoded_len(
    response: &CognitiveContextSnapshot,
) -> Result<usize, CognitiveStoreError> {
    let zero = Digest32::ZERO.to_string();
    [false, true]
        .into_iter()
        .map(|read_allowed| {
            let mut candidate = response.clone();
            candidate.snapshot_digest = zero.clone();
            candidate.read_digest = zero.clone();
            candidate.plan = Some(CognitiveContextPlan {
                evaluated_context_digest: zero.clone(),
                plan_receipt_digest: zero.clone(),
                read_allowed,
            });
            serde_json::to_vec(&candidate)
                .map(|encoded| encoded.len())
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
        })
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .max()
        .ok_or_else(|| CognitiveStoreError::Invalid("missing context plan shape".to_string()))
}

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
    let mut operation = OperationObservation::start(Phase::Read);
    if query.is_empty()
        || query.len() > 2048
        || !(1..=MAX_SELECTED_CONTEXT_RECORDS).contains(&limit)
    {
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

    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new(query, now))
        .await?;
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
    let cut = store
        .lane_c_snapshot_ids(&access, &scope, now, &record_ids)
        .await?;
    let read_view = OwnerCutReadView::new(cut.owner_snapshot()).map_err(map_read_ids_error)?;
    let admission_read = read_view
        .read_ids(ReadIdsRequestV1 {
            snapshot_digest: cut.snapshot().snapshot_digest,
            record_ids,
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        })
        .map_err(map_read_ids_error)?;
    cognitive_context_metrics::record_read(
        admission_read.payload_encoded_bytes(),
        admission_read.total_encoded_bytes(),
        admission_read.missing_ids().len(),
    );
    let admission_index = admitted_record_index(admission_read.records());
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
            cut.owner_snapshot(),
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
        let admission_key = (
            binding.memory.memory_id.as_str().to_string(),
            binding.memory.revision,
            binding.content_sha256.as_str().to_string(),
        );
        let accepted = admission_index
            .get(&admission_key)
            .is_some_and(|record| record.is_live())
            && binding.scope == scope;
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
        let (ranked_items, rank_observation) = tokio::task::spawn_blocking(move || {
            let observation = ranker.rank(
                &rank_owner,
                body_generation,
                &rank_query,
                &mut admitted_items,
            )?;
            Ok::<_, String>((admitted_items, observation))
        })
        .await
        .map_err(|_| CognitiveContextError::RankerUnavailable)?
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
    let statuses = store
        .revalidate_memory_candidates(&access, &ordered_bindings, now_seconds()?)
        .await?;

    // Materialize raw text only after final ordering and revalidation. The
    // complete JSON budget is still enforced before response publication.
    for (mut item, status) in admitted_items.into_iter().zip(statuses) {
        let RevalidationStatus::Current(explanation) = status else {
            cognitive_context_metrics::record_revalidation_failure("candidate_not_current");
            continue;
        };
        let memory = explanation.memory;
        let admission_key = (
            memory.id.memory_id.as_str().to_string(),
            memory.id.revision,
            memory.content_sha256.as_str().to_string(),
        );
        let accepted = admission_index
            .get(&admission_key)
            .is_some_and(|record| record.is_live())
            && memory.scope == scope;
        if !accepted
            || item.memory_id != memory.id.memory_id.as_str()
            || item.revision != memory.id.revision
            || item.content_sha256 != memory.content_sha256.as_str()
        {
            continue;
        }
        item.content = memory.content;
        response.items.push(item);
        let encoded_bytes = planned_context_encoded_len(&response)?;
        if encoded_bytes > MAX_CONTEXT_JSON_BYTES {
            response.items.pop();
            cognitive_context_metrics::record_budget_rejection();
            continue;
        }
        if response.items.len() == usize::from(limit) {
            break;
        }
    }

    let selected_ids = response
        .items
        .iter()
        .map(|item| {
            StableId::new(item.memory_id.as_str())
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let selected_cut = cut.select_ids(&selected_ids)?;
    let selected_view =
        OwnerCutReadView::new(selected_cut.owner_snapshot()).map_err(map_read_ids_error)?;
    let selected_read = read_selected_items(&selected_view, &response.items)?;
    let selected_read_binding = bind_selected_read(
        &selected_cut,
        &selected_read,
        expected_retrieval_context_digest,
    );
    response.snapshot_digest = selected_read.snapshot_digest().to_string();
    response.read_digest = selected_read_binding.to_string();
    let fresh_plan = plan_binding::evaluate(
        owner,
        body_generation,
        &response,
        plan_binding::now_micros()?,
    )?;
    fresh_plan.ensure_current(plan_binding::now_micros()?)?;
    if !fresh_plan.plan.read_allowed {
        response.items.clear();
    }
    response.read_digest = plan_binding::bind(
        owner,
        body_generation,
        selected_read_binding,
        &fresh_plan.plan,
    )?
    .to_string();
    response.plan = Some(fresh_plan.plan.clone());
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
        // This is a write-ahead publication candidate, not a socket receipt
        // or model exposure. Actual use requires the same digest in the
        // existing native inference dispatch/started journal.
        let context_exposed = !delivered_candidates.is_empty();
        let published_context_digest = if context_exposed {
            Some(Digest32::of_bytes(&serde_json::to_vec(&response).map_err(
                |error| CognitiveStoreError::Invalid(error.to_string()),
            )?))
        } else {
            None
        };
        let sink = std::sync::Arc::clone(sink);
        let owner = owner.clone();
        tokio::task::spawn_blocking(move || {
            sink.append_preparation_with_delivery_policy(
                &owner,
                body_generation,
                request_id,
                &assignment,
                &delivered_candidates,
                context_exposed,
                published_context_digest,
                downstream_policy_digest,
                delivery_propensity,
            )
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?;
    }
    // Publication is the last memory-owner observation, after every awaited
    // ranker/retrieval/learning operation. A write-ahead learning assignment may
    // survive a rejection here; it remains preparation evidence, not delivery.
    // Do not move another await below this fence. The worker independently
    // repeats currentness at physical use; this observation is not a lease.
    store
        .revalidate_lane_c_selection(&access, &scope, &selected_cut, now_seconds()?)
        .await
        .map_err(|error| {
            cognitive_context_metrics::record_stale_cut_rejection();
            error
        })?;
    fresh_plan.ensure_current(plan_binding::now_micros()?)?;
    cognitive_context_metrics::record_selected(response.items.len());
    operation.succeed();
    Ok(response)
}

#[cfg(test)]
mod budget_tests {
    use super::*;

    #[test]
    fn planned_budget_accounts_for_the_complete_envelope() {
        let response = CognitiveContextSnapshot {
            snapshot_digest: Digest32::ZERO.to_string(),
            read_digest: Digest32::ZERO.to_string(),
            omitted_records: 0,
            items: vec![CognitiveContextItem {
                memory_id: "memory:budget".to_string(),
                revision: 1,
                content: "payload".to_string(),
                content_sha256: Digest32::of_bytes(b"payload").to_string(),
            }],
            plan: None,
        };
        let planned = planned_context_encoded_len(&response).expect("planned length");
        let zero = Digest32::ZERO.to_string();
        let actual = [false, true]
            .into_iter()
            .map(|read_allowed| {
                let mut candidate = response.clone();
                candidate.snapshot_digest = zero.clone();
                candidate.read_digest = zero.clone();
                candidate.plan = Some(CognitiveContextPlan {
                    evaluated_context_digest: zero.clone(),
                    plan_receipt_digest: zero.clone(),
                    read_allowed,
                });
                serde_json::to_vec(&candidate).expect("serialize").len()
            })
            .max()
            .expect("shape");
        assert_eq!(planned, actual);
        assert!(planned < MAX_CONTEXT_JSON_BYTES);
    }
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

/// Bind the selected exact-ID receipt to the complete durable owner cut.
///
/// The opaque product read digest additionally binds the publication plan in
/// plan_binding::bind. The core V1 read receipt and canonical bytes stay intact.
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
    cut: &OwnerCutReadView<'_>,
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
        snapshot_digest: cut.snapshot_digest(),
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
#[path = "cognitive_context_closure_tests.rs"]
mod closure_tests;
#[cfg(test)]
#[path = "cognitive_context_tests.rs"]
mod tests;

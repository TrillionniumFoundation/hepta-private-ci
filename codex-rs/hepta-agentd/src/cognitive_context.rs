//! Connect the canonical SQLite owner to the bounded memory.retrieval product path.

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
use codex_hepta_memory::RetrievalLimitObservation;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::RevalidationStatus;
use codex_hepta_memory_retrieval::MAX_PRODUCT_RETRIEVAL_RESULTS;
use codex_hepta_memory_retrieval::ProductRelationEvidenceV1;
use codex_hepta_memory_retrieval::ProductRelationKindV1;
use codex_hepta_memory_retrieval::ProductRetrievalRequestV1;
use codex_hepta_memory_retrieval::ProductRetrievalRequestV2;
use codex_hepta_memory_retrieval::RetrievalCandidate;
use codex_hepta_memory_retrieval::retrieve_product_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;

const MAX_CONTEXT_JSON_BYTES: usize = 24 * 1024;

/// Only storage failures may invalidate the canonical SQLite owner. A revoked
/// or unavailable optional learned ranker closes the ranked read, not other
/// store ports.
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
///
/// Canonical ranking precedence is:
///
/// 1. the SQLite owner enumerates bounded MemoryFts/EntityFts/GraphOneHop/
///    Recency candidates and typed registered KG relation evidence;
/// 2. the Lane-C read cut admits only exact live revision/content matches;
/// 3. memory.retrieval binds the complete admitted owner observation, typed
///    relation subset/coverage and the product 512-candidate/16-result ceiling;
/// 4. selected bindings are revalidated in one SQLite transaction;
/// 5. an explicitly configured learned ranker may reorder only that verified
///    product set before the caller's 1..=4 limit and byte budget are applied.
pub(crate) async fn read(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_after_product_rank(
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

/// Testable implementation seam between deterministic product ranking and the
/// owner revalidation transaction. Production callers always use [`read`],
/// whose hook is a no-op. Tests use this seam to prove that a correction or
/// deletion committed after ranking cannot be attached from the stale result.
async fn read_with_after_product_rank<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    after_product_rank: F,
) -> Result<CognitiveContextSnapshot, CognitiveContextError>
where
    F: FnOnce() -> Fut,
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
    let snapshot_time = now_seconds()?;
    let cut = store
        .lane_c_snapshot(&access, &scope, snapshot_time)
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

    // Observe the owner's complete bounded generator output before the legacy
    // top-four truncation. The observation digest binds owner-side channel
    // limits, typed relation provenance, scores and revalidation bindings.
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new(query, snapshot_time))
        .await?;
    let owner_observation_digest: Digest32 = observation
        .observation_sha256()
        .as_str()
        .parse()
        .map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "owner retrieval observation digest is not a Digest32: {error}"
            ))
        })?;
    let query_digest = Digest32::of_bytes(query.as_bytes());
    let query_id = StableId::new(format!("memory-query:{query_digest}"))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;

    let mut admitted = Vec::<(RetrievalCandidate, MemoryRevalidationBinding)>::new();
    for observed in observation.candidates() {
        if observed.revalidation.scope != scope {
            continue;
        }
        let Some(record) = read.records().iter().find(|record| {
            record.record_id.as_str() == observed.revalidation.memory.memory_id.as_str()
                && record.revision.get() == observed.revalidation.memory.revision
                && record.content_digest.to_string()
                    == observed.revalidation.content_sha256.as_str()
        }) else {
            continue;
        };
        let owner_score = i64::try_from(observed.reciprocal_rank_score).map_err(|_| {
            CognitiveStoreError::Corrupt("owner retrieval score exceeds i64".to_string())
        })?;
        admitted.push((
            RetrievalCandidate {
                record: record.clone(),
                snapshot_digest: read.snapshot_digest(),
                // The SQLite owner has already fused legacy channel ranks with
                // RRF. Preserve that owner score rather than inventing weights
                // for typed KG relation evidence that is not yet calibrated.
                lexical_score: FixedQ32::from_raw(owner_score),
                graph_score: FixedQ32::ZERO,
                freshness_score: FixedQ32::ZERO,
            },
            observed.revalidation.clone(),
        ));
    }

    let owner_relation_evidence_count = observation.relation_signals().len();
    let owner_relation_limit_reached = matches!(
        observation.relation_limit(),
        RetrievalLimitObservation::LimitReached
    );
    let mut relation_evidence = Vec::new();
    for (candidate_id, support_id, relation_token, support_digest, group_digest) in
        observation.relation_signals()
    {
        // Relation evidence may not widen the Lane-C admitted product set. If
        // either endpoint/support falls outside the bounded read prefix, omit
        // the typed evidence and record that omission in the Product V2 receipt.
        let Some((candidate, _)) = admitted.iter().find(|(_, binding)| {
            binding.memory.memory_id == candidate_id.memory_id
                && binding.memory.revision == candidate_id.revision
        }) else {
            continue;
        };
        let Some((support, _)) = admitted.iter().find(|(_, binding)| {
            binding.memory.memory_id == support_id.memory_id
                && binding.memory.revision == support_id.revision
        }) else {
            continue;
        };
        let relation = ProductRelationKindV1::from_owner_token(relation_token).ok_or_else(|| {
            CognitiveStoreError::Corrupt(format!(
                "owner emitted unregistered retrieval relation token {relation_token}"
            ))
        })?;
        let support_digest: Digest32 = support_digest.as_str().parse().map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "owner relation support digest is not a Digest32: {error}"
            ))
        })?;
        let relation_group_digest: Digest32 =
            group_digest.as_str().parse().map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "owner relation group digest is not a Digest32: {error}"
                ))
            })?;
        relation_evidence.push(ProductRelationEvidenceV1 {
            candidate_record_id: candidate.record.record_id.clone(),
            candidate_revision: candidate.record.revision,
            support_record_id: support.record.record_id.clone(),
            support_revision: support.record.revision,
            relation,
            support_digest,
            relation_group_digest,
        });
    }

    let product = retrieve_product_v2(ProductRetrievalRequestV2 {
        retrieval: ProductRetrievalRequestV1 {
            query_id,
            query_digest,
            snapshot_digest: read.snapshot_digest(),
            owner_observation_digest,
            maximum_results: MAX_PRODUCT_RETRIEVAL_RESULTS,
            candidates: admitted
                .iter()
                .map(|(candidate, _)| candidate.clone())
                .collect(),
        },
        owner_relation_evidence_count,
        owner_relation_limit_reached,
        relation_evidence,
    })
    .map_err(|error| {
        CognitiveStoreError::Corrupt(format!("memory.retrieval product ranking rejected: {error}"))
    })?;

    let product_results = &product.retrieval.retrieval.retrieval.results;
    let mut selected_bindings = Vec::with_capacity(product_results.len());
    for result in product_results {
        let Some((_, binding)) = admitted.iter().find(|(candidate, _)| {
            candidate.record.record_id == result.record_id
                && candidate.record.record_digest() == result.record_digest
        }) else {
            return Err(CognitiveStoreError::Corrupt(
                "memory.retrieval returned a record outside the admitted owner cut".to_string(),
            )
            .into());
        };
        selected_bindings.push(binding.clone());
    }

    // Deliberate race seam: if an owner update commits here, the batch
    // revalidation below must observe it and the final Lane-C cut revalidation
    // must fail closed instead of publishing stale ranked content.
    after_product_rank().await;

    // Revalidate the complete selected set in one owner transaction. A
    // correction, tombstone, citation drift, expiry or KG generation change
    // after ranking cannot be attached as if it were current.
    let statuses = store
        .revalidate_memory_candidates(&access, &selected_bindings, now_seconds()?)
        .await?;

    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };
    let mut admitted_items = Vec::new();
    for status in statuses {
        let RevalidationStatus::Current(explanation) = status else {
            // Fail closed for this candidate. Final Lane-C revalidation below
            // still protects the complete response from a concurrent owner cut.
            continue;
        };
        let memory = explanation.memory;
        admitted_items.push(CognitiveContextItem {
            memory_id: memory.id.memory_id.as_str().to_string(),
            revision: memory.id.revision,
            content: memory.content,
            content_sha256: memory.content_sha256.as_str().to_string(),
        });
    }

    // Learned ranking is subordinate to the owner + memory.retrieval admission
    // path. It may reorder verified items but cannot resurrect a candidate that
    // the deterministic product path omitted or rejected.
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
    // after all ranking. Oversized winners are omitted rather than truncated.
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

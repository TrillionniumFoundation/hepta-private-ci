//! Connect the canonical SQLite owner to the authoritative cognitive read port.

use std::future::Future;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::AuthoritativeReadGenerationVectorV1;
use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_read::read_authoritative;
use codex_hepta_cognitive_read::revalidate_authoritative_read;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;

const MAX_CONTEXT_JSON_BYTES: usize = 24 * 1024;
const AUTHORITATIVE_READ_LEASE_MS: u64 = 5_000;
const AUTHORITATIVE_READ_DEADLINE_MS: u64 = 10_000;
const AUTHORITATIVE_PURPOSE_ID: &str = "agentd:cognitive-context";

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

/// `body_generation` is the process launch identity. `authority_epoch` is the
/// separately fenced fleet lifecycle generation and is rebound by StateControl
/// immediately before the returned context is consumed.
pub(crate) async fn read(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    authority_epoch: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_revalidation_hook(
        store,
        owner,
        body_generation,
        authority_epoch,
        query,
        limit,
        ranker,
        || async { Ok(()) },
    )
    .await
}

/// Shared production composition used by the normal entrypoint and adversarial
/// tests. The hook runs after the authoritative result is fully computed but
/// immediately before the owner/lease/vector consume-time revalidation.
async fn read_with_revalidation_hook<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    authority_epoch: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    before_revalidation: F,
) -> Result<CognitiveContextSnapshot, CognitiveContextError>
where
    F: FnOnce() -> Fut,
    Fut: Future<Output = Result<(), CognitiveStoreError>>,
{
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    if authority_epoch == 0 {
        return Err(CognitiveStoreError::Invalid(
            "context requires a non-zero host authority epoch".to_string(),
        )
        .into());
    }

    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let acquired_at_unix_ms = now_millis()?;
    let cut = store
        .lane_c_snapshot(
            &access,
            &scope,
            millis_to_seconds(acquired_at_unix_ms)?,
        )
        .await?;

    let read_request = ReadRequestV2 {
        read_request: ReadRequest {
            snapshot_digest: cut.snapshot().snapshot_digest,
            allowed_kinds: Vec::new(),
            maximum_results: 1024,
            include_tombstones: false,
        },
        maximum_encoded_bytes: 1024 * 1024,
    };
    let consumer_profile_digest = consumer_profile_digest(
        query,
        limit,
        body_generation,
        ranker.is_some(),
        &read_request,
    );
    let purpose_id = StableId::new(AUTHORITATIVE_PURPOSE_ID)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let deadline_unix_ms = acquired_at_unix_ms
        .checked_add(AUTHORITATIVE_READ_DEADLINE_MS)
        .ok_or_else(|| CognitiveStoreError::Invalid("read deadline overflow".to_string()))?;
    let lease_expires_unix_ms = acquired_at_unix_ms
        .checked_add(AUTHORITATIVE_READ_LEASE_MS)
        .ok_or_else(|| CognitiveStoreError::Invalid("read lease overflow".to_string()))?;

    let vector = AuthoritativeReadGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: purpose_id.clone(),
        memory_ledger_frontier: cut.frontiers().memory,
        source_ledger_frontier: cut.frontiers().source,
        tombstone_frontier: cut.frontiers().tombstone,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        consumer_profile_digest,
        authority_epoch,
    };
    let acquisition = SnapshotAcquisitionRequestV1 {
        request_id: acquisition_request_id(
            owner,
            authority_epoch,
            cut.cut_digest(),
            consumer_profile_digest,
        )?,
        scope_id: cut.scope_id().clone(),
        purpose_id,
        consumer_profile_digest,
        minimum_memory_frontier: cut.frontiers().memory,
        minimum_source_frontier: cut.frontiers().source,
        minimum_tombstone_frontier: cut.frontiers().tombstone,
        minimum_knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        minimum_knowledge_graph_generation: cut.frontiers().knowledge_graph,
        authority_epoch,
        deadline_unix_ms,
    };
    let provider = cut
        .authoritative_provider(
            vector.clone(),
            &acquisition,
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        )
        .map_err(authoritative_unavailable)?;
    let original_envelope = provider.envelope().clone();
    let read = read_authoritative(
        &provider,
        acquired_at_unix_ms,
        acquisition.clone(),
        read_request,
    )
    .map_err(authoritative_unavailable)?;

    let candidates = store
        .retrieve_memory_candidates(
            &access,
            &RetrievalRequest::new(query, millis_to_seconds(now_millis()?)?),
        )
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.read_result.snapshot_digest().to_string(),
        read_digest: read.binding_digest.to_string(),
        omitted_records: read.read_result.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };

    // Admit the whole bounded owner cut before applying the response byte
    // budget. Ranking must see every admitted candidate; otherwise a large
    // low-ranked record can hide the learned winner before the ranker runs.
    let mut admitted_items = Vec::new();
    for candidate in candidates.candidates {
        let memory = candidate.memory;
        // Retrieval may use current indexes, but only the exact revision and
        // digest already admitted by the frozen authoritative owner cut can
        // cross this boundary.
        let accepted = read.read_result.records().iter().any(|record| {
            record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record.content_digest.to_string() == memory.content_sha256.as_str()
                && memory.scope == scope
        });
        if !accepted {
            continue;
        }
        admitted_items.push(CognitiveContextItem {
            memory_id: memory.id.memory_id.as_str().to_string(),
            revision: memory.id.revision,
            content: memory.content,
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
    // after ranking. Oversized winners are skipped so they cannot consume the
    // only result slot.
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
        source_snapshot_digest: read.read_result.snapshot_digest(),
        read_digest: read.binding_digest,
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

    before_revalidation().await?;

    // Reacquire the owner cut at the final consumption boundary. Exact revision
    // revalidation is only one part of this check: the original leased receipt,
    // source/tombstone/KG frontiers, generation vector, profile binding and
    // authority epoch all remain bound into the authoritative result.
    let revalidated_at_unix_ms = now_millis()?;
    let current_cut = store
        .revalidate_lane_c_snapshot(
            &access,
            &scope,
            &cut,
            millis_to_seconds(revalidated_at_unix_ms)?,
        )
        .await?;
    let current_provider = current_cut
        .authoritative_provider(
            vector,
            &acquisition,
            revalidated_at_unix_ms,
            acquisition.deadline_unix_ms,
        )
        .map_err(authoritative_unavailable)?;
    revalidate_authoritative_read(
        &read,
        &original_envelope,
        current_provider.envelope(),
        revalidated_at_unix_ms,
        &acquisition,
    )
    .map_err(authoritative_unavailable)?;

    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    Ok(response)
}

fn authoritative_unavailable(error: SnapshotProviderError) -> CognitiveStoreError {
    CognitiveStoreError::Unavailable(format!(
        "authoritative cognitive read failed closed: {error}"
    ))
}

fn consumer_profile_digest(
    query: &str,
    limit: u16,
    body_generation: u64,
    ranked: bool,
    read_request: &ReadRequestV2,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.cognitive-read-profile.v1".to_vec();
    bytes.extend_from_slice(read_request.binding_digest().as_array());
    bytes.extend_from_slice(&(query.len() as u64).to_be_bytes());
    bytes.extend_from_slice(query.as_bytes());
    bytes.extend_from_slice(&limit.to_be_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.push(u8::from(ranked));
    Digest32::of_bytes(&bytes)
}

fn acquisition_request_id(
    owner: &AgentId,
    authority_epoch: u64,
    cut_digest: Digest32,
    consumer_profile_digest: Digest32,
) -> Result<StableId, CognitiveStoreError> {
    let mut bytes = b"hepta.agentd.cognitive-read-request.v1".to_vec();
    bytes.extend_from_slice(&(owner.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&authority_epoch.to_be_bytes());
    bytes.extend_from_slice(cut_digest.as_array());
    bytes.extend_from_slice(consumer_profile_digest.as_array());
    StableId::new(format!("cognitive-read:{}", Digest32::of_bytes(&bytes)))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
}

fn now_millis() -> Result<u64, CognitiveStoreError> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
            .as_millis(),
    )
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

fn millis_to_seconds(millis: u64) -> Result<i64, CognitiveStoreError> {
    i64::try_from(millis / 1000)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

#[cfg(test)]
#[path = "cognitive_context_tests.rs"]
mod tests;

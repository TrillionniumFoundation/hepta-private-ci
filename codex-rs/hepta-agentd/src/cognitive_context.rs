//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::future::Future;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_read::read_authoritative;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::LaneCAuthorityContextV1;
use codex_hepta_memory::RetrievalRequest;
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

async fn read_with_revalidation_hook<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    authority_epoch: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    before_final_revalidation: F,
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
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let acquired_at_unix_ms = now_millis()?;
    let lease_expires_unix_ms = acquired_at_unix_ms
        .checked_add(30_000)
        .ok_or_else(|| CognitiveStoreError::Invalid("cognitive read lease overflow".to_string()))?;
    let authority_context = LaneCAuthorityContextV1 {
        purpose_id: StableId::new("agentd:cognitive-context")
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        host_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        authority_epoch,
    };
    let provider = store
        .lane_c_authoritative_provider(
            &access,
            &scope,
            authority_context.clone(),
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        )
        .await?;
    let vector = provider.envelope().generation_vector();
    let acquisition_request = SnapshotAcquisitionRequestV1 {
        request_id: cognitive_request_id(owner, query, acquired_at_unix_ms)?,
        scope_id: vector.scope_id.clone(),
        purpose_id: vector.purpose_id.clone(),
        minimum_memory_frontier: vector.memory_ledger_frontier,
        minimum_source_frontier: vector.source_ledger_frontier,
        minimum_tombstone_frontier: vector.tombstone_frontier,
        minimum_knowledge_fact_frontier: vector.knowledge_fact_frontier,
        host_generation: vector.host_generation,
        authority_epoch: vector.authority_epoch,
        deadline_unix_ms: lease_expires_unix_ms,
    };
    let authoritative_read = read_authoritative(
        &provider,
        acquired_at_unix_ms,
        acquisition_request.clone(),
        ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: provider.envelope().snapshot().snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 1024,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 1024 * 1024,
        },
    )
    .map_err(authoritative_error)?;
    let read = &authoritative_read.read_result;
    let candidates = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new(query, now_seconds()?))
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: authoritative_read.binding_digest.to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };
    // Admit the whole bounded owner cut before applying the response byte
    // budget.  Ranking must see every admitted candidate; otherwise a large
    // low-ranked record can hide the learned winner before the ranker runs.
    let mut admitted_items = Vec::new();
    for candidate in candidates.candidates {
        let memory = candidate.memory;
        // The legacy search ranks candidates; the new owner cut admits only
        // the exact verified revision and content bound by the read port.
        let accepted = read.records().iter().any(|record| {
            record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record.content_digest.to_string() == memory.content_sha256.as_str()
                && memory.scope == scope
        });
        if !accepted {
            continue;
        }
        let item = CognitiveContextItem {
            memory_id: memory.id.memory_id.as_str().to_string(),
            revision: memory.id.revision,
            content: memory.content,
            content_sha256: memory.content_sha256.as_str().to_string(),
        };
        admitted_items.push(item);
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
        read_digest: authoritative_read.binding_digest,
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
    before_final_revalidation().await?;

    // Final-use revalidation covers the exact owner cut, every owner frontier,
    // the generation-vector digest, original lease and host authority binding.
    // The lease is never extended during this check.
    let final_now_unix_ms = now_millis()?;
    let current_provider = store
        .revalidate_lane_c_authoritative_provider(
            &access,
            &scope,
            &provider,
            authority_context,
            final_now_unix_ms,
        )
        .await?;
    authoritative_read
        .revalidate_for_current_snapshot(
            final_now_unix_ms,
            &acquisition_request,
            current_provider.envelope(),
        )
        .map_err(authoritative_error)?;
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    Ok(response)
}

fn cognitive_request_id(
    owner: &AgentId,
    query: &str,
    acquired_at_unix_ms: u64,
) -> Result<StableId, CognitiveStoreError> {
    let mut bytes = b"hepta.agentd.cognitive-context-request.v1".to_vec();
    bytes.extend_from_slice(&(owner.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&(query.len() as u64).to_be_bytes());
    bytes.extend_from_slice(query.as_bytes());
    bytes.extend_from_slice(&acquired_at_unix_ms.to_be_bytes());
    StableId::new(format!("context-{}", Digest32::of_bytes(&bytes)))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
}

fn authoritative_error(error: SnapshotProviderError) -> CognitiveStoreError {
    match error {
        SnapshotProviderError::InvalidRequest(_) | SnapshotProviderError::InvalidLeaseWindow => {
            CognitiveStoreError::Invalid(error.to_string())
        }
        SnapshotProviderError::Unavailable => CognitiveStoreError::Unavailable(error.to_string()),
        SnapshotProviderError::Read(_)
        | SnapshotProviderError::SnapshotIntegrity
        | SnapshotProviderError::GenerationVectorDigestMismatch
        | SnapshotProviderError::ReceiptDigestMismatch
        | SnapshotProviderError::AuthorityGranted
        | SnapshotProviderError::EmptyDigest
        | SnapshotProviderError::Indeterminate => CognitiveStoreError::Corrupt(error.to_string()),
        _ => CognitiveStoreError::Conflict(error.to_string()),
    }
}

fn now_millis() -> Result<u64, CognitiveStoreError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_millis();
    u64::try_from(millis).map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
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

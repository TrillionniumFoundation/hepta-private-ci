//! Connect the canonical SQLite owner to the authoritative bounded cognitive read port.

use std::sync::Arc;
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
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;
use crate::CognitiveReadAuthoritySnapshotV1;
use crate::CurrentCognitiveReadAuthority;

const MAX_CONTEXT_JSON_BYTES: usize = 24 * 1024;
const COGNITIVE_CONTEXT_PURPOSE: &str = "agentd:cognitive-context:read-v1";

/// Only storage failures may invalidate the canonical SQLite owner. Revoked,
/// unavailable, stale or indeterminate host authority closes this read only.
#[derive(Debug)]
pub(crate) enum CognitiveContextError {
    Store(CognitiveStoreError),
    Authority(SnapshotProviderError),
    RankerUnavailable,
}

impl From<CognitiveStoreError> for CognitiveContextError {
    fn from(error: CognitiveStoreError) -> Self {
        Self::Store(error)
    }
}

impl From<SnapshotProviderError> for CognitiveContextError {
    fn from(error: SnapshotProviderError) -> Self {
        Self::Authority(error)
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
    authority: Option<&Arc<dyn CurrentCognitiveReadAuthority>>,
    ranker: Option<&Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    let authority = authority.ok_or(CognitiveContextError::Authority(
        SnapshotProviderError::Unavailable,
    ))?;
    let acquired_at_unix_ms = now_millis()?;
    let acquired_at_unix_seconds = seconds_from_millis(acquired_at_unix_ms)?;
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, acquired_at_unix_seconds)
        .await?;
    let authority_snapshot = current_authority(authority, owner, body_generation).await?;
    let purpose_id = StableId::new(COGNITIVE_CONTEXT_PURPOSE)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let vector = authority_snapshot.bind_lane_c(&cut, purpose_id.clone())?;
    let lease_expires_unix_ms = acquired_at_unix_ms
        .checked_add(authority_snapshot.maximum_lease_ms)
        .ok_or(SnapshotProviderError::InvalidLeaseWindow)?;
    let provider = cut.authoritative_provider(
        vector,
        acquired_at_unix_ms,
        lease_expires_unix_ms,
    )?;
    let acquisition_request = SnapshotAcquisitionRequestV1 {
        request_id: cognitive_request_id(
            owner,
            body_generation,
            query,
            acquired_at_unix_ms,
            cut.snapshot().snapshot_digest,
        )?,
        scope_id: cut.scope_id().clone(),
        purpose_id: purpose_id.clone(),
        minimum_memory_frontier: cut.frontiers().memory,
        minimum_tombstone_frontier: cut.frontiers().tombstone,
        authority_epoch: authority_snapshot.authority_epoch,
        deadline_unix_ms: lease_expires_unix_ms,
    };
    let authoritative = read_authoritative(
        &provider,
        acquired_at_unix_ms,
        acquisition_request.clone(),
        ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: cut.snapshot().snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 1024,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 1024 * 1024,
        },
    )?;
    let read = &authoritative.read_result;

    let candidates = store
        .retrieve_memory_candidates(
            &access,
            &RetrievalRequest::new(query, acquired_at_unix_seconds),
        )
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: authoritative.source_snapshot_digest.to_string(),
        read_digest: authoritative.binding_digest.to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };
    // Admit the whole bounded owner cut before applying the response byte
    // budget. Ranking must see every admitted candidate; otherwise a large
    // low-ranked record can hide the learned winner before the ranker runs.
    let mut admitted_items = Vec::new();
    for candidate in candidates.candidates {
        let memory = candidate.memory;
        // Legacy retrieval ranks candidates; authoritative read admits only the
        // exact verified revision/content bound to this immutable owner cut.
        let accepted = read.records().iter().any(|record| {
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
        let ranker = Arc::clone(ranker);
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
    let now_micros = now_micros()?;
    let authority_expiry_micros = authoritative
        .lease_expires_unix_ms
        .checked_mul(1_000)
        .ok_or(SnapshotProviderError::InvalidLeaseWindow)?;
    let plan_expires_at_micros = now_micros
        .checked_add(1_000_000)
        .ok_or_else(|| {
            CognitiveStoreError::Invalid("context plan expiry overflow".to_string())
        })?
        .min(authority_expiry_micros);
    if plan_expires_at_micros <= now_micros {
        return Err(SnapshotProviderError::LeaseExpired.into());
    }
    let plan = plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: authoritative.source_snapshot_digest,
        read_digest: authoritative.binding_digest,
        verified_item_count: response.items.len() as u32,
        encoded_context: &encoded_context,
        maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
        observed_at_micros: now_micros,
        expires_at_micros: plan_expires_at_micros,
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

    // Final-use validation is deliberately optimistic and fail-closed. Reacquire
    // the canonical SQLite cut, then reacquire every external owner pin. The
    // completed authoritative read must still match the same full vector and
    // must still be inside its original lease before context leaves agentd.
    let consume_at_unix_ms = now_millis()?;
    let current_cut = store
        .revalidate_lane_c_snapshot(
            &access,
            &scope,
            &cut,
            seconds_from_millis(consume_at_unix_ms)?,
        )
        .await?;
    let current_authority = current_authority(authority, owner, body_generation).await?;
    let current_vector = current_authority.bind_lane_c(&current_cut, purpose_id)?;
    let current_lease_expires_unix_ms = consume_at_unix_ms
        .checked_add(current_authority.maximum_lease_ms)
        .ok_or(SnapshotProviderError::InvalidLeaseWindow)?;
    let current_provider = current_cut.authoritative_provider(
        current_vector,
        consume_at_unix_ms,
        current_lease_expires_unix_ms,
    )?;
    authoritative.validate_for_consumption(
        consume_at_unix_ms,
        &acquisition_request,
        current_provider.envelope(),
    )?;

    if let Some(ranker) = ranker {
        let ranker = Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    Ok(response)
}

async fn current_authority(
    authority: &Arc<dyn CurrentCognitiveReadAuthority>,
    owner: &AgentId,
    body_generation: u64,
) -> Result<CognitiveReadAuthoritySnapshotV1, CognitiveContextError> {
    let authority = Arc::clone(authority);
    let owner = owner.clone();
    tokio::task::spawn_blocking(move || authority.current(&owner, body_generation))
        .await
        .map_err(|_| CognitiveContextError::Authority(SnapshotProviderError::Indeterminate))?
        .map_err(CognitiveContextError::Authority)
}

fn cognitive_request_id(
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    acquired_at_unix_ms: u64,
    snapshot_digest: Digest32,
) -> Result<StableId, CognitiveStoreError> {
    let mut bytes = b"hepta.agentd.cognitive-context-request.v1".to_vec();
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.extend_from_slice(query.as_bytes());
    bytes.extend_from_slice(&acquired_at_unix_ms.to_be_bytes());
    bytes.extend_from_slice(snapshot_digest.as_array());
    StableId::new(format!("context-read-{}", Digest32::of_bytes(&bytes)))
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

fn now_micros() -> Result<u64, CognitiveStoreError> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
            .as_micros(),
    )
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

fn seconds_from_millis(value: u64) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value / 1_000)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

#[cfg(test)]
#[path = "cognitive_context_tests.rs"]
mod tests;

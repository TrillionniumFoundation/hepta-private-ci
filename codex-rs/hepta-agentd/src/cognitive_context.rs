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
use codex_hepta_memory::LaneCAuthoritativeHostContextV1;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;

const MAX_CONTEXT_JSON_BYTES: usize = 24 * 1024;
const AUTHORITATIVE_READ_LEASE_MS: u64 = 30_000;
const COGNITIVE_READ_PURPOSE: &str = "agentd-cognitive-context";

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

/// `body_generation` is the process launch identity. `authority_epoch` is
/// the separately fenced fleet lifecycle generation and must be rechecked by
/// the caller immediately before response publication.
pub(crate) async fn read(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    authority_epoch: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_final_use_hook(
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

async fn read_with_final_use_hook<F, Fut>(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    authority_epoch: u64,
    query: &str,
    limit: u16,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    final_use_hook: F,
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
    let host_context = authoritative_host_context(authority_epoch, ranker)?;
    let provider = store
        .authoritative_lane_c_snapshot_provider(
            &access,
            &scope,
            host_context.clone(),
            acquired_at_unix_ms,
            AUTHORITATIVE_READ_LEASE_MS,
        )
        .await?;
    let envelope = provider.envelope();
    let vector = &envelope.snapshot_key().vector;
    let acquisition = SnapshotAcquisitionRequestV1 {
        request_id: authoritative_request_id(
            owner,
            body_generation,
            authority_epoch,
            query,
            acquired_at_unix_ms,
        )?,
        scope_id: vector.scope_id.clone(),
        purpose_id: vector.purpose_id.clone(),
        minimum_memory_frontier: vector.memory_ledger_frontier,
        minimum_tombstone_frontier: vector.tombstone_frontier,
        authority_epoch,
        deadline_unix_ms: envelope.lease_expires_unix_ms(),
    };
    let read = read_authoritative(
        &provider,
        acquired_at_unix_ms,
        acquisition.clone(),
        ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: envelope.snapshot().snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 1024,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 1024 * 1024,
        },
    )
    .map_err(authoritative_read_error)?;
    let bounded_read = &read.read_result;
    let candidates = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new(query, now_seconds()?))
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: bounded_read.snapshot_digest().to_string(),
        read_digest: read.binding_digest.to_string(),
        omitted_records: bounded_read.omitted_count() as u64,
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
        let accepted = bounded_read.records().iter().any(|record| {
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
        source_snapshot_digest: bounded_read.snapshot_digest(),
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
    // Test/qualification hooks execute at the real product race boundary:
    // after the response has been built but before any final-use authority
    // checks. Production passes a no-op hook.
    final_use_hook().await?;
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    // Rebuild the host-owned vector after all optional ranker I/O, then ask the
    // canonical SQLite owner to revalidate the immutable cut, lease, receipt,
    // frontiers and full generation vector before this context can be consumed.
    let current_host_context = authoritative_host_context(authority_epoch, ranker)?;
    store
        .revalidate_authoritative_lane_c_snapshot(
            &access,
            &scope,
            &provider,
            &acquisition,
            &current_host_context,
            &read,
            now_millis()?,
        )
        .await?;
    Ok(response)
}

fn authoritative_host_context(
    authority_epoch: u64,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<LaneCAuthoritativeHostContextV1, CognitiveStoreError> {
    if authority_epoch == 0 {
        return Err(CognitiveStoreError::Invalid(
            "cognitive read authority epoch must be non-zero".to_string(),
        ));
    }
    // This product path does not consume compact checkpoints or prompt-registry
    // records. Their vector slots therefore use explicit fixed not-consumed
    // sentinels rather than pretending to observe those owners. The fields
    // actually consumed by this path are bound to stable profile identities.
    let not_consumed_generation = Generation::new(1)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let not_consumed_revision = Revision::new(1)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let model_digest = ranker.map_or_else(
        || Digest32::of_bytes(b"hepta.agentd.cognitive-context.no-ranker.v1"),
        |ranker| ranker.model_digest(),
    );
    Ok(LaneCAuthoritativeHostContextV1 {
        purpose_id: StableId::new(COGNITIVE_READ_PURPOSE)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        compact_checkpoint_generation: not_consumed_generation,
        prompt_registry_revision: not_consumed_revision,
        retrieval_profile_digest: Digest32::of_bytes(
            b"hepta.agentd.cognitive-context.sqlite-retrieval.v1",
        ),
        encoder_preprocessor_digest: Digest32::of_bytes(
            b"hepta.agentd.cognitive-context.utf8-query.v1",
        ),
        authority_epoch,
        model_digest,
        tokenizer_digest: Digest32::of_bytes(
            b"hepta.agentd.cognitive-context.no-tokenizer.v1",
        ),
        template_digest: Digest32::of_bytes(
            b"hepta.agentd.cognitive-context.json-envelope.v1",
        ),
        tool_schema_digest: Digest32::of_bytes(
            b"hepta.agentd.control.cognitive-context.v1",
        ),
    })
}

fn authoritative_request_id(
    owner: &AgentId,
    body_generation: u64,
    authority_epoch: u64,
    query: &str,
    acquired_at_unix_ms: u64,
) -> Result<StableId, CognitiveStoreError> {
    let mut bytes = b"hepta.agentd.cognitive-context.request.v1".to_vec();
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.extend_from_slice(&authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&acquired_at_unix_ms.to_be_bytes());
    bytes.extend_from_slice(query.as_bytes());
    StableId::new(format!("cognitive-read-{}", Digest32::of_bytes(&bytes)))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
}

fn authoritative_read_error(error: SnapshotProviderError) -> CognitiveStoreError {
    CognitiveStoreError::Conflict(format!("authoritative cognitive read rejected: {error}"))
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

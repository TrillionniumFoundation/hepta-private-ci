//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::read_authoritative;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::DurableCognitiveSnapshot;
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
const COGNITIVE_CONTEXT_PURPOSE: &str = "agentd-cognitive-context-owner-local-v1";
const OWNER_LOCAL_UNBOUND_PROFILE: &[u8] =
    b"hepta.agentd.cognitive-context.owner-local-unbound.v1";

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
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    if authority_epoch == 0 {
        return Err(CognitiveStoreError::Invalid(
            "cognitive authoritative read requires a non-zero host authority epoch".to_string(),
        )
        .into());
    }
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let acquired_at_unix_ms = now_millis()?;
    let acquired_at_unix_seconds = millis_to_seconds(acquired_at_unix_ms)?;
    let cut = store
        .lane_c_snapshot(&access, &scope, acquired_at_unix_seconds)
        .await?;
    let vector = owner_local_generation_vector(&cut, authority_epoch, query, limit, ranker.is_some())?;
    let lease_expires_unix_ms = acquired_at_unix_ms
        .checked_add(AUTHORITATIVE_READ_LEASE_MS)
        .ok_or_else(|| CognitiveStoreError::Invalid("cognitive read lease overflow".to_string()))?;
    let provider = cut
        .authoritative_provider(vector, acquired_at_unix_ms, lease_expires_unix_ms)
        .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    let acquisition_request = SnapshotAcquisitionRequestV1 {
        request_id: authoritative_request_id(
            owner,
            authority_epoch,
            query,
            limit,
            cut.snapshot().snapshot_digest,
        )?,
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new(COGNITIVE_CONTEXT_PURPOSE)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        minimum_memory_frontier: cut.frontiers().memory,
        minimum_tombstone_frontier: cut.frontiers().tombstone,
        authority_epoch,
        deadline_unix_ms: lease_expires_unix_ms,
    };
    let authoritative_read = read_authoritative(
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
    )
    .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    let read = authoritative_read.read_result;
    let candidates = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new(query, now_seconds()?))
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
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
        .revalidate_lane_c_authoritative_snapshot(
            &access,
            &scope,
            provider.envelope(),
            &acquisition_request,
            now_millis()?,
        )
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

fn owner_local_generation_vector(
    cut: &DurableCognitiveSnapshot,
    authority_epoch: u64,
    query: &str,
    limit: u16,
    ranker_present: bool,
) -> Result<LaneCGenerationVectorV1, CognitiveStoreError> {
    // This product path consumes the canonical Lane-C owner cut plus an optional
    // separately revalidated ranker. Model/tokenizer/template/tool bindings are
    // intentionally outside this read boundary, so those dimensions use one
    // explicit domain-separated sentinel rather than pretending to be live host
    // generations. The purpose ID makes this a documented owner-local subset.
    let unbound = Digest32::of_bytes(OWNER_LOCAL_UNBOUND_PROFILE);
    let mut retrieval_profile = b"hepta.agentd.cognitive-context.retrieval-profile.v1".to_vec();
    retrieval_profile.extend_from_slice(&(query.len() as u64).to_be_bytes());
    retrieval_profile.extend_from_slice(query.as_bytes());
    retrieval_profile.extend_from_slice(&limit.to_be_bytes());
    retrieval_profile.push(u8::from(ranker_present));
    Ok(LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new(COGNITIVE_CONTEXT_PURPOSE)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        prompt_registry_revision: Revision::new(1)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        retrieval_profile_digest: Digest32::of_bytes(&retrieval_profile),
        encoder_preprocessor_digest: Digest32::of_bytes(
            b"hepta.agentd.cognitive-context.query-encoder.v1",
        ),
        authority_epoch,
        model_digest: unbound,
        tokenizer_digest: unbound,
        template_digest: unbound,
        tool_schema_digest: unbound,
    })
}

fn authoritative_request_id(
    owner: &AgentId,
    authority_epoch: u64,
    query: &str,
    limit: u16,
    snapshot_digest: Digest32,
) -> Result<StableId, CognitiveStoreError> {
    let mut bytes = b"hepta.agentd.cognitive-context.authoritative-request.v1".to_vec();
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&(query.len() as u64).to_be_bytes());
    bytes.extend_from_slice(query.as_bytes());
    bytes.extend_from_slice(&limit.to_be_bytes());
    bytes.extend_from_slice(snapshot_digest.as_array());
    StableId::new(format!("cognitive-context-{}", Digest32::of_bytes(&bytes)))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
}

fn now_millis() -> Result<u64, CognitiveStoreError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_millis();
    u64::try_from(millis).map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

fn millis_to_seconds(millis: u64) -> Result<i64, CognitiveStoreError> {
    i64::try_from(millis / 1000)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

fn now_seconds() -> Result<i64, CognitiveStoreError> {
    millis_to_seconds(now_millis()?)
}

#[cfg(test)]
#[path = "cognitive_context_tests.rs"]
mod tests;

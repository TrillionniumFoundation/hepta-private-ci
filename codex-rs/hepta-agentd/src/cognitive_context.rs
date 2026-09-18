//! Connect the canonical SQLite owner to the authoritative bounded cognitive read port.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::AuthoritativeCognitiveSnapshotProvider;
use codex_hepta_cognitive_read::AuthoritativeReadRequestV1;
use codex_hepta_cognitive_read::AuthoritativeSnapshotV1;
use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
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
const MAX_AUTHORITATIVE_CONTEXT_LIFETIME_MS: u64 = 1_000;
const CONTEXT_PURPOSE: &str = "purpose:cognitive-context";

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

/// One production provider value owns one SQLite transaction cut plus the host
/// identities frozen for that read. It has no writer or ambient authority.
#[derive(Clone)]
struct AgentdAuthoritativeSnapshotProvider {
    cut: DurableCognitiveSnapshot,
    vector: LaneCGenerationVectorV1,
    acquired_at_unix_ms: u64,
}

impl AuthoritativeCognitiveSnapshotProvider for AgentdAuthoritativeSnapshotProvider {
    fn acquire(
        &self,
        request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError> {
        let lease_ceiling = self
            .acquired_at_unix_ms
            .checked_add(MAX_AUTHORITATIVE_CONTEXT_LIFETIME_MS)
            .ok_or(SnapshotProviderError::InvalidLeaseWindow)?;
        let lease_expires_unix_ms = lease_ceiling.min(request.deadline_unix_ms);
        if lease_expires_unix_ms <= self.acquired_at_unix_ms {
            return Err(SnapshotProviderError::DeadlineExpired);
        }
        self.cut.bind_context(
            self.vector.clone(),
            self.acquired_at_unix_ms,
            lease_expires_unix_ms,
        )
    }
}

/// The caller admits this method only while the Agent is Running and ready and
/// passes the exact fleet lifecycle generation observed by `refresh_generation`.
/// State control rechecks the same epoch after this async call before delivery.
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
            "cognitive authority epoch must be non-zero".to_string(),
        )
        .into());
    }
    if let Some(ranker) = ranker {
        ranker
            .require_identity(owner, body_generation)
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }

    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let acquired_at_unix_ms = now_millis()?;
    let cut = store
        .lane_c_snapshot(
            &access,
            &scope,
            seconds_from_millis(acquired_at_unix_ms)?,
        )
        .await?;
    let provider = authoritative_provider(&cut, authority_epoch, ranker, acquired_at_unix_ms)?;
    let deadline_unix_ms = acquired_at_unix_ms
        .checked_add(MAX_AUTHORITATIVE_CONTEXT_LIFETIME_MS)
        .ok_or_else(|| CognitiveStoreError::Invalid("context deadline overflow".to_string()))?;
    let acquisition_request = SnapshotAcquisitionRequestV1 {
        request_id: context_request_id(
            owner,
            body_generation,
            authority_epoch,
            query,
            acquired_at_unix_ms,
        )?,
        scope_id: cut.scope_id().clone(),
        purpose_id: context_purpose_id()?,
        minimum_memory_frontier: cut.frontiers().memory,
        minimum_tombstone_frontier: cut.frontiers().tombstone,
        authority_epoch,
        deadline_unix_ms,
    };
    let guarded = read_authoritative(
        &provider,
        acquired_at_unix_ms,
        acquisition_request,
        AuthoritativeReadRequestV1 {
            allowed_kinds: Vec::new(),
            maximum_results: 1024,
            include_tombstones: false,
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        },
    )
    .map_err(snapshot_provider_error)?;
    let bounded_read = guarded.read_result();
    let candidates = store
        .retrieve_memory_candidates(
            &access,
            &RetrievalRequest::new(query, now_seconds()?),
        )
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: bounded_read.snapshot_digest().to_string(),
        read_digest: guarded.result().binding_digest().to_string(),
        omitted_records: bounded_read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };

    // Admit the whole bounded owner cut before applying the response byte
    // budget. Ranking must see every admitted candidate; otherwise a large
    // low-ranked record can hide the learned winner before the ranker runs.
    let mut admitted_items = Vec::new();
    for candidate in candidates.candidates {
        let memory = candidate.memory;
        // Retrieval ranks content; only the exact authoritative revision and
        // content bound into this read guard may enter downstream context.
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
    // after ranking. This preserves the highest-ranked item when the legacy
    // byte cut would otherwise discard it. Oversized winners are skipped so
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
    let now_micros = now_micros()?;
    let plan = plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: bounded_read.snapshot_digest(),
        read_digest: guarded.result().binding_digest(),
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

    // Final-use fence: reacquire a new single-transaction SQLite cut, rebuild
    // the same host vector, and require provider/vector/snapshot/lease equality.
    // The outer Agentd caller independently refreshes the Running lifecycle
    // generation after this async boundary returns.
    let final_now_unix_ms = now_millis()?;
    let current_cut = store
        .lane_c_snapshot(
            &access,
            &scope,
            seconds_from_millis(final_now_unix_ms)?,
        )
        .await?;
    let current_provider =
        authoritative_provider(&current_cut, authority_epoch, ranker, final_now_unix_ms)?;
    guarded
        .revalidate(&current_provider, final_now_unix_ms)
        .map_err(snapshot_provider_error)?;

    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    Ok(response)
}

fn authoritative_provider(
    cut: &DurableCognitiveSnapshot,
    authority_epoch: u64,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    acquired_at_unix_ms: u64,
) -> Result<AgentdAuthoritativeSnapshotProvider, CognitiveStoreError> {
    Ok(AgentdAuthoritativeSnapshotProvider {
        cut: cut.clone(),
        vector: context_generation_vector(cut, authority_epoch, ranker)?,
        acquired_at_unix_ms,
    })
}

fn context_generation_vector(
    cut: &DurableCognitiveSnapshot,
    authority_epoch: u64,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<LaneCGenerationVectorV1, CognitiveStoreError> {
    if authority_epoch == 0 {
        return Err(CognitiveStoreError::Invalid(
            "zero cognitive authority epoch".to_string(),
        ));
    }
    // This product path does not consume compact/prompt/tokenizer/template/tool
    // generations. Their identities are explicitly frozen to domain-separated
    // "not used by this path" values instead of borrowing mutable ambient state.
    let not_used_generation = Generation::new(1)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let not_used_revision = Revision::new(1)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let not_used_digest = Digest32::of_bytes(b"hepta.agentd.cognitive-context.not-used.v1");
    let model_digest = ranker.map_or_else(
        || Digest32::of_bytes(b"hepta.agentd.cognitive-context.ranker.none.v1"),
        |value| value.model_digest(),
    );
    Ok(LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: context_purpose_id()?,
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: not_used_generation,
        prompt_registry_revision: not_used_revision,
        retrieval_profile_digest: Digest32::of_bytes(
            b"hepta.agentd.cognitive-context.retrieval-profile.v2",
        ),
        encoder_preprocessor_digest: Digest32::of_bytes(
            b"hepta.agentd.cognitive-context.query-encoder.v1",
        ),
        authority_epoch,
        model_digest,
        tokenizer_digest: not_used_digest,
        template_digest: not_used_digest,
        tool_schema_digest: not_used_digest,
    })
}

fn context_purpose_id() -> Result<StableId, CognitiveStoreError> {
    StableId::new(CONTEXT_PURPOSE)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
}

fn context_request_id(
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
    StableId::new(format!("context-read-{}", Digest32::of_bytes(&bytes)))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
}

fn snapshot_provider_error(error: SnapshotProviderError) -> CognitiveStoreError {
    match error {
        SnapshotProviderError::DeadlineExpired
        | SnapshotProviderError::LeaseExpired
        | SnapshotProviderError::AcquiredInFuture
        | SnapshotProviderError::ScopeMismatch
        | SnapshotProviderError::PurposeMismatch
        | SnapshotProviderError::AuthorityEpochMismatch
        | SnapshotProviderError::StaleMemoryFrontier
        | SnapshotProviderError::StaleTombstoneFrontier
        | SnapshotProviderError::ProviderMismatch
        | SnapshotProviderError::Revoked
        | SnapshotProviderError::GenerationGone => CognitiveStoreError::Conflict(format!(
            "authoritative cognitive snapshot is no longer current: {error}"
        )),
        SnapshotProviderError::Unavailable | SnapshotProviderError::Indeterminate => {
            CognitiveStoreError::Unavailable(format!(
                "authoritative cognitive snapshot unavailable: {error}"
            ))
        }
        SnapshotProviderError::InvalidRequest(_) | SnapshotProviderError::InvalidLeaseWindow => {
            CognitiveStoreError::Invalid(format!(
                "invalid authoritative cognitive read request: {error}"
            ))
        }
        SnapshotProviderError::Contract(_)
        | SnapshotProviderError::Read(_)
        | SnapshotProviderError::SnapshotIntegrity
        | SnapshotProviderError::ReadSnapshotMismatch
        | SnapshotProviderError::ReceiptDigestMismatch
        | SnapshotProviderError::AuthorityGranted
        | SnapshotProviderError::EmptyDigest => CognitiveStoreError::Corrupt(format!(
            "invalid authoritative cognitive snapshot: {error}"
        )),
    }
}

fn now_millis() -> Result<u64, CognitiveStoreError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_millis();
    u64::try_from(millis).map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

fn now_micros() -> Result<u64, CognitiveStoreError> {
    let micros = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_micros();
    u64::try_from(micros).map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

fn seconds_from_millis(value: u64) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value / 1000)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

fn now_seconds() -> Result<i64, CognitiveStoreError> {
    seconds_from_millis(now_millis()?)
}

#[cfg(test)]
#[path = "cognitive_context_tests.rs"]
mod tests;

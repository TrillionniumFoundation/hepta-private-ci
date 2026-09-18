//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::AuthoritativeCognitiveSnapshotProvider;
use codex_hepta_cognitive_read::AuthoritativeSnapshotV1;
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
use codex_hepta_memory_retrieval::RecallDispositionV1;
use codex_hepta_memory_retrieval::build_candidate_union_from_batches;
use codex_hepta_memory_retrieval::compile_cue;
use codex_hepta_memory_retrieval::recall_with_engram;
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
    RetrievalUnavailable,
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
    read_inner(
        store,
        owner,
        body_generation,
        query,
        limit,
        None,
        ranker,
    )
    .await
}

pub(crate) async fn read_with_runtime(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    retrieval_runtime: Option<&std::sync::Arc<crate::PinnedMemoryRetrievalRuntime>>,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_inner(
        store,
        owner,
        body_generation,
        query,
        limit,
        retrieval_runtime,
        ranker,
    )
    .await
}

async fn read_inner(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    retrieval_runtime: Option<&std::sync::Arc<crate::PinnedMemoryRetrievalRuntime>>,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let observed_seconds = now_seconds()?;
    let cut = store
        .lane_c_snapshot(&access, &scope, observed_seconds)
        .await?;
    let read_request = || ReadRequestV2 {
        read_request: ReadRequest {
            snapshot_digest: cut.snapshot().snapshot_digest,
            allowed_kinds: Vec::new(),
            maximum_results: 1024,
            include_tombstones: false,
        },
        maximum_encoded_bytes: 1024 * 1024,
    };
    let read = cut
        .read(read_request())
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let retrieval = store
        .observe_memory_retrieval(
            &access,
            &RetrievalRequest::new(query, observed_seconds),
        )
        .await?;

    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
        plan: None,
    };
    let mut admitted_items = Vec::new();
    for candidate in retrieval.materialized_candidates() {
        let memory = &candidate.memory;
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
            content: memory.content.clone(),
            content_sha256: memory.content_sha256.as_str().to_string(),
        });
    }

    let mut prepared_runtime = None;
    if let Some(runtime) = retrieval_runtime {
        let runtime = std::sync::Arc::clone(runtime);
        let rank_owner = owner.clone();
        let rank_query = query.to_string();
        let cut_for_prepare = cut.clone();
        let retrieval_for_prepare = retrieval.clone();
        let prepared = tokio::task::spawn_blocking(move || {
            runtime.prepare(
                &rank_owner,
                body_generation,
                &rank_query,
                &cut_for_prepare,
                &retrieval_for_prepare,
            )
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;

        let acquired_at_unix_ms = u64::try_from(observed_seconds)
            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
            .checked_mul(1000)
            .ok_or_else(|| {
                CognitiveStoreError::Unavailable(
                    "retrieval snapshot acquisition time overflow".to_string(),
                )
            })?;
        let lease_expires_unix_ms = acquired_at_unix_ms
            .checked_add(5_000)
            .ok_or_else(|| {
                CognitiveStoreError::Unavailable(
                    "retrieval snapshot lease overflow".to_string(),
                )
            })?;
        let envelope = cut
            .bind_context(
                prepared.profile.vector.clone(),
                acquired_at_unix_ms,
                lease_expires_unix_ms,
            )
            .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;
        let snapshot_key = envelope.snapshot_key().clone();
        let provider = BoundSnapshotProvider(envelope);
        let request_id = StableId::new(format!(
            "retrieval-read-{}",
            Digest32::of_bytes(query.as_bytes())
        ))
        .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;
        let authoritative_read = read_authoritative(
            &provider,
            acquired_at_unix_ms,
            SnapshotAcquisitionRequestV1 {
                request_id,
                scope_id: prepared.profile.vector.scope_id.clone(),
                purpose_id: prepared.profile.vector.purpose_id.clone(),
                minimum_memory_frontier: prepared.profile.vector.memory_ledger_frontier,
                minimum_tombstone_frontier: prepared.profile.vector.tombstone_frontier,
                authority_epoch: prepared.profile.vector.authority_epoch,
                deadline_unix_ms: acquired_at_unix_ms
                    .checked_add(4_000)
                    .ok_or(CognitiveContextError::RetrievalUnavailable)?,
            },
            read_request(),
        )
        .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;
        let cue = compile_cue(
            prepared.profile.cue_id.clone(),
            prepared.profile.objective_digest,
            prepared.profile.approved_context_digest,
            snapshot_key,
            prepared.profile.cue_profile_digest,
        )
        .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;
        let batches = crate::owner_retrieval_adapter::adapt_owner_retrieval(
            &cue,
            &prepared.profile.policy,
            &authoritative_read,
            &retrieval,
        )
        .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;
        let built = build_candidate_union_from_batches(
            &cue,
            &prepared.profile.policy,
            batches.clone(),
        )
        .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;

        if built.all_enabled_channels_exhausted {
            let candidates = batches
                .into_iter()
                .flat_map(|batch| batch.candidates)
                .collect();
            let receipt = recall_with_engram(
                &cue,
                &prepared.profile.policy,
                candidates,
                &prepared.profile.engram,
                &prepared.profile.dynamics,
            )
            .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;
            match receipt.packet.disposition {
                RecallDispositionV1::Recalled => {
                    let mut by_identity = admitted_items
                        .into_iter()
                        .map(|item| ((item.memory_id.clone(), item.revision), item))
                        .collect::<std::collections::BTreeMap<_, _>>();
                    let mut selected = Vec::with_capacity(receipt.packet.selections.len());
                    for selection in receipt.packet.selections {
                        let key = (
                            selection.record_id.as_str().to_string(),
                            selection.record_revision.get(),
                        );
                        let Some(item) = by_identity.remove(&key) else {
                            return Err(CognitiveContextError::RetrievalUnavailable);
                        };
                        if Digest32::of_bytes(item.content.as_bytes()) != selection.record_digest
                            && item.content_sha256 != selection.record_digest.to_string()
                        {
                            return Err(CognitiveContextError::RetrievalUnavailable);
                        }
                        selected.push(item);
                    }
                    admitted_items = selected;
                }
                RecallDispositionV1::Abstained(_) => admitted_items.clear(),
            }
        } else {
            // Partial channel coverage is not negative evidence. The composed
            // HNMF path abstains instead of treating a bounded prefix as complete.
            admitted_items.clear();
        }
        prepared_runtime = Some(prepared);
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

    store
        .revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)
        .await?;
    if let (Some(runtime), Some(prepared)) = (retrieval_runtime, prepared_runtime.as_ref()) {
        let runtime = std::sync::Arc::clone(runtime);
        let prepared = prepared.clone();
        tokio::task::spawn_blocking(move || runtime.revalidate(&prepared))
            .await
            .map_err(|_| CognitiveContextError::RetrievalUnavailable)?
            .map_err(|_| CognitiveContextError::RetrievalUnavailable)?;
    }
    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    Ok(response)
}

#[derive(Clone)]
struct BoundSnapshotProvider(AuthoritativeSnapshotV1);

impl AuthoritativeCognitiveSnapshotProvider for BoundSnapshotProvider {
    fn acquire(
        &self,
        _request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError> {
        Ok(self.0.clone())
    }
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

//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::collections::BTreeMap;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsError;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_memory::DurableCognitiveSnapshot;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextRevalidation;
use crate::CognitiveContextSnapshot;

const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;
const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";

/// Only storage failures may invalidate the canonical SQLite owner. A revoked
/// or unavailable optional ranker closes the ranked read, not other store ports.
#[derive(Debug)]
pub(crate) enum CognitiveContextError {
    Store(CognitiveStoreError),
    ReadUnavailable(String),
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
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, now_seconds()?)
        .await?;
    let candidates = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new(query, now_seconds()?))
        .await?;
    let mut record_ids = candidates
        .candidates
        .iter()
        .map(|candidate| {
            StableId::new(candidate.memory.id.memory_id.as_str())
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))
        })
        .collect::<Result<Vec<_>, _>>()?;
    record_ids.sort();
    record_ids.dedup();
    let admission_read = cut
        .read_ids(ReadIdsRequestV1 {
            snapshot_digest: cut.snapshot().snapshot_digest,
            record_ids,
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        })
        .map_err(map_read_ids_error)?;
    let admitted_by_id = admission_read
        .records()
        .iter()
        .map(|record| (record.record_id.as_str(), record))
        .collect::<BTreeMap<_, _>>();
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: admission_read.snapshot_digest().to_string(),
        read_digest: admission_read.receipt_digest().to_string(),
        omitted_records: 0,
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
        let accepted = admitted_by_id
            .get(memory.id.memory_id.as_str())
            .is_some_and(|record| {
                record.is_live()
                    && record.revision.get() == memory.id.revision
                    && record
                        .content_digest
                        .is_some_and(|digest| digest.to_string() == memory.content_sha256.as_str())
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
    let selected_read = read_selected_items(&cut, &response.items)?;
    let selected_read_binding = bind_selected_read(&cut, &selected_read);
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
        let empty_read = read_selected_items(&cut, &response.items)?;
        response.read_digest = bind_selected_read(&cut, &empty_read).to_string();
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
    if plan.read_allowed != !items.is_empty() {
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
    let cut = store
        .lane_c_snapshot(&access, &scope, now_seconds()?)
        .await?;
    if cut.snapshot().snapshot_digest != expected_snapshot {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context snapshot is stale".to_string(),
        )
        .into());
    }

    let read = read_selected_items(&cut, items)?;
    let current_read_binding = bind_selected_read(&cut, &read);
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
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
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
fn bind_selected_read(cut: &DurableCognitiveSnapshot, read: &ReadIdsResultV1) -> Digest32 {
    let mut bytes = CONTEXT_READ_BINDING_DOMAIN.to_vec();
    bytes.extend_from_slice(cut.cut_digest().as_array());
    bytes.extend_from_slice(read.receipt_digest().as_array());
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

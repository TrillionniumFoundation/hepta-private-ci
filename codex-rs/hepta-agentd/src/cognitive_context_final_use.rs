//! Final-use verification over a newly acquired owner cut. No publication
//! view, plan, clock observation or authorization decision is cached here.

use std::collections::BTreeMap;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CognitiveContextError;
use super::CognitiveStore;
use super::CognitiveStoreError;
use super::MAX_CONTEXT_JSON_BYTES;
use super::bind_selected_read;
use super::load_retrieval_context;
use super::map_read_ids_error;
use super::now_seconds;
use super::observation::OperationObservation;
use super::observation::Phase;
use super::plan_binding;
use super::read_selected_items;
use super::read_view::OwnerCutReadView;
use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use super::CognitiveContextRevalidation;
use crate::CognitiveContextSnapshot;

pub(crate) async fn revalidate_with_retrieval_context(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&std::sync::Arc<crate::PinnedCognitiveRanker>>,
    body_generation: u64,
    current_retrieval: Option<&std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>>,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    let mut operation = OperationObservation::start(Phase::FinalUse);
    if items.len() > 4 {
        return Err(CognitiveStoreError::Invalid(
            "context revalidation accepts at most four items".to_string(),
        )
        .into());
    }
    // Check raw material before cloning an untrusted context into a pre-plan.
    // The complete escaped JSON envelope is checked separately below.
    let raw_bytes = items.iter().try_fold(0_usize, |total, item| {
        total
            .checked_add(item.memory_id.len())
            .and_then(|value| value.checked_add(item.content.len()))
            .and_then(|value| value.checked_add(item.content_sha256.len()))
    });
    if raw_bytes.is_none_or(|bytes| bytes > MAX_CONTEXT_JSON_BYTES) {
        return Err(CognitiveStoreError::Invalid(
            "context revalidation raw payload exceeds product budget".to_string(),
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
    if plan.evaluated_context_digest.len() != 64 || plan.plan_receipt_digest.len() != 64 {
        return Err(CognitiveStoreError::Invalid(
            "cognitive planning evidence must contain exact digest encodings".to_string(),
        )
        .into());
    }
    if plan.read_allowed == items.is_empty() {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context plan/item disposition mismatch".to_string(),
        )
        .into());
    }
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let record_ids = items.iter().map(|item| {
        StableId::new(item.memory_id.as_str()).map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
    }).collect::<Result<Vec<_>, _>>()?;
    let cut = store
        .lane_c_snapshot_ids(&access, &scope, now_seconds()?, &record_ids)
        .await?;
    if cut.snapshot().snapshot_digest != expected_snapshot {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context snapshot is stale".to_string(),
        )
        .into());
    }

    let read_view = OwnerCutReadView::new(cut.owner_snapshot()).map_err(map_read_ids_error)?;
    let read = read_selected_items(&read_view, items)?;
    let retrieval_context_digest = match current_retrieval {
        Some(current) => Some(
            load_retrieval_context(current, owner, body_generation)
                .await?
                .binding_digest(),
        ),
        None => None,
    };
    let current_read_binding = bind_selected_read(&cut, &read, retrieval_context_digest);
    let response = CognitiveContextSnapshot {
        snapshot_digest: snapshot_digest.to_string(),
        read_digest: read_digest.to_string(),
        omitted_records,
        items: items.to_vec(),
        plan: Some(plan.clone()),
    };
    if serde_json::to_vec(&response)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
        .len()
        > MAX_CONTEXT_JSON_BYTES
    {
        return Err(CognitiveStoreError::Invalid(
            "context revalidation envelope exceeds product budget".to_string(),
        )
        .into());
    }
    let unplanned = plan_binding::verify_publication(
        owner,
        body_generation,
        current_read_binding,
        &response,
    )?;
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

    if let Some(ranker) = ranker {
        let ranker = std::sync::Arc::clone(ranker);
        tokio::task::spawn_blocking(move || ranker.revalidate())
            .await
            .map_err(|_| CognitiveContextError::RankerUnavailable)?
            .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    }
    if let (Some(current), Some(expected)) = (current_retrieval, retrieval_context_digest)
        && load_retrieval_context(current, owner, body_generation)
            .await?
            .binding_digest()
            != expected
    {
        return Err(CognitiveContextError::RetrievalContextUnavailable);
    }
    // Awaited registry/model work must not hide a correction or expiry that
    // occurred after the initial cut acquisition in this final-use request.
    store
        .revalidate_lane_c_selection(&access, &scope, &cut, now_seconds()?)
        .await?;
    let fresh = plan_binding::evaluate(
        owner,
        body_generation,
        &unplanned,
        plan_binding::now_micros()?,
    )?;
    if fresh.plan.read_allowed != plan.read_allowed {
        return Err(CognitiveStoreError::Conflict(
            "fresh cognitive planning disposition differs from publication".to_string(),
        )
        .into());
    }
    fresh.ensure_current(plan_binding::now_micros()?)?;
    operation.succeed();
    Ok(CognitiveContextRevalidation {
        snapshot_digest: expected_snapshot.to_string(),
        read_digest: expected_read.to_string(),
        verified_item_count: u16::try_from(items.len()).map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid context item count: {error}"))
        })?,
    })
}

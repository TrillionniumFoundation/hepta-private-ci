//! Owner cut bound, byte bounded export for an external training process.

use codex_hepta_agent_protocol::MAX_MEMORY_CELL_PAGE_ROWS;
use codex_hepta_agent_protocol::MAX_MEMORY_CELL_PAYLOAD_BYTES;
use codex_hepta_agent_protocol::InventoryCellSnapshotPageV1;
use codex_hepta_agent_protocol::InventoryCellSnapshotSourceV1;
use codex_hepta_agent_protocol::InventoryCellSnapshotValueV1;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_types::InventoryCellReadoutV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;

use crate::AgentdError;
use crate::AgentdPayload;

fn now_unix_seconds() -> Result<i64, AgentdError> {
    super::now().map_err(|(_, reason)| AgentdError::Protocol(reason.to_string()))
}

pub(crate) async fn export_page(
    store: &DurableCognitiveStore,
    access: &CognitiveAccess,
    scope: &CognitiveScope,
    after: Option<ContractDigestV1>,
    expected_owner_cut: Option<ContractDigestV1>,
    limit: u16,
) -> Result<AgentdPayload, AgentdError> {
    if !(1..=MAX_MEMORY_CELL_PAGE_ROWS).contains(&limit)
        || (after.is_some() && expected_owner_cut.is_none())
    {
        return Err(AgentdError::Invalid(
            "memory cell page requires a bounded limit and a cut bound cursor".to_string(),
        ));
    }
    let owner = store
        .inventory_cell_snapshot(access, scope, now_unix_seconds()?)
        .await
        .map_err(|_| {
            AgentdError::Protocol("memory cell export owner is unavailable".to_string())
        })?;
    if expected_owner_cut.is_some_and(|expected| expected != owner.owner_cut_digest()) {
        return Err(AgentdError::Protocol(
            "memory cell export owner cut changed; restart pagination".to_string(),
        ));
    }
    let mut eligible = owner
        .records()
        .iter()
        .filter(|record| owner.current_source_ids().contains(&record.source_id))
        .collect::<Vec<_>>();
    eligible.sort_by_key(|record| record.source_id);
    let begin = if let Some(cursor) = after {
        eligible
            .iter()
            .position(|record| record.source_id == cursor)
            .ok_or_else(|| {
                AgentdError::Invalid(
                    "memory cell export cursor does not exist at this cut".to_string(),
                )
            })?
            + 1
    } else {
        0
    };
    let remaining = &eligible[begin..];
    let mut page = InventoryCellSnapshotPageV1 {
        schema: "hepta.memory.inventory-owner-snapshot-page.v1".to_string(),
        owner_agent_id: owner.owner_agent_id().clone(),
        scope: owner.scope().clone(),
        owner_cut_digest: owner.owner_cut_digest(),
        observed_at_unix_seconds: owner.observed_at_unix_seconds(),
        records: Vec::new(),
        next_after: None,
    };
    for record in remaining.iter().take(usize::from(limit)) {
        page.records.push(InventoryCellSnapshotSourceV1 {
            source_id: record.source_id,
            owner_memory_id: record.owner_memory_id.as_str().to_string(),
            revision: record.revision,
            record: InventoryCellSnapshotValueV1 {
                schema: record.record.schema.clone(),
                key: record.record.key.clone(),
                kind: record.record.kind,
                effective_at: record.record.effective_at,
                value: record.record.value.clone(),
                training_origin: record.record.training_origin,
            },
        });
        // Reserve a cursor even for a page that might later be complete. This
        // measures actual JSON escaping and metadata, not an average row size.
        page.next_after = Some(record.source_id);
        if serde_json::to_vec(&AgentdPayload::InventoryCellSnapshot(page.clone()))?.len()
            > MAX_MEMORY_CELL_PAYLOAD_BYTES
        {
            page.records.pop();
            break;
        }
    }
    if page.records.is_empty() && !remaining.is_empty() {
        return Err(AgentdError::Protocol(
            "memory cell export row exceeds the page byte bound".to_string(),
        ));
    }
    page.next_after = if page.records.len() < remaining.len() {
        page.records.last().map(|row| row.source_id)
    } else {
        None
    };
    let refreshed = store
        .inventory_cell_snapshot(access, scope, now_unix_seconds()?)
        .await
        .map_err(|_| {
            AgentdError::Protocol("memory cell export owner changed during acquisition".to_string())
        })?;
    if refreshed.owner_cut_digest() != owner.owner_cut_digest() {
        return Err(AgentdError::Protocol(
            "memory cell export owner changed during acquisition".to_string(),
        ));
    }
    bounded_payload(AgentdPayload::InventoryCellSnapshot(page))
}

pub(crate) fn readout_payload(readout: &InventoryCellReadoutV1) -> Result<AgentdPayload, AgentdError> {
    readout
        .validate()
        .map_err(|error| AgentdError::Protocol(error.to_string()))?;
    bounded_payload(AgentdPayload::InventoryCellRead {
        readout_json: serde_json::to_string(readout)?,
    })
}

fn bounded_payload(payload: AgentdPayload) -> Result<AgentdPayload, AgentdError> {
    if serde_json::to_vec(&payload)?.len() > MAX_MEMORY_CELL_PAYLOAD_BYTES {
        return Err(AgentdError::Protocol(
            "memory cell payload exceeds the control byte bound".to_string(),
        ));
    }
    Ok(payload)
}


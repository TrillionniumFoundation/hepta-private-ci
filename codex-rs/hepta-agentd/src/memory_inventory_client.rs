//! Typed cell methods on the existing bounded Agentd control client.

use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;

use super::AgentdClient;
use super::unexpected;

impl AgentdClient {
    /// Export current owner sources for training. Pages do not confer read or
    /// publication authority; pass the first cut on every subsequent request.
    pub async fn memory_inventory_snapshot(
        &self,
        after: Option<codex_hepta_cognitive_types::hnmf::ContractDigestV1>,
        expected_owner_cut: Option<codex_hepta_cognitive_types::hnmf::ContractDigestV1>,
        limit: u16,
    ) -> Result<crate::MemoryInventorySnapshotPageV1, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::MemoryInventorySnapshot {
                    after,
                    expected_owner_cut,
                    limit,
                },
            })
            .await?
            .payload
        {
            AgentdPayload::MemoryInventorySnapshot(page) => {
                if page.schema != "hepta.memory.inventory-owner-snapshot-page.v1"
                    || page.owner_agent_id != self.expected_agent_id
                    || page.records.len() > usize::from(limit)
                    || page
                        .records
                        .windows(2)
                        .any(|rows| rows[0].source_id >= rows[1].source_id)
                    || expected_owner_cut.is_some_and(|cut| cut != page.owner_cut_digest)
                    || after.is_some_and(|cursor| {
                        page.records
                            .first()
                            .is_some_and(|row| row.source_id <= cursor)
                    })
                    || page.next_after.is_some_and(|cursor| {
                        page.records
                            .last()
                            .is_none_or(|row| row.source_id != cursor)
                    })
                {
                    return Err(AgentdError::Protocol(
                        "memory inventory snapshot page differs from its request".to_string(),
                    ));
                }
                for row in &page.records {
                    if row.record.schema != "hepta.memory.inventory-record.v1"
                        || row.revision == 0
                        || row.record.effective_at >= 1_u64 << 53
                    {
                        return Err(AgentdError::Protocol(
                            "invalid memory inventory snapshot row".to_string(),
                        ));
                    }
                    codex_hepta_cognitive_types::validate_memory_inventory_value_v1(
                        row.record.kind,
                        &row.record.value,
                    )
                    .map_err(|error| AgentdError::Protocol(error.to_string()))?;
                }
                Ok(page)
            }
            payload => unexpected(payload),
        }
    }

    /// Execute the server-selected address model and native cells. Strict
    /// decoding immediately restores the typed readout from additive wire JSON.
    pub async fn memory_inventory_read(
        &self,
        request: codex_hepta_cognitive_types::MemoryInventoryRequestV1,
    ) -> Result<codex_hepta_cognitive_types::MemoryInventoryReadoutV1, AgentdError> {
        request
            .validate()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::MemoryInventoryRead {
                    request: request.clone(),
                },
            })
            .await?
            .payload
        {
            AgentdPayload::MemoryInventoryRead { readout_json } => {
                let readout =
                    codex_hepta_cognitive_types::decode_memory_inventory_readout_v1(readout_json.as_bytes())
                        .map_err(|error| AgentdError::Protocol(error.to_string()))?;
                if readout.query_id != request.query_id
                    || readout.hops > request.max_hops
                    || readout.cell_digests.len() > usize::from(request.max_cells)
                {
                    return Err(AgentdError::Protocol(
                        "memory inventory readout differs from its request".to_string(),
                    ));
                }
                Ok(readout)
            }
            payload => unexpected(payload),
        }
    }
}

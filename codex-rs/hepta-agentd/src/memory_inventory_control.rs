//! Additive inventory dispatch shares the owner readiness and generation fences.

use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;

use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdState;
use crate::memory_inventory_runtime::snapshot;

impl AgentdState {
    pub(super) async fn inventory_snapshot_payload(
        &self,
        store: Option<Arc<DurableCognitiveStore>>,
        after: Option<ContractDigestV1>,
        expected_owner_cut: Option<ContractDigestV1>,
        limit: u16,
    ) -> Result<AgentdPayload, AgentdError> {
        self.require_cognitive_control_ready_now()?;
        let Some(store) = store else { return Ok(super::cognitive_control_unavailable()); };
        let default_access = CognitiveAccess::agent_private(self.identity.agent_id.clone());
        let (access, scope) = self.memory_inventory.get()
            .map(|host| (host.access(), host.scope()))
            .unwrap_or((&default_access, &CognitiveScope::AgentPrivate));
        let result = snapshot::export_page(&store, access, scope, after, expected_owner_cut, limit).await;
        self.require_cognitive_control_ready_now()?;
        Ok(result.unwrap_or_else(error_payload))
    }

    pub(super) async fn inventory_read_payload(
        &self,
        store: Option<Arc<DurableCognitiveStore>>,
        request: &MemoryInventoryRequestV1,
    ) -> Result<AgentdPayload, AgentdError> {
        self.require_cognitive_control_ready_now()?;
        let Some(store) = store else { return Ok(super::cognitive_control_unavailable()); };
        let Some(host) = self.memory_inventory.get() else {
            return Ok(error_payload(AgentdError::Protocol(
                "this Agent has no selected inventory memory host".to_string(),
            )));
        };
        let result = host.read(&store, request).await
            .and_then(|readout| snapshot::readout_payload(&readout));
        self.require_cognitive_control_ready_now()?;
        Ok(result.unwrap_or_else(error_payload))
    }
}

fn error_payload(error: AgentdError) -> AgentdPayload {
    AgentdPayload::Error {
        code: "memory_inventory_unavailable".to_string(),
        message: error.to_string(),
    }
}

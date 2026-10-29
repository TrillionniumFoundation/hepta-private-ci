//! Final-use validation reacquires the same canonical owner cut, including unqueried heads.

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryInventoryExecutionV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryReadoutV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use serde_json::Value;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::memory_cell_owner::invalid;
use crate::memory_inventory_owner::MemoryInventoryOwnerSnapshotV1;

impl CognitiveStore {
    /// Source authority remains with the live owner. A qualified parameter value
    /// is still a prediction and cannot bypass generation or complete-cut checks.
    pub async fn revalidate_memory_inventory_readout(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        acquired: &MemoryInventoryOwnerSnapshotV1,
        request: &MemoryInventoryRequestV1,
        readout: &MemoryInventoryReadoutV1,
        generation: ContractGenerationV1,
        bundle_digest: ContractDigestV1,
        now_unix_seconds: i64,
    ) -> Result<(), CognitiveStoreError> {
        request.validate().map_err(invalid)?;
        readout.validate().map_err(invalid)?;
        let current = self.revalidate_lane_c_snapshot(access, scope, &acquired.cut, now_unix_seconds).await?;
        if acquired.owner_agent_id() != self.owner_agent_id()
            || request.scope != *acquired.scope()
            || current.cut_digest() != acquired.owner_cut_digest().digest()
            || readout.query_id != request.query_id
            || readout.generation != generation
            || readout.snapshot_digest != bundle_digest
            || readout.status != MemoryReadStatusV1::Ok
            || readout.hops > request.max_hops
        {
            return Err(CognitiveStoreError::Conflict("inventory owner, request, generation or bundle differs".to_string()));
        }
        let operation = readout.operation.ok_or_else(|| invalid("inventory operation absent"))?;
        if acquired.required_sources(request, operation)? != readout.source_ids.iter().copied().collect::<BTreeSet<_>>() {
            return Err(CognitiveStoreError::Conflict("inventory typed dependencies differ".to_string()));
        }
        match operation {
            MemoryOperationV1::Current | MemoryOperationV1::History | MemoryOperationV1::Change => {
                let current = acquired.current(&request.entity_key, MemoryInventoryKindV1::Event);
                let historical = acquired.at(&request.entity_key, MemoryInventoryKindV1::Event, request.at);
                let expected = match operation {
                    MemoryOperationV1::Current => current.map(|record| record.record.value.clone()),
                    MemoryOperationV1::History => historical.map(|record| record.record.value.clone()),
                    MemoryOperationV1::Change => current.and_then(|latest| {
                        acquired.at(&request.entity_key, MemoryInventoryKindV1::Event, request.since).and_then(|prior| {
                            Some(Value::from(latest.record.value.as_i64()?.checked_sub(prior.record.value.as_i64()?)?))
                        })
                    }),
                    MemoryOperationV1::Semantic | MemoryOperationV1::Procedure | MemoryOperationV1::Apply => None,
                };
                if expected.as_ref() != Some(&readout.value) || request.max_cells < 1 {
                    return Err(CognitiveStoreError::Conflict("inventory exact event differs".to_string()));
                }
            }
            MemoryOperationV1::Semantic | MemoryOperationV1::Procedure => {
                if readout.cell_digests.len() != 1 || request.max_cells < 1 {
                    return Err(CognitiveStoreError::Conflict("inventory single prediction artifact".to_string()));
                }
            }
            MemoryOperationV1::Apply => {
                let hold = acquired.current(&request.entity_key, MemoryInventoryKindV1::Hold)
                    .and_then(|record| record.record.value.as_bool());
                let event = acquired.current(&request.entity_key, MemoryInventoryKindV1::Event)
                    .and_then(|record| record.record.value.as_i64());
                let execution: MemoryInventoryExecutionV1 = serde_json::from_value(readout.value.clone()).map_err(invalid)?;
                if hold != Some(false)
                    || request.max_cells < 4
                    || request.max_hops < 3
                    || readout.hops != 3
                    || readout.cell_digests.len() != 2
                    || execution.trace.len() > usize::from(request.max_steps)
                    || execution.trace.first().map(|step| step.before) != event
                {
                    return Err(CognitiveStoreError::Conflict("inventory hold, program budget or initial event differs".to_string()));
                }
            }
        }
        Ok(())
    }
}

//! Inventory views are acquired from the canonical cognitive owner, never imported as authority.

use std::collections::BTreeSet;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractIdV1, HnmfContractError};
use codex_hepta_cognitive_types::validate_memory_inventory_value_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_types::Digest32;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use crate::{CognitiveStoreError, DurableCognitiveSnapshot, StableMemoryId};
use crate::cognitive_store::unavailable;
use crate::memory_cell_owner::invalid;

pub const MAX_MEMORY_INVENTORY_OWNER_HEADS: usize = 512;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryAddressV1 {
    pub key: ContractIdV1,
    pub kind: MemoryInventoryKindV1,
    /// Unix seconds, matching the canonical owner's validity timestamp.
    pub effective_at: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryRecordV1 {
    pub schema: String,
    pub key: ContractIdV1,
    pub kind: MemoryInventoryKindV1,
    /// Unix seconds; this is not a YYYYMMDD date or a scope-local logical clock.
    pub effective_at: u64,
    pub value: Value,
}

impl MemoryInventoryRecordV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.inventory-record.v1" || self.effective_at >= 1_u64 << 53 {
            return Err(HnmfContractError::Invalid("memory cell record envelope"));
        }
        validate_memory_inventory_value_v1(self.kind, &self.value)
    }

    pub fn address(&self) -> MemoryInventoryAddressV1 {
        MemoryInventoryAddressV1 {
            key: self.key.clone(),
            kind: self.kind,
            effective_at: self.effective_at,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryInventoryOwnerRecordV1 {
    pub source_id: ContractDigestV1,
    pub owner_memory_id: StableMemoryId,
    pub revision: u64,
    pub record: MemoryInventoryRecordV1,
}

/// Created only by the real owner. JSON serialization supports training export;
/// there is deliberately no deserializer that could import an authority claim.
#[derive(Clone, Debug, Serialize)]
pub struct MemoryInventoryOwnerSnapshotV1 {
    pub(crate) schema: &'static str,
    pub(crate) owner_agent_id: AgentId,
    pub(crate) scope: ContractIdV1,
    pub(crate) owner_cut_digest: ContractDigestV1,
    pub(crate) observed_at_unix_seconds: i64,
    pub(crate) records: Vec<MemoryInventoryOwnerRecordV1>,
    pub(crate) withdrawn_addresses: Vec<MemoryInventoryAddressV1>,
    pub(crate) current_source_ids: Vec<ContractDigestV1>,
    #[serde(skip)]
    pub(crate) cut: DurableCognitiveSnapshot,
}

impl MemoryInventoryOwnerSnapshotV1 {
    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }

    pub fn observed_at_unix_seconds(&self) -> i64 {
        self.observed_at_unix_seconds
    }

    pub fn scope(&self) -> &ContractIdV1 {
        &self.scope
    }

    pub fn owner_cut_digest(&self) -> ContractDigestV1 {
        self.owner_cut_digest
    }

    pub fn records(&self) -> &[MemoryInventoryOwnerRecordV1] {
        &self.records
    }

    pub fn current_source_ids(&self) -> &[ContractDigestV1] {
        &self.current_source_ids
    }

    pub fn training_records(&self, kind: MemoryInventoryKindV1) -> Vec<&MemoryInventoryOwnerRecordV1> {
        self.records
            .iter()
            .filter(|item| {
                item.record.kind == kind && self.current_source_ids.contains(&item.source_id)
            })
            .collect()
    }

    pub fn current(
        &self,
        key: &ContractIdV1,
        kind: MemoryInventoryKindV1,
    ) -> Option<&MemoryInventoryOwnerRecordV1> {
        self.at(key, kind, self.observed_at_unix_seconds as u64)
    }

    pub fn at(
        &self,
        key: &ContractIdV1,
        kind: MemoryInventoryKindV1,
        at: u64,
    ) -> Option<&MemoryInventoryOwnerRecordV1> {
        let selected = self
            .records
            .iter()
            .filter(|item| {
                item.record.key == *key
                    && item.record.kind == kind
                    && item.record.effective_at <= at
            })
            .max_by_key(|item| item.record.effective_at)?;
        if self.withdrawn_addresses.iter().any(|address| {
            address.key == *key
                && address.kind == kind
                && address.effective_at <= at
                && address.effective_at >= selected.record.effective_at
        }) {
            return None;
        }
        Some(selected)
    }

    /// Exact typed dependencies, including an explicit current hold=false record.
    pub fn required_sources(
        &self,
        request: &MemoryInventoryRequestV1,
        operation: MemoryOperationV1,
    ) -> Result<BTreeSet<ContractDigestV1>, CognitiveStoreError> {
        request.validate().map_err(crate::memory_cell_owner::invalid)?;
        if request.scope != self.scope {
            return Err(CognitiveStoreError::AccessDenied("inventory request scope".to_string()));
        }
        use MemoryInventoryKindV1::{Event, Semantic, Procedure, Hold};
        let selected = match operation {
            MemoryOperationV1::Current => vec![self.current(&request.entity_key, Event)],
            MemoryOperationV1::History => vec![self.at(&request.entity_key, Event, request.at)],
            MemoryOperationV1::Change => vec![self.current(&request.entity_key, Event), self.at(&request.entity_key, Event, request.since)],
            MemoryOperationV1::Semantic => vec![self.current(&request.entity_key, Semantic)],
            MemoryOperationV1::Procedure => vec![self.current(&request.workflow_key, Procedure)],
            MemoryOperationV1::Apply => vec![self.current(&request.entity_key, Event), self.current(&request.entity_key, Semantic),
                self.current(&request.workflow_key, Procedure), self.current(&request.entity_key, Hold)],
        };
        selected.into_iter().map(|record| record.map(|record| record.source_id).ok_or_else(||
            CognitiveStoreError::Conflict("inventory dependency unavailable or withdrawn".to_string()))).collect()
    }
}

pub(crate) fn inventory_stable_key(
    address: &MemoryInventoryAddressV1,
) -> Result<String, CognitiveStoreError> {
    if address.effective_at >= 1_u64 << 53 {
        return Err(CognitiveStoreError::Invalid(
            "memory cell address time bound".to_string(),
        ));
    }
    let bytes = serde_json::to_vec(address).map_err(unavailable)?;
    Ok(format!("memory-inventory:v1:{}", Digest32::of_bytes(&bytes)))
}

pub(crate) fn decode_inventory(content: &str) -> Result<Option<MemoryInventoryRecordV1>, CognitiveStoreError> {
    let Ok(value) = serde_json::from_str::<Value>(content) else {
        return Ok(None);
    };
    if value.get("schema").and_then(Value::as_str) != Some("hepta.memory.inventory-record.v1") {
        return Ok(None);
    }
    let record: MemoryInventoryRecordV1 = serde_json::from_value(value)
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    record.validate().map_err(invalid)?;
    Ok(Some(record))
}

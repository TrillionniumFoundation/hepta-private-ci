//! A typed view of the original SQLite owner; no second database or authority.

use std::collections::BTreeSet;
use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellRequestV1, InventoryCellRouteV1, MemoryOperationV1, validate_inventory_cell_value_v1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractIdV1, HnmfContractError};
use codex_hepta_contracts::AgentId;
use codex_hepta_types::Digest32;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use crate::{CognitiveStoreError, DurableCognitiveSnapshot, StableMemoryId};
use crate::cognitive_store::unavailable;
use crate::memory_cell_owner::invalid;

#[path = "inventory_cell_acquire.rs"]
mod acquire;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellAddressV1 {
    pub key: ContractIdV1,
    pub kind: InventoryCellKindV1,
    /// Unix seconds, matching the canonical owner's validity timestamp.
    pub effective_at: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellRecordV1 {
    pub schema: String,
    pub key: ContractIdV1,
    pub kind: InventoryCellKindV1,
    /// Unix seconds; this is not a YYYYMMDD date or a scope-local logical clock.
    pub effective_at: u64,
    pub value: Value,
    /// Optional import lineage. Only the immutable first revision may map this
    /// authored source to a native owner source; corrected values must retrain
    /// against their actual canonical source IDs.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub training_origin: Option<ContractDigestV1>,
}

impl InventoryCellRecordV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.inventory-cell-record.v1" || self.effective_at >= 1_u64 << 53 {
            return Err(HnmfContractError::Invalid("memory cell record envelope"));
        }
        validate_inventory_cell_value_v1(self.kind, &self.value)
    }

    pub fn address(&self) -> InventoryCellAddressV1 {
        InventoryCellAddressV1 {
            key: self.key.clone(),
            kind: self.kind,
            effective_at: self.effective_at,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct InventoryCellOwnerRecordV1 {
    pub source_id: ContractDigestV1,
    pub owner_memory_id: StableMemoryId,
    pub revision: u64,
    pub record: InventoryCellRecordV1,
}

/// Created only by the real owner. JSON serialization supports training export;
/// there is deliberately no deserializer that could import an authority claim.
#[derive(Clone, Debug, Serialize)]
pub struct InventoryCellOwnerSnapshotV1 {
    schema: &'static str,
    owner_agent_id: AgentId,
    scope: ContractIdV1,
    owner_cut_digest: ContractDigestV1,
    observed_at_unix_seconds: i64,
    records: Vec<InventoryCellOwnerRecordV1>,
    withdrawn_addresses: Vec<InventoryCellAddressV1>,
    current_source_ids: Vec<ContractDigestV1>,
    #[serde(skip)]
    cut: DurableCognitiveSnapshot,
}

impl InventoryCellOwnerSnapshotV1 {
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

    pub fn records(&self) -> &[InventoryCellOwnerRecordV1] {
        &self.records
    }

    pub fn current_source_ids(&self) -> &[ContractDigestV1] {
        &self.current_source_ids
    }

    /// Only learned policy/program sources bind parameter validity. Exact events
    /// and holds are read from a fresh full owner cut on every request.
    pub fn parameter_training_cut_digest(&self) -> Result<ContractDigestV1, CognitiveStoreError> {
        let mut sources: Vec<_> = self.records.iter().filter(|row| {
            matches!(row.record.kind, InventoryCellKindV1::Semantic | InventoryCellKindV1::Skill)
                && self.current_source_ids.contains(&row.source_id)
        }).map(|row| (row.record.kind, row.record.key.clone(), row.source_id)).collect();
        sources.sort_by(|left, right| {
            let rank = |kind| u8::from(kind == InventoryCellKindV1::Skill);
            rank(left.0).cmp(&rank(right.0)).then_with(|| left.1.as_str().cmp(right.1.as_str()))
        });
        let bytes = serde_json::to_vec(&("hepta.sqlite.inventory-training-cut.v1", &self.scope, sources)).map_err(unavailable)?;
        ContractDigestV1::from_digest(Digest32::of_bytes(&bytes)).map_err(invalid)
    }

    pub fn training_records(&self, kind: InventoryCellKindV1) -> Vec<&InventoryCellOwnerRecordV1> {
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
        kind: InventoryCellKindV1,
    ) -> Option<&InventoryCellOwnerRecordV1> {
        self.at(key, kind, self.observed_at_unix_seconds as u64)
    }

    pub fn at(
        &self,
        key: &ContractIdV1,
        kind: InventoryCellKindV1,
        at: u64,
    ) -> Option<&InventoryCellOwnerRecordV1> {
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

    pub(crate) fn required_sources(
        &self, request: &InventoryCellRequestV1, route: &InventoryCellRouteV1,
    ) -> Result<BTreeSet<ContractDigestV1>, CognitiveStoreError> {
        route.validate().map_err(invalid)?;
        use InventoryCellKindV1::{Event, Semantic, Skill, Hold};
        let current = |key: &Option<ContractIdV1>, kind| key.as_ref().and_then(|key| self.current(key, kind));
        let event_at = |at| route.entity.as_ref().and_then(|key| self.at(key, Event, at));
        let selected = match route.operation {
            MemoryOperationV1::Current => vec![current(&route.entity, Event)],
            MemoryOperationV1::History => vec![event_at(request.at)],
            MemoryOperationV1::Change => vec![current(&route.entity, Event), event_at(request.since)],
            MemoryOperationV1::Semantic => vec![current(&route.entity, Semantic)],
            MemoryOperationV1::Procedure => vec![current(&route.workflow, Skill)],
            MemoryOperationV1::Apply => {
                if current(&route.entity, Hold).is_some() {
                    return Err(CognitiveStoreError::Conflict("exact owner hold forbids composition".to_string()));
                }
                vec![current(&route.entity, Event), current(&route.entity, Semantic), current(&route.workflow, Skill)]
            }
        };
        selected.into_iter().map(|row| row.map(|row| row.source_id).ok_or_else(||
            CognitiveStoreError::Conflict("inventory dependency missing or withdrawn".to_string())
        )).collect()
    }
}

pub(crate) fn inventory_cell_stable_key(
    address: &InventoryCellAddressV1,
) -> Result<String, CognitiveStoreError> {
    if address.effective_at >= 1_u64 << 53 {
        return Err(CognitiveStoreError::Invalid(
            "memory cell address time bound".to_string(),
        ));
    }
    let bytes = serde_json::to_vec(address).map_err(unavailable)?;
    Ok(format!("inventory-cell:v1:{}", Digest32::of_bytes(&bytes)))
}

fn decode_inventory_cell(content: &str) -> Result<Option<InventoryCellRecordV1>, CognitiveStoreError> {
    let Ok(value) = serde_json::from_str::<Value>(content) else {
        return Ok(None);
    };
    if value.get("schema").and_then(Value::as_str) != Some("hepta.memory.inventory-cell-record.v1") {
        return Ok(None);
    }
    let record: InventoryCellRecordV1 = serde_json::from_value(value)
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    record.validate().map_err(invalid)?;
    Ok(Some(record))
}


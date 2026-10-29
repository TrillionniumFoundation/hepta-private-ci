//! Reuse Lane C snapshot acquisition, immutable origins and final-use revalidation.

use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellReadoutV1, InventoryCellRequestV1, MemoryOperationV1, MemoryPredictionKindV1, MemoryReadStatusV1, RecordState};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractGenerationV1, ContractIdV1};
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use serde_json::Value;
use sqlx::Row;
use crate::{CognitiveAccess, CognitiveScope, CognitiveStore, CognitiveStoreError, StableMemoryId, MAX_MEMORY_CELL_OWNER_HEADS};
use crate::cognitive_store::unavailable;
use crate::memory_cell_owner::invalid;
use super::{InventoryCellAddressV1, InventoryCellOwnerRecordV1, InventoryCellOwnerSnapshotV1, decode_inventory_cell, inventory_cell_stable_key};

impl CognitiveStore {
    /// Read current typed heads under the existing owner and exact scope. The
    /// complete Lane C cut is checked again after payload/citation acquisition.
    pub async fn inventory_cell_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<InventoryCellOwnerSnapshotV1, CognitiveStoreError> {
        let cut = self
            .lane_c_snapshot(access, scope, now_unix_seconds)
            .await?;
        if cut.snapshot().records.len() > MAX_MEMORY_CELL_OWNER_HEADS {
            return Err(CognitiveStoreError::Unavailable(
                "memory cell owner head capacity exceeded".to_string(),
            ));
        }
        let scope_id = ContractIdV1::new(cut.scope_id().as_str()).map_err(invalid)?;
        let mut records = Vec::new();
        let mut withdrawn_addresses = Vec::new();
        for head in &cut.snapshot().records {
            let id = StableMemoryId::parse(head.record_id.as_str())
                .map_err(CognitiveStoreError::Corrupt)?;
            let first = sqlx::query("SELECT content, content_sha256 FROM memory_revisions WHERE memory_id = ? AND revision = 1")
                .bind(id.as_str()).fetch_one(&self.pool).await.map_err(unavailable)?;
            let first_content: String = first.try_get("content").map_err(unavailable)?;
            let first_digest: String = first.try_get("content_sha256").map_err(unavailable)?;
            if Sha256Digest::for_bytes(first_content.as_bytes()).as_str() != first_digest {
                return Err(CognitiveStoreError::Corrupt(
                    "memory cell origin payload digest differs".to_string(),
                ));
            }
            let Ok(origin) = serde_json::from_str::<Value>(&first_content) else {
                continue;
            };
            if origin.get("schema").and_then(Value::as_str) != Some("hepta.memory.inventory-cell-record.v1") {
                continue;
            }
            let Ok(address) = serde_json::from_value::<InventoryCellAddressV1>(serde_json::json!({
                "key": origin.get("key"), "kind": origin.get("kind"), "effective_at": origin.get("effective_at")
            })) else {
                continue;
            };
            if address.effective_at >= 1_u64 << 53 {
                continue;
            }
            if StableMemoryId::for_key(self.owner_agent_id(), scope, &inventory_cell_stable_key(&address)?)
                != id
            {
                // A normal memory may quote this JSON schema. The owner's
                // canonical address, not payload text alone, registers a cell.
                continue;
            }
            let original = decode_inventory_cell(&first_content)?.ok_or_else(|| {
                CognitiveStoreError::Corrupt("registered memory cell origin is invalid".to_string())
            })?;
            let explanation = self.explain_memory_head(access, &id).await?;
            let memory = explanation.memory;
            if memory.scope != *scope
                || memory.id.revision != head.revision.get()
                || memory.content_sha256.as_str() != head.content_digest.to_string()
                || explanation.citations.len() != head.citations.len()
                || explanation
                    .citations
                    .iter()
                    .zip(&head.citations)
                    .any(|(actual, bound)| {
                        actual.id.source_id.as_str() != bound.source_id.as_str()
                            || actual.content_sha256.as_str() != bound.source_digest.to_string()
                    })
            {
                return Err(CognitiveStoreError::Conflict(
                    "memory cell head differs from acquired cut".to_string(),
                ));
            }
            if head.state == RecordState::Tombstone {
                withdrawn_addresses.push(original.address());
                continue;
            }
            let record = decode_inventory_cell(&memory.content)?.ok_or_else(|| {
                CognitiveStoreError::Corrupt("typed memory changed its schema".to_string())
            })?;
            if record.address() != original.address()
                || record.effective_at != memory.valid_from_unix_seconds as u64
            {
                return Err(CognitiveStoreError::Corrupt(
                    "typed memory changed its address or validity".to_string(),
                ));
            }
            let source_bytes = serde_json::to_vec(&(
                "hepta.sqlite.inventory-cell-source.v1",
                &scope_id,
                head.record_digest().to_string(),
            ))
            .map_err(unavailable)?;
            records.push(InventoryCellOwnerRecordV1 {
                source_id: ContractDigestV1::from_digest(Digest32::of_bytes(&source_bytes))
                    .map_err(invalid)?,
                owner_memory_id: id,
                revision: memory.id.revision,
                record,
            });
        }
        self.revalidate_lane_c_snapshot(access, scope, &cut, now_unix_seconds)
            .await?;
        let mut snapshot = InventoryCellOwnerSnapshotV1 {
            schema: "hepta.memory.inventory-owner-snapshot.v1",
            owner_agent_id: self.owner_agent_id().clone(),
            scope: scope_id,
            owner_cut_digest: ContractDigestV1::from_digest(cut.cut_digest()).map_err(invalid)?,
            observed_at_unix_seconds: now_unix_seconds,
            records,
            withdrawn_addresses,
            current_source_ids: Vec::new(),
            cut,
        };
        snapshot.current_source_ids = snapshot
            .records
            .iter()
            .filter(|record| {
                snapshot
                    .current(&record.record.key, record.record.kind)
                    .map(|item| item.source_id)
                    == Some(record.source_id)
            })
            .map(|record| record.source_id)
            .collect();
        Ok(snapshot)
    }

    /// Validate against the same authenticated owner cut immediately before use.
    /// Tensor predictions retain prediction status; they never authorize writes.
    pub async fn revalidate_inventory_cell_readout(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        acquired: &InventoryCellOwnerSnapshotV1,
        request: &InventoryCellRequestV1,
        readout: &InventoryCellReadoutV1,
        generation: ContractGenerationV1,
        bundle_digest: ContractDigestV1,
        now_unix_seconds: i64,
    ) -> Result<(), CognitiveStoreError> {
        request.validate().map_err(invalid)?;
        readout.validate().map_err(invalid)?;
        let result = &readout.result;
        let route = readout.route.as_ref().ok_or_else(|| invalid("inventory route absent"))?;
        let current = self.revalidate_lane_c_snapshot(access, scope, &acquired.cut, now_unix_seconds).await?;
        if acquired.owner_agent_id != *self.owner_agent_id()
            || request.scope != acquired.scope
            || current.cut_digest() != acquired.owner_cut_digest.digest()
            || request.query_id != result.query_id
            || result.status != MemoryReadStatusV1::Ok
            || result.generation != generation
            || result.snapshot_digest != bundle_digest
        {
            return Err(CognitiveStoreError::Conflict("inventory readout owner, query or version differs".to_string()));
        }
        if acquired.required_sources(request, route)? != result.source_ids.iter().copied().collect() {
            return Err(CognitiveStoreError::Conflict("inventory dual-address dependencies differ".to_string()));
        }
        let (cells, hops, kind, models) = match route.operation {
            MemoryOperationV1::Apply => (3, 3, MemoryPredictionKindV1::Mixed, 2),
            MemoryOperationV1::Semantic | MemoryOperationV1::Procedure => (1, 1, MemoryPredictionKindV1::ModelPrediction, 1),
            MemoryOperationV1::Change => (1, 2, MemoryPredictionKindV1::SourceEvidence, 0),
            _ => (1, 1, MemoryPredictionKindV1::SourceEvidence, 0),
        };
        if request.max_cells < cells || request.max_hops < hops || result.hops != hops
            || result.prediction_kind != kind || result.cell_digests.len() != models
        {
            return Err(CognitiveStoreError::Conflict("inventory budget or prediction labeling differs".to_string()));
        }
        if kind == MemoryPredictionKindV1::SourceEvidence {
            let entity = route.entity.as_ref().ok_or_else(|| invalid("inventory entity absent"))?;
            let event = |at| acquired.at(entity, InventoryCellKindV1::Event, at)
                .and_then(|row| row.record.value.as_i64());
            let value = match route.operation {
                MemoryOperationV1::Current => event(acquired.observed_at_unix_seconds as u64),
                MemoryOperationV1::History => event(request.at),
                MemoryOperationV1::Change => event(acquired.observed_at_unix_seconds as u64)
                    .and_then(|latest| latest.checked_sub(event(request.since)?)),
                _ => None,
            };
            if value != result.value.as_i64() || value.is_none() {
                return Err(CognitiveStoreError::Conflict("exact inventory event differs".to_string()));
            }
        }
        Ok(())
    }
}


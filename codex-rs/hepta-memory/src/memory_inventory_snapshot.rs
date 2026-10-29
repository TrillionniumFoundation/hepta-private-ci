//! Profile-specific source decoding over the same authorized Lane C snapshot.

use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractIdV1};
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use serde_json::Value;
use sqlx::Row;
use crate::{CognitiveAccess, CognitiveScope, CognitiveStore, CognitiveStoreError, StableMemoryId};
use crate::cognitive_store::unavailable;
use crate::memory_cell_owner::invalid;
use crate::memory_inventory_owner::{MemoryInventoryAddressV1, MemoryInventoryOwnerRecordV1, MemoryInventoryOwnerSnapshotV1, MAX_MEMORY_INVENTORY_OWNER_HEADS, decode_inventory, inventory_stable_key};

impl CognitiveStore {
    /// Read current typed heads under the existing owner and exact scope. The
    /// complete Lane C cut is checked again after payload/citation acquisition.
    pub async fn memory_inventory_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<MemoryInventoryOwnerSnapshotV1, CognitiveStoreError> {
        let cut = self
            .lane_c_snapshot(access, scope, now_unix_seconds)
            .await?;
        if cut.snapshot().records.len() > MAX_MEMORY_INVENTORY_OWNER_HEADS {
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
            if origin.get("schema").and_then(Value::as_str) != Some("hepta.memory.inventory-record.v1") {
                continue;
            }
            let Ok(address) = serde_json::from_value::<MemoryInventoryAddressV1>(serde_json::json!({
                "key": origin.get("key"), "kind": origin.get("kind"), "effective_at": origin.get("effective_at")
            })) else {
                continue;
            };
            if address.effective_at >= 1_u64 << 53 {
                continue;
            }
            if StableMemoryId::for_key(self.owner_agent_id(), scope, &inventory_stable_key(&address)?)
                != id
            {
                // A normal memory may quote this JSON schema. The owner's
                // canonical address, not payload text alone, registers a cell.
                continue;
            }
            let original = decode_inventory(&first_content)?.ok_or_else(|| {
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
            let record = decode_inventory(&memory.content)?.ok_or_else(|| {
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
                "hepta.sqlite.memory-inventory-source.v1",
                &scope_id,
                head.record_digest().to_string(),
            ))
            .map_err(unavailable)?;
            records.push(MemoryInventoryOwnerRecordV1 {
                source_id: ContractDigestV1::from_digest(Digest32::of_bytes(&source_bytes))
                    .map_err(invalid)?,
                owner_memory_id: id,
                revision: memory.id.revision,
                record,
            });
        }
        self.revalidate_lane_c_snapshot(access, scope, &cut, now_unix_seconds)
            .await?;
        let mut snapshot = MemoryInventoryOwnerSnapshotV1 {
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

}

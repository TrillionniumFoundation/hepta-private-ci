//! Typed cell views acquired from the canonical SQLite cognitive owner.
//!
//! An exported snapshot is historical evidence, never a freshness capability.
//! Final-use validation reacquires the actual owner cut with authenticated access.

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::HnmfContractError;
use codex_hepta_cognitive_types::validate_memory_cell_value_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory_retrieval::MemorySourceVerifierV1;
use codex_hepta_memory_retrieval::revalidate_memory_readout_v1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use sqlx::Row;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::DurableCognitiveSnapshot;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;

pub const MAX_MEMORY_CELL_OWNER_HEADS: usize = 512;

/// Canonical Lane C scope address. Deriving an address conveys no source access;
/// callers still need the real owner or a current federation capability.
pub fn memory_cell_scope_id(
    owner: &AgentId,
    scope: &CognitiveScope,
) -> Result<ContractIdV1, HnmfContractError> {
    ContractIdV1::new(format!(
        "cognitive:{owner}:{}",
        Digest32::of_bytes(scope.projection_key().as_bytes())
    ))
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellAddressV1 {
    pub entity: ContractIdV1,
    pub kind: MemoryCellKindV1,
    /// Unix seconds, matching the canonical owner's validity timestamp.
    pub effective_at: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellRecordV1 {
    pub schema: String,
    pub entity: ContractIdV1,
    pub kind: MemoryCellKindV1,
    /// Unix seconds; this is not a YYYYMMDD date or a scope-local logical clock.
    pub effective_at: u64,
    pub value: Value,
}

impl MemoryCellRecordV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.cell-record.v1" || self.effective_at >= 1_u64 << 53 {
            return Err(HnmfContractError::Invalid("memory cell record envelope"));
        }
        validate_memory_cell_value_v1(self.kind, &self.value)
    }

    pub fn address(&self) -> MemoryCellAddressV1 {
        MemoryCellAddressV1 {
            entity: self.entity.clone(),
            kind: self.kind,
            effective_at: self.effective_at,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryCellOwnerRecordV1 {
    pub source_id: ContractDigestV1,
    pub owner_memory_id: StableMemoryId,
    pub revision: u64,
    pub record: MemoryCellRecordV1,
}

/// Created only by the real owner. JSON serialization supports training export;
/// there is deliberately no deserializer that could import an authority claim.
#[derive(Clone, Debug, Serialize)]
pub struct MemoryCellOwnerSnapshotV1 {
    schema: &'static str,
    owner_agent_id: AgentId,
    scope: ContractIdV1,
    owner_cut_digest: ContractDigestV1,
    observed_at_unix_seconds: i64,
    records: Vec<MemoryCellOwnerRecordV1>,
    withdrawn_addresses: Vec<MemoryCellAddressV1>,
    current_source_ids: Vec<ContractDigestV1>,
    #[serde(skip)]
    cut: DurableCognitiveSnapshot,
}

impl MemoryCellOwnerSnapshotV1 {
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

    pub fn records(&self) -> &[MemoryCellOwnerRecordV1] {
        &self.records
    }

    pub fn current_source_ids(&self) -> &[ContractDigestV1] {
        &self.current_source_ids
    }

    pub fn training_records(&self, kind: MemoryCellKindV1) -> Vec<&MemoryCellOwnerRecordV1> {
        self.records
            .iter()
            .filter(|item| {
                item.record.kind == kind && self.current_source_ids.contains(&item.source_id)
            })
            .collect()
    }

    pub fn current(
        &self,
        entity: &ContractIdV1,
        kind: MemoryCellKindV1,
    ) -> Option<&MemoryCellOwnerRecordV1> {
        self.at(entity, kind, self.observed_at_unix_seconds as u64)
    }

    pub fn at(
        &self,
        entity: &ContractIdV1,
        kind: MemoryCellKindV1,
        at: u64,
    ) -> Option<&MemoryCellOwnerRecordV1> {
        let selected = self
            .records
            .iter()
            .filter(|item| {
                item.record.entity == *entity
                    && item.record.kind == kind
                    && item.record.effective_at <= at
            })
            .max_by_key(|item| item.record.effective_at)?;
        if self.withdrawn_addresses.iter().any(|address| {
            address.entity == *entity
                && address.kind == kind
                && address.effective_at <= at
                && address.effective_at >= selected.record.effective_at
        }) {
            return None;
        }
        Some(selected)
    }

    fn required_sources(
        &self,
        request: &MemoryRequestV1,
        operation: MemoryOperationV1,
    ) -> Result<BTreeSet<ContractDigestV1>, CognitiveStoreError> {
        use MemoryCellKindV1::Event;
        use MemoryCellKindV1::Procedure;
        use MemoryCellKindV1::Semantic;
        let current = |kind| self.current(&request.entity, kind);
        let selected = match operation {
            MemoryOperationV1::Current => vec![current(Event)],
            MemoryOperationV1::History => vec![self.at(&request.entity, Event, request.at)],
            MemoryOperationV1::Semantic => vec![current(Semantic)],
            MemoryOperationV1::Procedure => vec![current(Procedure)],
            MemoryOperationV1::Change => vec![
                current(Event),
                self.at(&request.entity, Event, request.since),
            ],
            MemoryOperationV1::Apply => vec![current(Event), current(Semantic), current(Procedure)],
        };
        selected
            .into_iter()
            .map(|record| {
                record.map(|item| item.source_id).ok_or_else(|| {
                    CognitiveStoreError::Conflict(
                        "memory cell dependency is unavailable or withdrawn".to_string(),
                    )
                })
            })
            .collect()
    }
}

impl CognitiveStore {
    /// Read current typed heads under the existing owner and exact scope. The
    /// complete Lane C cut is checked again after payload/citation acquisition.
    pub async fn memory_cell_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<MemoryCellOwnerSnapshotV1, CognitiveStoreError> {
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
            if origin.get("schema").and_then(Value::as_str) != Some("hepta.memory.cell-record.v1") {
                continue;
            }
            let Ok(address) = serde_json::from_value::<MemoryCellAddressV1>(serde_json::json!({
                "entity": origin.get("entity"), "kind": origin.get("kind"), "effective_at": origin.get("effective_at")
            })) else {
                continue;
            };
            if address.effective_at >= 1_u64 << 53 {
                continue;
            }
            if StableMemoryId::for_key(self.owner_agent_id(), scope, &cell_stable_key(&address)?)
                != id
            {
                // A normal memory may quote this JSON schema. The owner's
                // canonical address, not payload text alone, registers a cell.
                continue;
            }
            let original = decode_cell(&first_content)?.ok_or_else(|| {
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
            let record = decode_cell(&memory.content)?.ok_or_else(|| {
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
                "hepta.sqlite.memory-cell-source.v1",
                &scope_id,
                head.record_digest().to_string(),
            ))
            .map_err(unavailable)?;
            records.push(MemoryCellOwnerRecordV1 {
                source_id: ContractDigestV1::from_digest(Digest32::of_bytes(&source_bytes))
                    .map_err(invalid)?,
                owner_memory_id: id,
                revision: memory.id.revision,
                record,
            });
        }
        self.revalidate_lane_c_snapshot(access, scope, &cut, now_unix_seconds)
            .await?;
        let mut snapshot = MemoryCellOwnerSnapshotV1 {
            schema: "hepta.memory.owner-snapshot.v1",
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
                    .current(&record.record.entity, record.record.kind)
                    .map(|item| item.source_id)
                    == Some(record.source_id)
            })
            .map(|record| record.source_id)
            .collect();
        Ok(snapshot)
    }

    /// Reacquire the real owner immediately before consuming a model readout.
    /// The caller separately binds the published bundle to this owner cut and
    /// validates its complete training lineage; no model fact authority is added.
    pub async fn revalidate_memory_cell_readout(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        acquired: &MemoryCellOwnerSnapshotV1,
        request: &MemoryRequestV1,
        readout: &MemoryReadoutV1,
        generation: ContractGenerationV1,
        bundle_digest: ContractDigestV1,
        now_unix_seconds: i64,
    ) -> Result<(), CognitiveStoreError> {
        request.validate().map_err(invalid)?;
        readout.validate().map_err(invalid)?;
        let current = self
            .revalidate_lane_c_snapshot(access, scope, &acquired.cut, now_unix_seconds)
            .await?;
        if acquired.owner_agent_id != *self.owner_agent_id()
            || request.scope != acquired.scope
            || current.cut_digest() != acquired.owner_cut_digest.digest()
        {
            return Err(CognitiveStoreError::AccessDenied(
                "memory cell request owner or scope differs".to_string(),
            ));
        }
        let operation = readout
            .operation
            .ok_or_else(|| CognitiveStoreError::Invalid("memory operation absent".to_string()))?;
        let expected = acquired.required_sources(request, operation)?;
        if expected != readout.source_ids.iter().copied().collect() {
            return Err(CognitiveStoreError::Conflict(
                "memory readout dependencies differ from current typed address".to_string(),
            ));
        }
        match operation {
            MemoryOperationV1::Current | MemoryOperationV1::History | MemoryOperationV1::Change => {
                let current = acquired.current(&request.entity, MemoryCellKindV1::Event);
                let historical = acquired.at(&request.entity, MemoryCellKindV1::Event, request.at);
                let value = if operation == MemoryOperationV1::Current {
                    current.map(|item| item.record.value.clone())
                } else if operation == MemoryOperationV1::History {
                    historical.map(|item| item.record.value.clone())
                } else {
                    current.and_then(|latest| {
                        acquired
                            .at(&request.entity, MemoryCellKindV1::Event, request.since)
                            .and_then(|prior| {
                                Some(Value::from(
                                    latest.record.value.as_i64()? - prior.record.value.as_i64()?,
                                ))
                            })
                    })
                };
                if readout.prediction_kind != MemoryPredictionKindV1::SourceEvidence
                    || value.as_ref() != Some(&readout.value)
                {
                    return Err(CognitiveStoreError::Conflict(
                        "exact owner value or prediction label differs".to_string(),
                    ));
                }
            }
            MemoryOperationV1::Semantic | MemoryOperationV1::Procedure => {
                let kind = if operation == MemoryOperationV1::Semantic {
                    MemoryCellKindV1::Semantic
                } else {
                    MemoryCellKindV1::Procedure
                };
                validate_memory_cell_value_v1(kind, &readout.value).map_err(invalid)?;
                if readout.prediction_kind != MemoryPredictionKindV1::ModelPrediction {
                    return Err(CognitiveStoreError::Conflict(
                        "parameter readout must retain prediction status".to_string(),
                    ));
                }
            }
            MemoryOperationV1::Apply => {
                if request.max_cells < 3
                    || readout.prediction_kind != MemoryPredictionKindV1::Mixed
                    || readout.value.as_i64().is_none()
                {
                    return Err(CognitiveStoreError::Conflict(
                        "composition cell budget, value or prediction label differs".to_string(),
                    ));
                }
            }
        }
        let verifier = CurrentCellSources {
            acquired,
            expected,
            bundle_digest,
        };
        revalidate_memory_readout_v1(request, readout, generation, bundle_digest, &verifier)
            .map_err(invalid)
    }
}

struct CurrentCellSources<'a> {
    acquired: &'a MemoryCellOwnerSnapshotV1,
    expected: BTreeSet<ContractDigestV1>,
    bundle_digest: ContractDigestV1,
}

impl MemorySourceVerifierV1 for CurrentCellSources<'_> {
    fn verify_current_source(
        &self,
        request: &MemoryRequestV1,
        source: ContractDigestV1,
        snapshot: ContractDigestV1,
    ) -> Result<(), HnmfContractError> {
        if snapshot != self.bundle_digest
            || request.scope != self.acquired.scope
            || !self.expected.contains(&source)
            || !self
                .acquired
                .records
                .iter()
                .any(|record| record.source_id == source && record.record.entity == request.entity)
        {
            return Err(HnmfContractError::Conflict(
                "current owner memory cell source",
            ));
        }
        Ok(())
    }
}

pub(crate) fn cell_stable_key(
    address: &MemoryCellAddressV1,
) -> Result<String, CognitiveStoreError> {
    if address.effective_at >= 1_u64 << 53 {
        return Err(CognitiveStoreError::Invalid(
            "memory cell address time bound".to_string(),
        ));
    }
    let bytes = serde_json::to_vec(address).map_err(unavailable)?;
    Ok(format!("memory-cell:v1:{}", Digest32::of_bytes(&bytes)))
}

fn decode_cell(content: &str) -> Result<Option<MemoryCellRecordV1>, CognitiveStoreError> {
    let Ok(value) = serde_json::from_str::<Value>(content) else {
        return Ok(None);
    };
    if value.get("schema").and_then(Value::as_str) != Some("hepta.memory.cell-record.v1") {
        return Ok(None);
    }
    let record: MemoryCellRecordV1 = serde_json::from_value(value)
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    record.validate().map_err(invalid)?;
    Ok(Some(record))
}

pub(crate) fn invalid(error: impl std::fmt::Display) -> CognitiveStoreError {
    CognitiveStoreError::Invalid(error.to_string())
}

//! Owner-created per-cell training dependencies. Serialized exports carry no
//! authority: only a fresh canonical snapshot can construct this projection.

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryInventoryOwnerRecordV1;
use crate::MemoryInventoryOwnerSnapshotV1;

/// A declared, bounded cell partition, not a caller-supplied source digest.
/// Membership is explicit: a new version or tombstone of any selected key is
/// relevant; writes outside this partition do not change its training identity.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryTrainingSelectorV11 {
    pub cell_id: ContractIdV1,
    pub kind: MemoryInventoryKindV1,
    pub keys: Vec<ContractIdV1>,
}

impl MemoryTrainingSelectorV11 {
    pub fn validate(&self) -> Result<(), CognitiveStoreError> {
        if !matches!(
            self.kind,
            MemoryInventoryKindV1::Semantic | MemoryInventoryKindV1::Procedure
        ) || self.keys.is_empty()
            || self.keys.len() > crate::MAX_MEMORY_INVENTORY_OWNER_HEADS
            || self.keys.windows(2).any(|pair| pair[0] >= pair[1])
        {
            return Err(CognitiveStoreError::Invalid(
                "V11 training selector kind, bound or order".to_string(),
            ));
        }
        Ok(())
    }
}

/// Clean-fit training view. There is intentionally no Deserialize implementation
/// or public field constructor. Incremental inherited dependencies are not
/// silently omitted: this profile only admits exact current-source clean fits.
#[derive(Clone, Debug, Serialize)]
pub struct MemoryTrainingProjectionV11 {
    schema: &'static str,
    owner_agent_id: AgentId,
    scope: ContractIdV1,
    selector: MemoryTrainingSelectorV11,
    projection_digest: ContractDigestV1,
    acquisition_cut_digest: ContractDigestV1,
    records: Vec<MemoryInventoryOwnerRecordV1>,
}

impl MemoryTrainingProjectionV11 {
    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }
    pub fn scope(&self) -> &ContractIdV1 {
        &self.scope
    }
    pub fn selector(&self) -> &MemoryTrainingSelectorV11 {
        &self.selector
    }
    pub fn digest(&self) -> ContractDigestV1 {
        self.projection_digest
    }
    pub fn acquisition_cut_digest(&self) -> ContractDigestV1 {
        self.acquisition_cut_digest
    }
    pub fn records(&self) -> &[MemoryInventoryOwnerRecordV1] {
        &self.records
    }
}

impl MemoryInventoryOwnerSnapshotV1 {
    /// Derive every current source of the declared partition from the complete
    /// authenticated owner snapshot. Latest/absence is resolved by the owner,
    /// including newer effective versions and tombstones, never by the trainer.
    pub fn training_projection_v11(
        &self,
        selector: &MemoryTrainingSelectorV11,
    ) -> Result<MemoryTrainingProjectionV11, CognitiveStoreError> {
        selector.validate()?;
        let records = selector
            .keys
            .iter()
            .map(|key| {
                self.current(key, selector.kind).cloned().ok_or_else(|| {
                    CognitiveStoreError::Conflict(
                        "V11 training key unavailable or withdrawn".to_string(),
                    )
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        let bytes = serde_json::to_vec(&(
            "hepta.memory.training-projection.v11",
            self.owner_agent_id(),
            self.scope(),
            selector,
            &records,
        ))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let projection_digest = ContractDigestV1::from_digest(Digest32::of_bytes(&bytes))
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        Ok(MemoryTrainingProjectionV11 {
            schema: "hepta.memory.training-projection.v11",
            owner_agent_id: self.owner_agent_id().clone(),
            scope: self.scope().clone(),
            selector: selector.clone(),
            projection_digest,
            acquisition_cut_digest: self.owner_cut_digest(),
            records,
        })
    }
}

impl CognitiveStore {
    /// Reacquire authorization and the complete owner view before deriving the
    /// same partition. An unrelated write may change the acquisition cut while
    /// preserving this training projection; a relevant write cannot do so.
    pub async fn revalidate_training_projection_v11(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        previous: &MemoryTrainingProjectionV11,
        now_unix_seconds: i64,
    ) -> Result<MemoryTrainingProjectionV11, CognitiveStoreError> {
        let snapshot = self
            .memory_inventory_snapshot(access, scope, now_unix_seconds)
            .await?;
        let current = snapshot.training_projection_v11(previous.selector())?;
        if current.owner_agent_id != previous.owner_agent_id
            || current.scope != previous.scope
            || current.projection_digest != previous.projection_digest
        {
            return Err(CognitiveStoreError::Conflict(
                "V11 training dependency changed".to_string(),
            ));
        }
        Ok(current)
    }
}

#[cfg(test)]
#[path = "memory_training_projection_v11_tests.rs"]
mod tests;

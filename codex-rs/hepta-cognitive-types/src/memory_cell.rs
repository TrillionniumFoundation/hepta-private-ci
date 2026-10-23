//! Typed Memory Cell contracts for shadow recall and bounded evolution.
//!
//! These values describe a cell's identity, lineage, bounded state and one
//! deterministic tick. They carry no writer, model, selection, promotion or
//! release authority. Facts remain in the source/revision ledger; a cell is a
//! rebuildable projection over that ledger.

use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::ModalityKindV1;
use crate::hnmf::ppm;
use crate::hnmf_learning::EngramPopulationV1;
use crate::hnmf_learning::PlasticityBatchV1;
use crate::hnmf_learning::TopologyOperationV1;
use crate::hnmf_learning::TopologyProposalStateV1;
use crate::hnmf_learning::TopologyProposalV1;

pub const MEMORY_CELL_MANIFEST_SCHEMA_VERSION: u32 = 1;
pub const MEMORY_CELL_TICK_SCHEMA_VERSION: u32 = 1;
pub const MEMORY_CELL_RECEIPT_SCHEMA_VERSION: u32 = 1;
pub const MEMORY_CELL_SPLIT_SCHEMA_VERSION: u32 = 1;
pub const MEMORY_CELL_SPLIT_CHILDREN: usize = 2;
pub const MAX_MEMORY_CELL_MODALITIES: usize = 9;
pub const MAX_MEMORY_CELL_POPULATIONS: usize = 7;
pub const MAX_MEMORY_CELL_ACTIVE_CELLS: usize = 64;
pub const MAX_MEMORY_CELL_STATE_BYTES: u32 = 1_048_576;
pub const MAX_MEMORY_CELL_TRANSIENT_BYTES: u32 = 524_288;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCellRoleV1 {
    Episodic,
    Semantic,
    Procedural,
    Predictive,
    CrossModal,
    MetaMemory,
    Utility,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCellStatusV1 {
    Selected,
    Abstained,
    Unavailable,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellManifestV1 {
    pub schema_version: u32,
    pub cell_id: ContractIdV1,
    pub role: MemoryCellRoleV1,
    pub parent_cell_id: Option<ContractIdV1>,
    pub shared_base_digest: ContractDigestV1,
    pub encoder_digest: ContractDigestV1,
    pub adapter_artifact_digest: ContractDigestV1,
    pub head_artifact_digest: ContractDigestV1,
    pub state_schema_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub lineage_digest: ContractDigestV1,
    pub modalities: BTreeSet<ModalityKindV1>,
    pub populations: BTreeSet<EngramPopulationV1>,
    pub graph_generation: ContractGenerationV1,
    pub model_generation: ContractGenerationV1,
    pub max_active_cells: u16,
    pub max_state_bytes: u32,
}

impl MemoryCellManifestV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != MEMORY_CELL_MANIFEST_SCHEMA_VERSION {
            return Err(HnmfContractError::Invalid("memory cell manifest schema"));
        }
        if self.parent_cell_id.as_ref() == Some(&self.cell_id) {
            return Err(HnmfContractError::Conflict("memory cell self-parent"));
        }
        validate_set(
            self.modalities.len(),
            MAX_MEMORY_CELL_MODALITIES,
            "memoryCellModalities",
        )?;
        validate_set(
            self.populations.len(),
            MAX_MEMORY_CELL_POPULATIONS,
            "memoryCellPopulations",
        )?;
        validate_budget(
            usize::from(self.max_active_cells),
            MAX_MEMORY_CELL_ACTIVE_CELLS,
            "maxActiveCells",
        )?;
        validate_budget(
            usize::try_from(self.max_state_bytes).unwrap_or(usize::MAX),
            usize::try_from(MAX_MEMORY_CELL_STATE_BYTES).unwrap_or(usize::MAX),
            "maxStateBytes",
        )?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellTickInputV1 {
    pub schema_version: u32,
    pub cell_id: ContractIdV1,
    pub graph_generation: ContractGenerationV1,
    pub model_generation: ContractGenerationV1,
    pub logical_sequence: u64,
    pub predecessor_checkpoint_digest: Option<ContractDigestV1>,
    pub input_digest: ContractDigestV1,
    pub cue_digest: ContractDigestV1,
    pub snapshot_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub objective_digest: ContractDigestV1,
    pub ndu_state_digest: ContractDigestV1,
    pub resource_budget_units: u32,
}

impl MemoryCellTickInputV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != MEMORY_CELL_TICK_SCHEMA_VERSION {
            return Err(HnmfContractError::Invalid("memory cell tick schema"));
        }
        if self.logical_sequence == 0 {
            return Err(HnmfContractError::ZeroValue("logicalSequence"));
        }
        if self.resource_budget_units == 0 {
            return Err(HnmfContractError::ZeroValue("resourceBudgetUnits"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellTickReceiptV1 {
    pub schema_version: u32,
    pub cell_id: ContractIdV1,
    pub graph_generation: ContractGenerationV1,
    pub model_generation: ContractGenerationV1,
    pub logical_sequence: u64,
    pub status: MemoryCellStatusV1,
    pub predecessor_checkpoint_digest: Option<ContractDigestV1>,
    pub successor_checkpoint_digest: Option<ContractDigestV1>,
    pub recall_packet_digest: Option<ContractDigestV1>,
    pub candidate_digest: Option<ContractDigestV1>,
    pub coverage_ppm: u32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub resident_bytes: u32,
    pub transient_bytes: u32,
}

impl MemoryCellTickReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != MEMORY_CELL_RECEIPT_SCHEMA_VERSION {
            return Err(HnmfContractError::Invalid("memory cell receipt schema"));
        }
        if self.logical_sequence == 0 {
            return Err(HnmfContractError::ZeroValue("logicalSequence"));
        }
        ppm(self.coverage_ppm, "memory cell coverage")?;
        ppm(self.confidence_ppm, "memory cell confidence")?;
        ppm(self.ood_ppm, "memory cell ood")?;
        if self.transient_bytes > MAX_MEMORY_CELL_TRANSIENT_BYTES {
            return Err(HnmfContractError::LimitExceeded {
                field: "transientBytes",
                actual: usize::try_from(self.transient_bytes).unwrap_or(usize::MAX),
                maximum: usize::try_from(MAX_MEMORY_CELL_TRANSIENT_BYTES).unwrap_or(usize::MAX),
            });
        }
        if self.resident_bytes > MAX_MEMORY_CELL_STATE_BYTES {
            return Err(HnmfContractError::LimitExceeded {
                field: "residentBytes",
                actual: usize::try_from(self.resident_bytes).unwrap_or(usize::MAX),
                maximum: usize::try_from(MAX_MEMORY_CELL_STATE_BYTES).unwrap_or(usize::MAX),
            });
        }
        match self.status {
            MemoryCellStatusV1::Selected => {
                if self.successor_checkpoint_digest.is_none()
                    || self.recall_packet_digest.is_none()
                    || self.candidate_digest.is_none()
                {
                    return Err(HnmfContractError::Missing(
                        "selected memory cell receipt successor",
                    ));
                }
            }
            MemoryCellStatusV1::Abstained => {
                if self.successor_checkpoint_digest.is_some() || self.recall_packet_digest.is_some()
                {
                    return Err(HnmfContractError::Conflict(
                        "abstained memory cell receipt output",
                    ));
                }
            }
            MemoryCellStatusV1::Unavailable => {
                if self.successor_checkpoint_digest.is_some() || self.recall_packet_digest.is_some()
                {
                    return Err(HnmfContractError::Conflict(
                        "unavailable memory cell receipt output",
                    ));
                }
            }
            MemoryCellStatusV1::Indeterminate => {
                if self.successor_checkpoint_digest.is_some() {
                    return Err(HnmfContractError::Conflict(
                        "indeterminate memory cell successor",
                    ));
                }
            }
        }
        Ok(())
    }

    /// Validate a tick receipt against its exact admitted definition and input.
    ///
    /// Structural receipt validation alone cannot establish the predecessor,
    /// source/forget frontiers, or the per-cell resident-state budget. This
    /// check is pure: it neither attests evidence ownership nor persists state.
    pub fn validate_against_manifest_and_input(
        &self,
        manifest: &MemoryCellManifestV1,
        input: &MemoryCellTickInputV1,
    ) -> Result<(), HnmfContractError> {
        manifest.validate()?;
        input.validate()?;
        self.validate()?;
        if input.cell_id != manifest.cell_id
            || input.graph_generation != manifest.graph_generation
            || input.model_generation != manifest.model_generation
            || input.source_frontier_digest != manifest.source_frontier_digest
            || input.forget_frontier_digest != manifest.forget_frontier_digest
        {
            return Err(HnmfContractError::Conflict(
                "memory cell manifest/input binding",
            ));
        }
        if self.cell_id != input.cell_id
            || self.graph_generation != input.graph_generation
            || self.model_generation != input.model_generation
            || self.logical_sequence != input.logical_sequence
            || self.predecessor_checkpoint_digest != input.predecessor_checkpoint_digest
        {
            return Err(HnmfContractError::Conflict("memory cell receipt/input binding"));
        }
        if self.resident_bytes > manifest.max_state_bytes {
            return Err(HnmfContractError::LimitExceeded {
                field: "residentBytes",
                actual: usize::try_from(self.resident_bytes).unwrap_or(usize::MAX),
                maximum: usize::try_from(manifest.max_state_bytes).unwrap_or(usize::MAX),
            });
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellSplitProposalV1 {
    pub schema_version: u32,
    pub proposal_id: ContractIdV1,
    pub parent_cell_id: ContractIdV1,
    pub child_cell_ids: Vec<ContractIdV1>,
    pub parent_manifest_digest: ContractDigestV1,
    pub child_manifest_digests: Vec<ContractDigestV1>,
    pub partition_digest: ContractDigestV1,
    pub state_transform_digest: ContractDigestV1,
    pub replay_snapshot_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub predecessor_graph_generation: ContractGenerationV1,
    pub next_graph_generation: ContractGenerationV1,
    pub predecessor_model_generation: ContractGenerationV1,
    pub next_model_generation: ContractGenerationV1,
    pub topology: TopologyProposalV1,
    pub plasticity: PlasticityBatchV1,
    pub independent_evaluation_digest: ContractDigestV1,
}

impl MemoryCellSplitProposalV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != MEMORY_CELL_SPLIT_SCHEMA_VERSION {
            return Err(HnmfContractError::Invalid("memory cell split schema"));
        }
        if self.child_cell_ids.len() != MEMORY_CELL_SPLIT_CHILDREN
            || self.child_manifest_digests.len() != self.child_cell_ids.len()
        {
            return Err(HnmfContractError::Invalid("memory cell split children"));
        }
        if self.parent_cell_id == self.child_cell_ids[0]
            || self.parent_cell_id == self.child_cell_ids[1]
            || self.child_cell_ids[0] >= self.child_cell_ids[1]
        {
            return Err(HnmfContractError::Conflict("memory cell split identity"));
        }
        if self.proposal_id != self.topology.proposal_id {
            return Err(HnmfContractError::Conflict(
                "memory cell split proposal binding",
            ));
        }
        if self.topology.operation != TopologyOperationV1::Split
            || self.topology.state == TopologyProposalStateV1::Rejected
            || self.topology.resource_delta.node_delta < 1
        {
            return Err(HnmfContractError::Conflict("memory cell split topology"));
        }
        if self.predecessor_graph_generation.next()? != self.next_graph_generation
            || self.plasticity.predecessor_generation != self.predecessor_model_generation
            || self.plasticity.next_generation != self.next_model_generation
        {
            return Err(HnmfContractError::Conflict(
                "memory cell split generation binding",
            ));
        }
        self.topology.validate()?;
        self.plasticity.validate()?;
        Ok(())
    }
}

fn validate_set(
    actual: usize,
    maximum: usize,
    field: &'static str,
) -> Result<(), HnmfContractError> {
    if actual == 0 || actual > maximum {
        return Err(HnmfContractError::LimitExceeded {
            field,
            actual,
            maximum,
        });
    }
    Ok(())
}

fn validate_budget(
    actual: usize,
    maximum: usize,
    field: &'static str,
) -> Result<(), HnmfContractError> {
    if actual == 0 || actual > maximum {
        return Err(HnmfContractError::LimitExceeded {
            field,
            actual,
            maximum,
        });
    }
    Ok(())
}

#[cfg(test)]
#[path = "memory_cell_tests.rs"]
mod tests;

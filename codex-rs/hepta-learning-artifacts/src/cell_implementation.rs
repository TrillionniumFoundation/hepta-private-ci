//! Local training restrictions shared by semantic and temporal Cell producers.
//! A valid candidate is not selected or installed. Native owner cutover still
//! requires its existing fenced, authenticated publication/readback path.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellBundleCutoverPlanV1;
use crate::CellBundleError;
use crate::CellCompatibilityBundleV1;
use crate::CellStatePartitionV1;
use crate::CellStateTransitionV1;
use crate::prepare_cell_bundle_cutover_v1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SemanticTrainablePartV1 {
    Heads,
    CellAdapterAndHeads,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TemporalCellKernelV1 {
    Gru,
    /// A simple diagonal recurrence, not a claim of S4D or Mamba parity.
    DiagonalSsm,
    /// Registration does not establish numerical or comparative qualification.
    HcsnResearch,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeterministicCellKindV1 {
    Retrieval,
    RuleVerifier,
    Numerical,
    ToolWrapper,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellImplementationFamilyV1 {
    SharedSemantic { trainable: SemanticTrainablePartV1 },
    StatefulTemporal { kernel: TemporalCellKernelV1 },
    Deterministic { kind: DeterministicCellKindV1 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellLocalUpdateErrorV1 {
    Bundle(CellBundleError),
    NotTrainable,
    WrongSuccessor,
    FrozenComponentChanged,
    NoParameterChange,
}

impl fmt::Display for CellLocalUpdateErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for CellLocalUpdateErrorV1 {}
impl From<CellBundleError> for CellLocalUpdateErrorV1 {
    fn from(value: CellBundleError) -> Self {
        Self::Bundle(value)
    }
}

/// Validate the changed component commitments against a producer's frozen
/// local training scope. This does not inspect tensor bytes or prove a gradient.
pub fn validate_cell_local_update_v1(
    family: CellImplementationFamilyV1,
    predecessor: &CellCompatibilityBundleV1,
    successor: &CellCompatibilityBundleV1,
) -> Result<Digest32, CellLocalUpdateErrorV1> {
    let predecessor_digest = predecessor.digest()?;
    let successor_digest = successor.digest()?;
    if successor.rollback_predecessor != Some(predecessor_digest)
        || predecessor.generation.get().checked_add(1) != Some(successor.generation.get())
    {
        return Err(CellLocalUpdateErrorV1::WrongSuccessor);
    }
    let before = &predecessor.components;
    let after = &successor.components;
    let mut permitted = before.clone();
    match family {
        CellImplementationFamilyV1::SharedSemantic { trainable } => {
            permitted.heads = after.heads;
            match trainable {
                SemanticTrainablePartV1::Heads => {}
                SemanticTrainablePartV1::CellAdapterAndHeads => {
                    permitted.cell_adapter = after.cell_adapter;
                }
            }
        }
        CellImplementationFamilyV1::StatefulTemporal { kernel: _ } => {
            permitted.base = after.base;
            permitted.heads = after.heads;
        }
        CellImplementationFamilyV1::Deterministic { kind: _ } => {
            return Err(CellLocalUpdateErrorV1::NotTrainable);
        }
    }
    if permitted != *after {
        return Err(CellLocalUpdateErrorV1::FrozenComponentChanged);
    }
    if before == after {
        return Err(CellLocalUpdateErrorV1::NoParameterChange);
    }
    Ok(successor_digest)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellLocalResetV1 {
    pub initializer: Digest32,
    pub target_checkpoint: Digest32,
}

/// Prepare an explicit state reset after a local parameter update. Callers
/// cannot preserve a hidden state produced by another parameter generation.
/// Qualified migrations keep using the existing separate cutover API.
pub fn prepare_cell_local_reset_v1(
    family: CellImplementationFamilyV1,
    operation_id: StableId,
    state_owner: StableId,
    state_partition: CellStatePartitionV1,
    predecessor: &CellCompatibilityBundleV1,
    successor: &CellCompatibilityBundleV1,
    reset: CellLocalResetV1,
) -> Result<CellBundleCutoverPlanV1, CellLocalUpdateErrorV1> {
    validate_cell_local_update_v1(family, predecessor, successor)?;
    Ok(prepare_cell_bundle_cutover_v1(
        operation_id,
        state_owner,
        state_partition,
        predecessor,
        successor,
        CellStateTransitionV1::Reset {
            initializer: reset.initializer,
            target_checkpoint: reset.target_checkpoint,
        },
    )?)
}

#[cfg(test)]
#[path = "cell_implementation_tests.rs"]
mod tests;

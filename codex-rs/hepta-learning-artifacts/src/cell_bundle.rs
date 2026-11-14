//! Immutable compatibility bundles and scoped state cutover plans.
//!
//! Plans grant no install, selection or writer authority. The existing state
//! owner fences old writers and executes an admitted plan before publishing a
//! durable receipt. Readback validation does not authenticate that receipt.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellBundleComponentsV1 {
    pub base: Digest32,
    pub organ_adapter: Option<Digest32>,
    pub cell_adapter: Option<Digest32>,
    pub heads: Digest32,
    /// Layer names, shapes, ranks, scales and adapter composition order.
    pub composition: Digest32,
    pub encoder: Digest32,
    pub tokenizer: Digest32,
    pub normalizer: Digest32,
    pub calibration: Digest32,
    pub numeric_profile: Digest32,
    pub output_schema: Digest32,
    pub state_schema: Digest32,
    /// Recurrent-state meaning, including reset and homeostatic policy.
    pub state_semantics: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellTrainingLineageV1 {
    pub source_bundle: Digest32,
    pub dataset: Digest32,
    pub update_rule: Digest32,
    /// Frozen protocol, not its result: evaluation signs the completed bundle.
    pub evaluation_profile: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellCompatibilityBundleV1 {
    pub artifact_id: StableId,
    pub generation: Generation,
    pub components: CellBundleComponentsV1,
    /// Both lineage and rollback are absent only for an explicit genesis.
    pub training_lineage: Option<CellTrainingLineageV1>,
    pub rollback_predecessor: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellBundleError {
    EmptyDigest,
    MissingLineage,
    WrongPredecessor,
    GenerationNotAdvanced,
    IncompatiblePreservedState,
    InvalidStateTransition,
    WrongOwnerReceipt,
}

impl fmt::Display for CellBundleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for CellBundleError {}

impl CellCompatibilityBundleV1 {
    pub fn digest(&self) -> Result<Digest32, CellBundleError> {
        let c = &self.components;
        let required = [
            c.base,
            c.heads,
            c.composition,
            c.encoder,
            c.tokenizer,
            c.normalizer,
            c.calibration,
            c.numeric_profile,
            c.output_schema,
            c.state_schema,
            c.state_semantics,
        ];
        if required.iter().copied().any(Digest32::is_zero)
            || [c.organ_adapter, c.cell_adapter, self.rollback_predecessor]
                .into_iter()
                .flatten()
                .any(Digest32::is_zero)
        {
            return Err(CellBundleError::EmptyDigest);
        }
        if self.training_lineage.is_some() != self.rollback_predecessor.is_some() {
            return Err(CellBundleError::MissingLineage);
        }
        let mut bytes = b"hepta.cell.compatibility-bundle.v1\0".to_vec();
        append_id(&mut bytes, &self.artifact_id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for digest in required {
            bytes.extend_from_slice(digest.as_array());
        }
        for digest in [c.organ_adapter, c.cell_adapter, self.rollback_predecessor] {
            bytes.push(u8::from(digest.is_some()));
            if let Some(digest) = digest {
                bytes.extend_from_slice(digest.as_array());
            }
        }
        if let Some(lineage) = &self.training_lineage {
            for digest in [
                lineage.source_bundle,
                lineage.dataset,
                lineage.update_rule,
                lineage.evaluation_profile,
            ] {
                if digest.is_zero() {
                    return Err(CellBundleError::EmptyDigest);
                }
                bytes.extend_from_slice(digest.as_array());
            }
            if Some(lineage.source_bundle) != self.rollback_predecessor {
                return Err(CellBundleError::WrongPredecessor);
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStatePartitionV1 {
    pub principal_id: StableId,
    pub agent_id: StableId,
    pub cell_id: StableId,
    pub run_id: StableId,
}

impl CellStatePartitionV1 {
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell.state-partition.v1\0".to_vec();
        for id in [
            &self.principal_id,
            &self.agent_id,
            &self.cell_id,
            &self.run_id,
        ] {
            append_id(&mut bytes, id);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellStateTransitionV1 {
    Preserve {
        checkpoint: Digest32,
    },
    Reset {
        initializer: Digest32,
        target_checkpoint: Digest32,
    },
    Migrate {
        transform: Digest32,
        source_checkpoint: Digest32,
        target_checkpoint: Digest32,
        qualification: Digest32,
    },
}

/// Sealed after validation: callers cannot relabel a plan while retaining its
/// old digest, or substitute another cell partition before readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellBundleCutoverPlanV1 {
    operation_id: StableId,
    state_owner: StableId,
    state_partition: CellStatePartitionV1,
    predecessor_bundle: Digest32,
    successor_bundle: Digest32,
    successor_generation: Generation,
    transition: CellStateTransitionV1,
    plan_digest: Digest32,
}

impl CellBundleCutoverPlanV1 {
    pub fn operation_id(&self) -> &StableId {
        &self.operation_id
    }
    pub fn state_owner(&self) -> &StableId {
        &self.state_owner
    }
    pub fn state_partition(&self) -> &CellStatePartitionV1 {
        &self.state_partition
    }
    pub fn predecessor_bundle(&self) -> Digest32 {
        self.predecessor_bundle
    }
    pub fn successor_bundle(&self) -> Digest32 {
        self.successor_bundle
    }
    pub fn successor_generation(&self) -> Generation {
        self.successor_generation
    }
    pub fn transition(&self) -> &CellStateTransitionV1 {
        &self.transition
    }
    pub fn plan_digest(&self) -> Digest32 {
        self.plan_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellBundleCutoverReceiptV1 {
    pub operation_id: StableId,
    pub state_owner: StableId,
    pub state_partition_digest: Digest32,
    pub plan_digest: Digest32,
    pub observed_bundle: Digest32,
    pub observed_generation: Generation,
    pub observed_checkpoint: Digest32,
    /// Digest of the authenticated state-owner durable publication.
    pub owner_receipt_digest: Digest32,
}

pub fn prepare_cell_bundle_cutover_v1(
    operation_id: StableId,
    state_owner: StableId,
    state_partition: CellStatePartitionV1,
    predecessor: &CellCompatibilityBundleV1,
    successor: &CellCompatibilityBundleV1,
    transition: CellStateTransitionV1,
) -> Result<CellBundleCutoverPlanV1, CellBundleError> {
    let predecessor_bundle = predecessor.digest()?;
    let successor_bundle = successor.digest()?;
    if successor.rollback_predecessor != Some(predecessor_bundle) {
        return Err(CellBundleError::WrongPredecessor);
    }
    if successor.generation <= predecessor.generation {
        return Err(CellBundleError::GenerationNotAdvanced);
    }
    let mut bytes = b"hepta.cell.bundle-cutover.v1\0".to_vec();
    append_id(&mut bytes, &operation_id);
    append_id(&mut bytes, &state_owner);
    bytes.extend_from_slice(state_partition.digest().as_array());
    bytes.extend_from_slice(predecessor_bundle.as_array());
    bytes.extend_from_slice(successor_bundle.as_array());
    bytes.extend_from_slice(&successor.generation.get().to_be_bytes());
    let state_digests = match &transition {
        CellStateTransitionV1::Preserve { checkpoint } => {
            // Equal dimensions do not imply equal state meaning.
            if predecessor.components != successor.components {
                return Err(CellBundleError::IncompatiblePreservedState);
            }
            bytes.push(0);
            vec![*checkpoint]
        }
        CellStateTransitionV1::Reset {
            initializer,
            target_checkpoint,
        } => {
            bytes.push(1);
            vec![*initializer, *target_checkpoint]
        }
        CellStateTransitionV1::Migrate {
            transform,
            source_checkpoint,
            target_checkpoint,
            qualification,
        } => {
            bytes.push(2);
            vec![
                *transform,
                *source_checkpoint,
                *target_checkpoint,
                *qualification,
            ]
        }
    };
    if state_digests.iter().copied().any(Digest32::is_zero) {
        return Err(CellBundleError::InvalidStateTransition);
    }
    for digest in state_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(CellBundleCutoverPlanV1 {
        operation_id,
        state_owner,
        state_partition,
        predecessor_bundle,
        successor_bundle,
        successor_generation: successor.generation,
        transition,
        plan_digest: Digest32::of_bytes(&bytes),
    })
}

/// Check all planned values after the state owner authenticates its receipt.
pub fn validate_cell_bundle_readback_v1(
    plan: &CellBundleCutoverPlanV1,
    receipt: &CellBundleCutoverReceiptV1,
) -> Result<(), CellBundleError> {
    let checkpoint = match plan.transition {
        CellStateTransitionV1::Preserve { checkpoint } => checkpoint,
        CellStateTransitionV1::Reset {
            target_checkpoint, ..
        }
        | CellStateTransitionV1::Migrate {
            target_checkpoint, ..
        } => target_checkpoint,
    };
    if receipt.operation_id != plan.operation_id
        || receipt.state_owner != plan.state_owner
        || receipt.state_partition_digest != plan.state_partition.digest()
        || receipt.plan_digest != plan.plan_digest
        || receipt.observed_bundle != plan.successor_bundle
        || receipt.observed_generation != plan.successor_generation
        || receipt.observed_checkpoint != checkpoint
        || receipt.owner_receipt_digest.is_zero()
    {
        return Err(CellBundleError::WrongOwnerReceipt);
    }
    Ok(())
}

pub(crate) fn append_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

#[cfg(test)]
#[path = "cell_bundle_tests.rs"]
mod tests;

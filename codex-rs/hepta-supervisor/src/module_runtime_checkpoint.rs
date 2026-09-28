use std::collections::BTreeMap;

use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeModulePromotionWitnessV1;
use codex_hepta_control_plane::RuntimeModuleRegistryCheckpointV1;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::StableId;

use super::MAX_PENDING_TOPOLOGIES;
use super::RuntimeModuleSupervisorErrorV1;
use super::RuntimeModuleSupervisorV1;
use super::validate_runtime_dependency_graph;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleSelectionCheckpointV1 {
    pub module_id: StableId,
    pub generation: Generation,
    pub selection_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModulePendingPromotionCheckpointV1 {
    pub candidate_digest: Digest32,
    pub module_id: StableId,
    pub witness: RuntimeModulePromotionWitnessV1,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleRetirementCheckpointV1 {
    pub module_id: StableId,
    pub generation: Generation,
    pub witness_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleSupervisorCheckpointV1 {
    pub registry: RuntimeModuleRegistryCheckpointV1,
    pub selections: Vec<RuntimeModuleSelectionCheckpointV1>,
    pub pending_topologies: Vec<RuntimeTopologyCandidateV1>,
    pub pending_promotions: Vec<RuntimeModulePendingPromotionCheckpointV1>,
    pub retirement_ready: Vec<RuntimeModuleRetirementCheckpointV1>,
}

impl RuntimeModuleSupervisorV1 {
    pub fn checkpoint(&self) -> RuntimeModuleSupervisorCheckpointV1 {
        RuntimeModuleSupervisorCheckpointV1 {
            registry: self.registry.checkpoint(),
            selections: self
                .selections
                .iter()
                .map(|((module_id, generation), selection_digest)| {
                    RuntimeModuleSelectionCheckpointV1 {
                        module_id: module_id.clone(),
                        generation: *generation,
                        selection_digest: *selection_digest,
                    }
                })
                .collect(),
            pending_topologies: self.pending_topologies.values().cloned().collect(),
            pending_promotions: self
                .pending_promotions
                .iter()
                .map(|((candidate_digest, module_id), witness)| {
                    RuntimeModulePendingPromotionCheckpointV1 {
                        candidate_digest: *candidate_digest,
                        module_id: module_id.clone(),
                        witness: witness.clone(),
                    }
                })
                .collect(),
            retirement_ready: self
                .retirement_ready
                .iter()
                .map(|((module_id, generation), witness_digest)| {
                    RuntimeModuleRetirementCheckpointV1 {
                        module_id: module_id.clone(),
                        generation: *generation,
                        witness_digest: *witness_digest,
                    }
                })
                .collect(),
        }
    }

    pub fn restore_checkpoint(
        checkpoint: RuntimeModuleSupervisorCheckpointV1,
    ) -> Result<Self, RuntimeModuleSupervisorErrorV1> {
        if checkpoint.pending_topologies.len() > MAX_PENDING_TOPOLOGIES {
            return Err(RuntimeModuleSupervisorErrorV1::CheckpointInvalid);
        }
        let registry = RuntimeModuleRegistryV1::restore_checkpoint(checkpoint.registry)?;
        validate_runtime_dependency_graph(&registry.snapshot())?;
        let mut selections = BTreeMap::new();
        for selection in checkpoint.selections {
            if selection.selection_digest.is_zero()
                || registry
                    .record(&selection.module_id, selection.generation)
                    .is_none()
                || selections
                    .insert(
                        (selection.module_id, selection.generation),
                        selection.selection_digest,
                    )
                    .is_some()
            {
                return Err(RuntimeModuleSupervisorErrorV1::CheckpointDuplicate);
            }
        }

        let mut pending_topologies = BTreeMap::new();
        for candidate in checkpoint.pending_topologies {
            candidate.validate()?;
            if pending_topologies
                .insert(candidate.candidate_digest, candidate)
                .is_some()
            {
                return Err(RuntimeModuleSupervisorErrorV1::CheckpointDuplicate);
            }
        }

        let mut pending_promotions = BTreeMap::new();
        for promotion in checkpoint.pending_promotions {
            let Some(candidate) = pending_topologies.get(&promotion.candidate_digest) else {
                return Err(RuntimeModuleSupervisorErrorV1::CheckpointInvalid);
            };
            let Some(record) =
                registry.record(&promotion.module_id, candidate.candidate_generation)
            else {
                return Err(RuntimeModuleSupervisorErrorV1::CheckpointInvalid);
            };
            if record.lifecycle != RuntimeModuleLifecycleV1::Canary {
                return Err(RuntimeModuleSupervisorErrorV1::CheckpointInvalid);
            }
            promotion.witness.validate_for(&record.abi)?;
            if pending_promotions
                .insert(
                    (promotion.candidate_digest, promotion.module_id),
                    promotion.witness,
                )
                .is_some()
            {
                return Err(RuntimeModuleSupervisorErrorV1::CheckpointDuplicate);
            }
        }

        let mut retirement_ready = BTreeMap::new();
        for retirement in checkpoint.retirement_ready {
            if retirement.witness_digest.is_zero()
                || registry.active_generation(&retirement.module_id) != Some(retirement.generation)
                || retirement_ready
                    .insert(
                        (retirement.module_id, retirement.generation),
                        retirement.witness_digest,
                    )
                    .is_some()
            {
                return Err(RuntimeModuleSupervisorErrorV1::CheckpointInvalid);
            }
        }

        let mut restored = Self {
            registry,
            selections,
            pending_topologies,
            pending_promotions,
            retirement_ready,
        };
        restored.prune_lifecycle_metadata();
        Ok(restored)
    }
}

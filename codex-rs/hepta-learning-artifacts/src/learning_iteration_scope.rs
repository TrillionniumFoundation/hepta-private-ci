//! Explicit medium-cadence restrictions over the original immutable iteration.
//! A scope is a frozen constraint, never an artifact or consensus activation grant.

use codex_hepta_types::Digest32;

use crate::CellBundleComponentsV1;
use crate::LearningIterationCoordinatorV1;
use crate::LearningIterationError;
use crate::LearningIterationObservationV1;
use crate::LearningIterationOwnersV1;
use crate::LearningIterationRequestV1;
use crate::LearningIterationSnapshotV1;
use crate::learning_iteration_digest::initial_digest;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningUpdateScopeV2 {
    Cell,
    Organ,
    /// Classification only. The medium-cadence owner cannot admit base releases.
    BaseRelease,
}

/// Host-frozen exact request, owner set, update rule and component boundary.
/// The original artifact owner still checks actual tensor bytes, masks, state
/// migration and adoption. Component digests alone do not prove compatibility.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenLearningScopeV2 {
    initial_head: Digest32,
    components: CellBundleComponentsV1,
    scope: LearningUpdateScopeV2,
    update_rule: Digest32,
    binding: Digest32,
}

impl FrozenLearningScopeV2 {
    pub fn freeze(
        request: &LearningIterationRequestV1,
        owners: &LearningIterationOwnersV1,
        scope: LearningUpdateScopeV2,
        update_rule: Digest32,
    ) -> Result<Self, LearningIterationError> {
        let tag = match scope {
            LearningUpdateScopeV2::Cell => 1,
            LearningUpdateScopeV2::Organ => 2,
            LearningUpdateScopeV2::BaseRelease => {
                return Err(LearningIterationError::SlowReleaseRequired);
            }
        };
        if update_rule.is_zero() {
            return Err(LearningIterationError::EmptyEvidence);
        }
        let initial = LearningIterationCoordinatorV1::new(request.clone(), owners.clone())?;
        let initial_head = initial.snapshot().head_digest;
        let binding = Digest32::of_parts(&[
            b"hepta.learning.frozen-update-scope.v2\0",
            initial_head.as_array(),
            &[tag],
            update_rule.as_array(),
        ]);
        Ok(Self {
            initial_head,
            components: request.selected_bundle.components.clone(),
            scope,
            update_rule,
            binding,
        })
    }

    pub fn binding(&self) -> Digest32 {
        self.binding
    }

    pub fn validate_request(
        &self,
        request: &LearningIterationRequestV1,
        owners: &LearningIterationOwnersV1,
    ) -> Result<(), LearningIterationError> {
        if initial_digest(request, owners)? != self.initial_head {
            return Err(LearningIterationError::UpdateScopeMismatch);
        }
        Ok(())
    }

    /// Check before advancing to evaluation or publishing another checkpoint.
    pub fn validate_observation(
        &self,
        observation: &LearningIterationObservationV1,
    ) -> Result<(), LearningIterationError> {
        if let LearningIterationObservationV1::TrainingNoUpdateV2(outcome) = observation
            && outcome.update_rule != self.update_rule
        {
            return Err(LearningIterationError::UpdateScopeMismatch);
        }
        if let LearningIterationObservationV1::Training { candidate, .. } = observation {
            let mut preserved = candidate.components.clone();
            // These changed components remain subject to the existing tensor,
            // evaluation, compatibility and publication owners.
            preserved.heads = self.components.heads;
            preserved.calibration = self.components.calibration;
            preserved.composition = self.components.composition;
            match self.scope {
                LearningUpdateScopeV2::Cell => {
                    preserved.cell_adapter = self.components.cell_adapter;
                }
                LearningUpdateScopeV2::Organ => {
                    preserved.organ_adapter = self.components.organ_adapter;
                }
                LearningUpdateScopeV2::BaseRelease => {
                    return Err(LearningIterationError::SlowReleaseRequired);
                }
            }
            if preserved != self.components
                || candidate
                    .training_lineage
                    .as_ref()
                    .map(|lineage| lineage.update_rule)
                    != Some(self.update_rule)
            {
                return Err(LearningIterationError::UpdateScopeMismatch);
            }
        }
        Ok(())
    }

    /// Restoring a later cut rechecks every original candidate, even when its
    /// evaluator eventually returned NoUpdate. That result cannot widen scope.
    pub fn validate_snapshot(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), LearningIterationError> {
        self.validate_request(&snapshot.request, &snapshot.owners)?;
        for receipt in &snapshot.receipts {
            self.validate_observation(&receipt.observation)?;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "learning_iteration_scope_tests.rs"]
mod tests;

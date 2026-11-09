//! Additional required checks inside the original registered Root case.
//!
//! The original non-Root child performs every checkpoint mutation. These
//! checks retain the real owner across those existing phases and only restore
//! CURRENT. No new test, ignore marker, registration, CAS, or process is added.
//! Synthetic learning payloads establish no training or receipt authority.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::fixture::Fixture;
use crate::AgentdError;
use crate::joint_text_training_owner::JointTextCheckpointBindingV1;

pub(super) struct CheckpointGuardChecks {
    previous: Option<JointTextCheckpointBindingV1>,
}

impl CheckpointGuardChecks {
    pub(super) fn from_vacant(
        fixture: &Fixture,
        initial: &LearningIterationSnapshotV1,
    ) -> anyhow::Result<Self> {
        let owner = Arc::new(fixture.owner()?);
        assert_eq!(owner.restore(&initial.request)?, None);
        assert!(matches!(
            JointTextCheckpointBindingV1::bind(Arc::clone(&owner), initial.clone()),
            Err(AgentdError::GenerationFenced(_))
        ));
        // Binding must not install genesis to make an absent CURRENT match.
        assert_eq!(owner.restore(&initial.request)?, None);
        Ok(Self { previous: None })
    }

    pub(super) fn observe_original_phase(
        &mut self,
        fixture: &Fixture,
        expected: &LearningIterationSnapshotV1,
    ) -> anyhow::Result<()> {
        if let Some(previous) = self.previous.as_ref() {
            if previous.iteration_snapshot() == expected {
                // The original revoked/lost-ACK paths may leave data unchanged.
                // This proves only fresh data equality, never live permission.
                previous.require_current()?;
            } else {
                // The same ordinary child has already committed the next
                // original phase. A cached admission must now fail repeatedly.
                assert!(matches!(
                    previous.require_current(),
                    Err(AgentdError::GenerationFenced(_))
                ));
                assert!(matches!(
                    previous.require_current(),
                    Err(AgentdError::GenerationFenced(_))
                ));
            }
        }
        let owner = Arc::new(fixture.owner()?);
        assert_eq!(owner.restore(&expected.request)?, Some(expected.clone()));
        let current = JointTextCheckpointBindingV1::bind(Arc::clone(&owner), expected.clone())?;
        assert_eq!(current.iteration_snapshot(), expected);
        current.require_current()?;

        // Matching only head_digest must not admit different complete data.
        let mut same_head_different_owners = expected.clone();
        same_head_different_owners.owners.trainer = StableId::new("foreign-joint-trainer")?;
        assert_eq!(same_head_different_owners.head_digest, expected.head_digest);
        assert!(matches!(
            JointTextCheckpointBindingV1::bind(Arc::clone(&owner), same_head_different_owners),
            Err(AgentdError::GenerationFenced(_))
        ));

        let mut foreign_scope = expected.clone();
        foreign_scope.request.operation_id = StableId::new("foreign-joint-operation")?;
        assert!(matches!(
            JointTextCheckpointBindingV1::bind(Arc::clone(&owner), foreign_scope),
            Err(AgentdError::GenerationFenced(_))
        ));
        // Neither rejection nor checking a retained stale guard writes CURRENT.
        assert_eq!(owner.restore(&expected.request)?, Some(expected.clone()));
        self.previous = Some(current);
        Ok(())
    }
}

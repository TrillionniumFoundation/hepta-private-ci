//! Fixed ordinary panel membership and opaque original readback values.

use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::OriginalProductEvaluationExecutionEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::CellGenerationScopeV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::super::Prepared;
use super::Error;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::OriginalCircuitEvaluationCohortCurrentV1;

pub(super) const MAX_RETENTION_TASKS: usize = 16;

/// Original task and frozen plan identities, fixed before training. The host
/// binds this complete membership through the original evaluation-profile pin.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellEvaluationPanelTaskV1 {
    pub plan_id: StableId,
    pub task_digest: Digest32,
    pub cohort_rule_digest: Digest32,
}

/// No deserializer or membership setter exists. The canonical profile can be
/// registered in the original request before the candidate or any result exists.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellEvaluationPanelRegistrationV1 {
    primary: OriginalCellEvaluationPanelTaskV1,
    retention: Vec<OriginalCellEvaluationPanelTaskV1>,
    profile: Digest32,
}

impl OriginalCellEvaluationPanelRegistrationV1 {
    pub fn new(
        primary: OriginalCellEvaluationPanelTaskV1,
        mut retention: Vec<OriginalCellEvaluationPanelTaskV1>,
    ) -> Result<Self, Error> {
        if retention.is_empty() || retention.len() > MAX_RETENTION_TASKS {
            return Err(Error::Binding("nonempty bounded original retention panel"));
        }
        retention.sort_by(|left, right| left.plan_id.cmp(&right.plan_id));
        let mut plans = BTreeSet::new();
        let mut tasks = BTreeSet::new();
        let mut bytes = b"hepta.agentd.original-cell-evaluation-panel-profile.v1\0".to_vec();
        bytes.extend_from_slice(&(retention.len() as u64).to_be_bytes());
        for task in std::iter::once(&primary).chain(retention.iter()) {
            if task.task_digest.is_zero()
                || task.cohort_rule_digest.is_zero()
                || !plans.insert(task.plan_id.clone())
                || !tasks.insert(task.task_digest)
            {
                return Err(Error::Binding("distinct original B and retention tasks"));
            }
            let name = task.plan_id.as_str().as_bytes();
            bytes.extend_from_slice(&(name.len() as u64).to_be_bytes());
            bytes.extend_from_slice(name);
            bytes.extend_from_slice(task.task_digest.as_array());
            bytes.extend_from_slice(task.cohort_rule_digest.as_array());
        }
        Ok(Self {
            primary,
            retention,
            profile: Digest32::of_bytes(&bytes),
        })
    }

    pub fn primary(&self) -> &OriginalCellEvaluationPanelTaskV1 {
        &self.primary
    }

    pub fn retention(&self) -> &[OriginalCellEvaluationPanelTaskV1] {
        &self.retention
    }

    pub fn evaluation_profile(&self) -> Digest32 {
        self.profile
    }
}

/// Actual readback from one consumed member, not a caller-supplied receipt DTO.
/// The full original signatures and execution remain pinned, including windows.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellEvaluationPanelMemberReadbackV1 {
    pub(super) task: OriginalCellEvaluationPanelTaskV1,
    pub(super) prepared: Prepared,
    pub(super) qualification: CellEvaluationQualificationV1,
    pub(super) product_evidence: SignedEvaluationEvidenceV1,
    pub(super) execution_evidence: OriginalProductEvaluationExecutionEvidenceV1,
    pub(super) cells: [Digest32; 2],
    pub(super) scopes: [CellGenerationScopeV2; 2],
    pub(super) cohort: OriginalCircuitEvaluationCohortCurrentV1,
}

impl OriginalCellEvaluationPanelMemberReadbackV1 {
    pub fn task(&self) -> &OriginalCellEvaluationPanelTaskV1 {
        &self.task
    }

    pub fn evaluation(&self) -> &CellEvaluationReceiptV1 {
        &self.prepared.evaluation
    }

    pub fn qualification(&self) -> &CellEvaluationQualificationV1 {
        &self.qualification
    }

    pub fn product_evidence(&self) -> &SignedEvaluationEvidenceV1 {
        &self.product_evidence
    }

    pub fn execution_evidence(&self) -> &OriginalProductEvaluationExecutionEvidenceV1 {
        &self.execution_evidence
    }
}

/// One point-in-time panel cut. It is not evidence that B was dispatched by
/// this reader, an adoption decision, a FinalUse grant, or a rollback oracle.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellEvaluationPanelReadbackV1 {
    pub(super) binding: Digest32,
    pub(super) registration: OriginalCellEvaluationPanelRegistrationV1,
    pub(super) training: LearningIterationSnapshotV1,
    pub(super) training_evidence: SignedLearningEvidenceV1,
    pub(super) primary: OriginalCellEvaluationPanelMemberReadbackV1,
    pub(super) retention: Vec<OriginalCellEvaluationPanelMemberReadbackV1>,
}

impl OriginalCellEvaluationPanelReadbackV1 {
    pub fn binding(&self) -> Digest32 {
        self.binding
    }

    pub fn registration(&self) -> &OriginalCellEvaluationPanelRegistrationV1 {
        &self.registration
    }

    pub fn training(&self) -> &LearningIterationSnapshotV1 {
        &self.training
    }

    pub fn training_evidence(&self) -> &SignedLearningEvidenceV1 {
        &self.training_evidence
    }

    pub fn primary(&self) -> &OriginalCellEvaluationPanelMemberReadbackV1 {
        &self.primary
    }

    pub fn retention(&self) -> &[OriginalCellEvaluationPanelMemberReadbackV1] {
        &self.retention
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

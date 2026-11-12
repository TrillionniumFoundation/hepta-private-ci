//! The ordinary paired V2 declaration for the complete nonempty panel.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::StableId;

use super::Error;
use super::OriginalCircuitOnPolicyEvaluationPolicyV2;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellEvaluationPanelTaskV1;

/// Immutable metadata only. Clone shares no owner, receipt, clock or CURRENT.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyPanelPolicyV2 {
    primary: OriginalCircuitOnPolicyEvaluationPolicyV2,
    retention: Vec<OriginalCircuitOnPolicyEvaluationPolicyV2>,
    registration: OriginalCellEvaluationPanelRegistrationV1,
}

impl OriginalCircuitOnPolicyPanelPolicyV2 {
    pub fn freeze(
        primary: OriginalCircuitOnPolicyEvaluationPolicyV2,
        mut retention: Vec<OriginalCircuitOnPolicyEvaluationPolicyV2>,
    ) -> Result<Self, Error> {
        if !(1..=16).contains(&retention.len()) {
            return Err(Error::Binding("nonempty bounded complete retention policy"));
        }
        retention.sort_by(|left, right| left.product.context().plan_id.cmp(&right.product.context().plan_id));
        let task = |policy: &OriginalCircuitOnPolicyEvaluationPolicyV2| -> Result<_, Error> {
            Ok(OriginalCellEvaluationPanelTaskV1 {
                plan_id: policy.product.context().plan_id.clone(),
                task_digest: policy.task,
                cohort_rule_digest: policy.cohort_rule_digest()?,
            })
        };
        let registration = OriginalCellEvaluationPanelRegistrationV1::new(
            task(&primary)?,
            retention.iter().map(task).collect::<Result<Vec<_>, _>>()?,
        ).map_err(|_| Error::Binding("complete exact V2 panel registration"))?;
        let policy = Self { primary, retention, registration };
        policy.require_declaration()?;
        Ok(policy)
    }

    pub fn registration(&self) -> &OriginalCellEvaluationPanelRegistrationV1 {
        &self.registration
    }

    pub(crate) fn member(&self, plan_id: &StableId) -> Result<&OriginalCircuitOnPolicyEvaluationPolicyV2, Error> {
        std::iter::once(&self.primary).chain(&self.retention)
            .find(|policy| &policy.product.context().plan_id == plan_id)
            .ok_or(Error::Binding("declared complete original V2 panel member"))
    }

    /// This is a necessary size rejection for the specified ordinary route:
    /// twelve complete transfers on the same original E connection. It does
    /// not prove that the remaining body, extra polls or cold reads fit 128.
    fn require_declaration(&self) -> Result<(), Error> {
        let mut contribution = 0usize;
        for policy in std::iter::once(&self.primary).chain(&self.retention) {
            if policy.product.input().claim_scope
                != codex_hepta_intelligence_eval::EvaluationClaimScopeV1::Qualification
                || policy.baseline != self.primary.baseline
                || policy.product.input().baseline_id != self.primary.product.input().baseline_id
                || policy.product.context().objective_digest != self.primary.product.context().objective_digest
            {
                return Err(Error::Binding("same fixed panel baseline and objective"));
            }
            let bytes = OriginalCircuitOnPolicyEvaluationPolicyV2::canonical_commitment_bytes(policy)?;
            if OriginalCircuitOnPolicyEvaluationPolicyV2::from_canonical_commitment_bytes(&bytes)? != *policy {
                return Err(Error::Binding("whole canonical panel policy"));
            }
            contribution = contribution.checked_add(8)
                .and_then(|value| value.checked_add(bytes.len()))
                .ok_or(Error::Binding("bounded policy contribution"))?;
        }
        // Existing E body fields are nonempty. At this threshold the body
        // needs at least ten 8192-byte pages; 12 * (10 + Finish) exceeds 128.
        if contribution >= 9 * 8192 {
            return Err(Error::Binding("ordinary twelve-transfer policy contribution cannot fit"));
        }
        Ok(())
    }

    pub(crate) fn require_original_panel_initial(&self, initial: &LearningIterationSnapshotV1) -> Result<(), Error> {
        LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
        if !initial.receipts.is_empty() {
            return Err(Error::Binding("original initial cut before Material initialization"));
        }
        self.require_original_panel_training(initial)
    }

    pub(crate) fn require_original_panel_training(&self, training: &LearningIterationSnapshotV1) -> Result<(), Error> {
        self.require_declaration()?;
        if training.request.evaluation_profile != self.registration.evaluation_profile() {
            return Err(Error::Binding("exact original T commitment to complete V2 panel"));
        }
        for policy in std::iter::once(&self.primary).chain(&self.retention) {
            crate::OriginalCircuitOnPolicyEvaluationPolicyV2::require_original_policy_training(policy, training)?;
        }
        Ok(())
    }
}

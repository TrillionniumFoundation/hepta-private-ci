//! Source-bound plan inputs, before the existing product freezer and signatures.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use crate::CrossFoldPlanV1;
use crate::FrozenTaskSourceLineageV1;
use crate::TaskCrossFoldInputsV1;
use crate::TaskLineageError;
use crate::task_lineage::require_digest;

impl FrozenTaskSourceLineageV1 {
    /// Derive every partition from the same complete source graph and bind that
    /// graph into the original estimand. The final holdout's tasks/components
    /// are excluded from every training fold, even if a caller renames a window.
    ///
    /// This returns inputs, not a frozen receipt. Pass the result to the existing
    /// `freeze_product_evaluation_plan_v1`; all signature, support, multiplicity,
    /// primary-superiority and final-holdout consumption gates remain required.
    pub fn bind_cross_fold_plan(
        &self,
        mut plan: CrossFoldPlanV1,
        folds: Vec<TaskCrossFoldInputsV1>,
    ) -> Result<CrossFoldPlanV1, TaskLineageError> {
        require_digest(plan.estimand_digest)?;
        if !plan.folds.is_empty()
            || !(2..=32).contains(&folds.len())
            || plan.objective_digest != self.objective_digest
        {
            return Err(TaskLineageError::InvalidPlan);
        }
        plan.folds = folds
            .into_iter()
            .map(|fold| self.cross_fold_partition(fold))
            .collect::<Result<_, _>>()?;
        let mut final_folds = plan
            .folds
            .iter()
            .filter(|fold| fold.holdout_windows.contains(&plan.final_holdout_window_id));
        let final_fold = final_folds.next().ok_or(TaskLineageError::InvalidPlan)?;
        if final_folds.next().is_some() {
            return Err(TaskLineageError::InvalidPlan);
        }
        let final_principals: BTreeSet<_> = final_fold.holdout_principals.iter().collect();
        let final_episodes: BTreeSet<_> = final_fold.holdout_episodes.iter().collect();
        for fold in &plan.folds {
            if fold
                .training_principals
                .iter()
                .any(|principal| final_principals.contains(principal))
                || fold
                    .training_episodes
                    .iter()
                    .any(|episode| final_episodes.contains(episode))
            {
                return Err(TaskLineageError::FinalHoldoutLeakage);
            }
        }
        let mut bytes = b"hepta.eval.archived-task.bound-estimand.v1".to_vec();
        for digest in [
            plan.estimand_digest,
            self.scope_digest(),
            self.source_graph_digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        plan.estimand_digest = Digest32::of_bytes(&bytes);
        Ok(plan)
    }
}

#[cfg(test)]
#[path = "task_lineage_plan_tests.rs"]
mod tests;

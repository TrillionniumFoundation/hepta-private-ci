//! Actual bounded execution of every preregistered temporal fold.
//!
//! `CrossFoldPlanV1` previously froze caller-supplied fold model/prediction
//! digests. This executor recomputes those digests from the declared training and
//! held-out lineages before returning the frozen receipt. It remains a pure
//! source-level evaluator: supplied provenance still requires authentication and
//! no result selects, activates, promotes or releases an artifact.

use std::collections::BTreeSet;

use super::*;
use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanReceiptV1;
use crate::CrossFoldPlanV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationError;
use crate::TemporalEvaluationError;
use crate::freeze_cross_fold_plan_v2;

const MAX_CROSS_FIT_ROWS: usize = 1_000_000;
const MAX_CROSS_FIT_ACTION_CELLS: usize = 4_000_000;

/// Execute every preregistered fold and reject any lineage or digest substitution.
///
/// Each tuple is `(fold_id, fold_plan, training_rows, held_out_targets)`. Inputs
/// may arrive in any order; the executor canonicalizes by `fold_id` and requires
/// exact coverage of the frozen plan.
impl CrossFoldPlanV1 {
    pub fn execute_temporal_cross_fit_v1(
        self,
        metric_roles: Vec<MetricRoleContractV2>,
        mut inputs: Vec<(
            StableId,
            TemporalFoldPlan,
            Vec<OutcomeTrainingSample>,
            Vec<HeldOutTarget>,
        )>,
    ) -> Result<CrossFoldPlanReceiptV1, ProductEvaluationError> {
        let frozen = freeze_cross_fold_plan_v2(self.clone(), metric_roles)?;
        if inputs.len() != self.folds.len() {
            return Err(ProductEvaluationError::Binding("cross-fit fold coverage"));
        }
        inputs.sort_by_key(|input| input.0.clone());
        if inputs.windows(2).any(|rows| rows[0].0 == rows[1].0) {
            return Err(ProductEvaluationError::Binding("duplicate cross-fit fold"));
        }
        let mut declared = self.folds.clone();
        declared.sort_by_key(|fold| fold.fold_id.clone());

        // Cross-fold held-out identity is a global admission invariant. Check it
        // before fitting any fold so a duplicate cannot be masked by the first
        // affected fold's changed prediction digest.
        let mut held_out_decisions = BTreeSet::new();
        for (_, _, _, targets) in &inputs {
            for target in targets {
                if !held_out_decisions.insert(target.decision_id.clone()) {
                    return Err(ProductEvaluationError::Binding(
                        "cross-fit held-out decision reuse",
                    ));
                }
            }
        }

        let mut total_rows = 0_usize;
        let mut total_action_cells = 0_usize;

        for (partition, (fold_id, fold_plan, training, targets)) in
            declared.iter().zip(inputs.iter())
        {
            if partition.fold_id != *fold_id || fold_plan.fold_id != *fold_id {
                return Err(ProductEvaluationError::Binding("cross-fit fold identity"));
            }
            total_rows = total_rows
                .checked_add(training.len())
                .and_then(|value| value.checked_add(targets.len()))
                .filter(|value| *value <= MAX_CROSS_FIT_ROWS)
                .ok_or(ProductEvaluationError::Binding("cross-fit row budget"))?;
            for target in targets {
                total_action_cells = total_action_cells
                    .checked_add(target.actions.len())
                    .filter(|value| *value <= MAX_CROSS_FIT_ACTION_CELLS)
                    .ok_or(ProductEvaluationError::Binding("cross-fit action budget"))?;
            }
            validate_lineage(partition, training, targets)?;
            let receipt = fit_temporal_fold(fold_plan, training, targets).map_err(|error| {
                ProductEvaluationError::Temporal(TemporalEvaluationError::Fold(error))
            })?;
            if receipt.model_digest != partition.model_digest
                || receipt.predictions_digest != partition.predictions_digest
            {
                return Err(ProductEvaluationError::Integrity(
                    "cross-fit preregistered output",
                ));
            }
        }
        Ok(frozen)
    }
}

fn validate_lineage(
    partition: &CrossFoldPartitionV1,
    training: &[OutcomeTrainingSample],
    targets: &[HeldOutTarget],
) -> Result<(), ProductEvaluationError> {
    let training_principals = unique(training.iter().map(|row| &row.principal_lineage));
    let training_episodes = unique(training.iter().map(|row| &row.episode_lineage));
    let training_windows = unique(training.iter().map(|row| &row.window_id));
    let holdout_principals = unique(targets.iter().map(|row| &row.principal_lineage));
    let holdout_episodes = unique(targets.iter().map(|row| &row.episode_lineage));
    let holdout_windows = unique(targets.iter().map(|row| &row.window_id));
    if training_principals != normalized(&partition.training_principals)
        || training_episodes != normalized(&partition.training_episodes)
        || training_windows != normalized(&partition.training_windows)
        || holdout_principals != normalized(&partition.holdout_principals)
        || holdout_episodes != normalized(&partition.holdout_episodes)
        || holdout_windows != normalized(&partition.holdout_windows)
    {
        return Err(ProductEvaluationError::Binding("cross-fit lineage"));
    }
    Ok(())
}

fn unique<'a>(values: impl Iterator<Item = &'a StableId>) -> Vec<StableId> {
    values
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn normalized(values: &[StableId]) -> Vec<StableId> {
    values
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::EvaluationClaimScopeV1;
    use crate::EvaluationDirectionV1;
    use crate::MetricContractV1;
    use crate::MetricRoleV2;
    use codex_hepta_types::FixedQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn fold_fixture(
        name: &str,
        final_window: bool,
    ) -> (
        CrossFoldPartitionV1,
        (
            StableId,
            TemporalFoldPlan,
            Vec<OutcomeTrainingSample>,
            Vec<HeldOutTarget>,
        ),
    ) {
        let fold_id = id(name);
        let plan = TemporalFoldPlan {
            plan_digest: digest(&format!("plan:{name}")),
            fold_id: fold_id.clone(),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        };
        let training_principal = id(&format!("training-principal:{name}"));
        let training_episode = id(&format!("training-episode:{name}"));
        let training_window = id(&format!("training-window:{name}"));
        let holdout_principal = id(&format!("holdout-principal:{name}"));
        let holdout_episode = id(&format!("holdout-episode:{name}"));
        let holdout_window = if final_window {
            id("final-window")
        } else {
            id(&format!("holdout-window:{name}"))
        };
        let training = [FixedQ32::ZERO, FixedQ32::ONE]
            .into_iter()
            .enumerate()
            .map(|(index, outcome)| OutcomeTrainingSample {
                decision_id: id(&format!("training:{name}:{index}")),
                principal_lineage: training_principal.clone(),
                episode_lineage: training_episode.clone(),
                window_id: training_window.clone(),
                action_id: id("action"),
                outcome,
                observed_at: 10,
                evidence_digest: digest(&format!("evidence:{name}:{index}")),
            })
            .collect::<Vec<_>>();
        let targets = vec![HeldOutTarget {
            decision_id: id(&format!("target:{name}")),
            principal_lineage: holdout_principal.clone(),
            episode_lineage: holdout_episode.clone(),
            window_id: holdout_window.clone(),
            decision_at: 20,
            actions: vec![id("action")],
        }];
        let receipt = fit_temporal_fold(&plan, &training, &targets).expect("fold receipt");
        let partition = CrossFoldPartitionV1 {
            fold_id: fold_id.clone(),
            training_principals: vec![training_principal],
            training_episodes: vec![training_episode],
            training_windows: vec![training_window],
            holdout_principals: vec![holdout_principal],
            holdout_episodes: vec![holdout_episode],
            holdout_windows: vec![holdout_window],
            model_digest: receipt.model_digest,
            predictions_digest: receipt.predictions_digest,
        };
        (partition, (fold_id, plan, training, targets))
    }

    fn fixture() -> (
        CrossFoldPlanV1,
        Vec<MetricRoleContractV2>,
        Vec<(
            StableId,
            TemporalFoldPlan,
            Vec<OutcomeTrainingSample>,
            Vec<HeldOutTarget>,
        )>,
    ) {
        let (first_partition, first_input) = fold_fixture("fold-a", true);
        let (second_partition, second_input) = fold_fixture("fold-b", false);
        let metric = id("success");
        (
            CrossFoldPlanV1 {
                plan_id: id("cross-fit-plan"),
                claim_scope: EvaluationClaimScopeV1::Qualification,
                candidate_id: id("candidate"),
                baseline_id: id("baseline"),
                objective_digest: digest("objective"),
                dataset_digest: digest("dataset"),
                estimand_digest: digest("estimand"),
                metric_contracts: vec![MetricContractV1 {
                    metric_id: metric.clone(),
                    direction: EvaluationDirectionV1::Maximize,
                    safety_floor: None,
                }],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                folds: vec![second_partition, first_partition],
                final_holdout_window_id: id("final-window"),
                final_holdout_digest: digest("final-holdout"),
            },
            vec![MetricRoleContractV2 {
                metric_id: metric,
                role: MetricRoleV2::PrimarySuperiority {
                    minimum_improvement: FixedQ32::ZERO,
                },
            }],
            vec![second_input, first_input],
        )
    }

    #[test]
    fn executes_every_fold_and_canonicalizes_input_order() {
        let (plan, roles, inputs) = fixture();
        let expected = plan
            .clone()
            .execute_temporal_cross_fit_v1(roles.clone(), inputs.clone())
            .expect("cross fit");
        let mut reversed = inputs;
        reversed.reverse();
        assert_eq!(
            plan.execute_temporal_cross_fit_v1(roles, reversed)
                .expect("reordered"),
            expected
        );
    }

    #[test]
    fn rejects_lineage_substitution_and_preregistered_digest_drift() {
        let (plan, roles, mut inputs) = fixture();
        inputs[0].2[0].principal_lineage = id("substituted-principal");
        assert!(matches!(
            plan.clone()
                .execute_temporal_cross_fit_v1(roles.clone(), inputs),
            Err(ProductEvaluationError::Binding("cross-fit lineage"))
        ));
        let (mut plan, roles, inputs) = fixture();
        plan.folds[0].model_digest = digest("changed-model");
        assert!(matches!(
            plan.execute_temporal_cross_fit_v1(roles, inputs),
            Err(ProductEvaluationError::Integrity(
                "cross-fit preregistered output"
            ))
        ));
    }

    #[test]
    fn rejects_held_out_decision_reuse_across_folds() {
        let (plan, roles, mut inputs) = fixture();
        let repeated = inputs[0].3[0].decision_id.clone();
        inputs[1].3[0].decision_id = repeated;
        assert!(matches!(
            plan.execute_temporal_cross_fit_v1(roles, inputs),
            Err(ProductEvaluationError::Binding(
                "cross-fit held-out decision reuse"
            ))
        ));
    }
}

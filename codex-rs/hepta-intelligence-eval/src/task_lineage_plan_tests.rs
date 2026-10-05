use super::*;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::MetricContractV1;
use crate::MetricRoleContractV2;
use crate::MetricRoleV2;
use crate::TaskSourceRecordV1;
use crate::TaskSourceScopeV1;
use crate::freeze_cross_fold_plan_v2;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn source() -> FrozenTaskSourceLineageV1 {
    let scope = TaskSourceScopeV1 {
        objective_digest: digest("benchmark-objective"),
        task_definition_digest: digest("benchmark-task-contract"),
        source_archive_digest: digest("fixture-archive"),
    };
    let records: Vec<_> = ["train", "cal", "final"]
        .into_iter()
        .enumerate()
        .map(|(index, task)| TaskSourceRecordV1 {
            source_file_digest: digest("source-file"),
            source_row_index: index as u64 + 1,
            source_record_digest: digest(task),
            task_id: id(task),
            dependency_ids: vec![id(&format!("doc-{task}"))],
        })
        .collect();
    FrozenTaskSourceLineageV1::freeze(&scope, &records).unwrap()
}

fn plan() -> CrossFoldPlanV1 {
    CrossFoldPlanV1 {
        plan_id: id("benchmark-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("real-candidate"),
        baseline_id: id("installed-product-comparator"),
        objective_digest: digest("benchmark-objective"),
        dataset_digest: digest("authenticated-ledger-dataset"),
        estimand_digest: digest("original-task-population-estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("accuracy"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: None,
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: Vec::new(),
        final_holdout_window_id: id("final-run"),
        final_holdout_digest: digest("custody-fenced-manifest"),
    }
}

fn folds() -> Vec<TaskCrossFoldInputsV1> {
    ["cal", "final"]
        .into_iter()
        .map(|task| TaskCrossFoldInputsV1 {
            fold_id: id(&format!("fold-{task}")),
            training_records: vec![digest("train")],
            holdout_records: vec![digest(task)],
            training_windows: vec![id("original-training-run")],
            holdout_windows: vec![id(&format!("{task}-run"))],
            model_digest: digest("frozen-train-only-nuisance-model"),
            predictions_digest: digest("preregistered-nuisance-predictions"),
        })
        .collect()
}

#[test]
fn task_lineage_plan_binds_source_graph_and_preserves_native_freeze_contract() {
    let original = plan();
    let bound = source()
        .bind_cross_fold_plan(original.clone(), folds())
        .unwrap();
    assert_eq!(
        (
            &bound.dataset_digest,
            &bound.objective_digest,
            &bound.claim_scope,
            &bound.baseline_id
        ),
        (
            &original.dataset_digest,
            &original.objective_digest,
            &original.claim_scope,
            &original.baseline_id
        )
    );
    assert_ne!(bound.estimand_digest, original.estimand_digest);
    let receipt = freeze_cross_fold_plan_v2(
        bound,
        vec![MetricRoleContractV2 {
            metric_id: id("accuracy"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }],
    )
    .unwrap();
    assert_eq!(receipt.fold_count, 2);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn task_lineage_plan_rejects_final_tasks_in_any_training_fold_despite_window_rename() {
    let mut leaking = folds();
    leaking[0].training_records = vec![digest("final")];
    assert_eq!(
        source().bind_cross_fold_plan(plan(), leaking),
        Err(TaskLineageError::FinalHoldoutLeakage)
    );
}

#[test]
fn task_lineage_plan_rejects_scope_substitution_or_asserted_subjects() {
    let mut changed = plan();
    changed.objective_digest = digest("other-objective");
    assert_eq!(
        source().bind_cross_fold_plan(changed, folds()),
        Err(TaskLineageError::InvalidPlan)
    );
    let source = source();
    let mut changed = plan();
    changed.folds = vec![
        source
            .cross_fold_partition(folds().remove(/*index*/ 0))
            .unwrap(),
    ];
    assert_eq!(
        source.bind_cross_fold_plan(changed, folds()),
        Err(TaskLineageError::InvalidPlan)
    );
}

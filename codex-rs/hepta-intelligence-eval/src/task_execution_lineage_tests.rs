use super::*;
use crate::TaskSourceRecordV1;
use crate::TaskSourceScopeV1;
use crate::TemporalFoldError;
use crate::TemporalFoldPlan;
use crate::fit_temporal_fold;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

// Contract fixtures, not qualification or observed future-calendar evidence.
fn source() -> FrozenTaskSourceLineageV1 {
    let scope = TaskSourceScopeV1 {
        objective_digest: digest("classification"),
        task_definition_digest: digest("archived-benchmark-v1"),
        source_archive_digest: digest("archive"),
    };
    let records: Vec<_> = ["a", "b"]
        .into_iter()
        .map(|task| TaskSourceRecordV1 {
            source_file_digest: digest("file"),
            source_row_index: if task == "a" { 1 } else { 2 },
            source_record_digest: digest(task),
            task_id: id(task),
            dependency_ids: vec![id(&format!("document-{task}"))],
        })
        .collect();
    FrozenTaskSourceLineageV1::freeze(&scope, &records).unwrap()
}

fn window(run: &str, start: u64) -> TaskExecutionWindowV1 {
    TaskExecutionWindowV1 {
        registration: TaskExecutionRegistrationV1 {
            run_id: id(run),
            preregistration_digest: digest("persisted-native-registration"),
            registered_at_unix_micros: start - 10,
        },
        started_at_unix_micros: start,
        finished_at_unix_micros: start + 20,
    }
}

fn event(
    source: &FrozenTaskSourceLineageV1,
    run: &str,
    task: &str,
    at: u64,
) -> TaskPredictionEventV1 {
    TaskPredictionEventV1 {
        decision_id: id(&format!("native-request-{run}-{task}")),
        run_id: id(run),
        source_graph_digest: source.source_graph_digest(),
        source_record_digest: digest(task),
        native_prediction_receipt_digest: digest(&format!("original-receipt-{run}-{task}")),
        executed_at_unix_micros: at,
    }
}

#[test]
fn task_lineage_native_event_projects_exact_target_training_and_cluster() {
    let source = source();
    let window = window("run-a", /*start*/ 100);
    let event = event(&source, "run-a", "a", /*at*/ 110);
    let lineage = source
        .bind_prediction(&window, &event, /*now_unix_micros*/ 200)
        .unwrap();
    let target = lineage.held_out_target(vec![id("support")]).unwrap();
    let outcome = TaskObservedOutcomeV1 {
        action_id: id("support"),
        outcome: FixedQ32::ONE,
        observed_at_unix_micros: 125,
        evidence_digest: digest("signed-terminal-observer"),
    };
    let sample = lineage
        .training_sample(&outcome, /*now_unix_micros*/ 200)
        .unwrap();
    assert_eq!(
        target,
        HeldOutTarget {
            decision_id: sample.decision_id.clone(),
            principal_lineage: sample.principal_lineage.clone(),
            episode_lineage: sample.episode_lineage.clone(),
            window_id: sample.window_id.clone(),
            decision_at: event.executed_at_unix_micros,
            actions: vec![outcome.action_id],
        }
    );
    assert_eq!(lineage.cluster_assignment().decision_id, event.decision_id);
    assert_ne!(sample.evidence_digest, outcome.evidence_digest);
}

#[test]
fn task_lineage_rerun_preserves_task_identity_and_native_temporal_leakage_gate() {
    let source = source();
    let original = source
        .bind_prediction(
            &window("train", /*start*/ 100),
            &event(&source, "train", "a", /*now_unix_micros*/ 110),
            /*at*/ 500,
        )
        .unwrap();
    let repeated = source
        .bind_prediction(
            &window("repeat", /*start*/ 300),
            &event(&source, "repeat", "a", /*now_unix_micros*/ 310),
            /*at*/ 500,
        )
        .unwrap();
    let target = repeated.held_out_target(vec![id("support")]).unwrap();
    let training = original
        .training_sample(
            &TaskObservedOutcomeV1 {
                action_id: id("support"),
                outcome: FixedQ32::ONE,
                observed_at_unix_micros: 130,
                evidence_digest: digest("authenticated-training-outcome"),
            },
            /*now_unix_micros*/ 500,
        )
        .unwrap();
    assert_eq!(training.episode_lineage, target.episode_lineage);
    assert_eq!(training.principal_lineage, target.principal_lineage);
    assert_ne!(training.window_id, target.window_id);
    assert_ne!(training.decision_id, target.decision_id);
    let plan = TemporalFoldPlan {
        plan_digest: digest("frozen-temporal-plan"),
        fold_id: id("fold"),
        training_watermark: 200,
        evaluation_start: 300,
        minimum_per_action: 1,
    };
    assert_eq!(
        fit_temporal_fold(&plan, std::slice::from_ref(&training), &[target]),
        Err(TemporalFoldError::PrincipalLeakage)
    );
    let independent = source
        .bind_prediction(
            &window("holdout", /*start*/ 300),
            &event(&source, "holdout", "b", /*now_unix_micros*/ 310),
            /*at*/ 500,
        )
        .unwrap();
    let target = independent.held_out_target(vec![id("support")]).unwrap();
    assert!(fit_temporal_fold(&plan, &[training], &[target]).is_ok());
}

#[test]
fn task_lineage_rejects_past_source_time_future_event_run_and_graph_substitution() {
    let source = source();
    let actual_window = window("run", /*start*/ 100);
    let actual_event = event(&source, "run", "a", /*at*/ 110);
    let mut changed = actual_event.clone();
    changed.executed_at_unix_micros = 1;
    assert_eq!(
        source.bind_prediction(&actual_window, &changed, /*now_unix_micros*/ 200),
        Err(TaskLineageError::InvalidEvent)
    );
    changed = actual_event.clone();
    changed.run_id = id("other-native-run");
    assert_eq!(
        source.bind_prediction(&actual_window, &changed, /*now_unix_micros*/ 200),
        Err(TaskLineageError::InvalidEvent)
    );
    changed = actual_event;
    changed.source_graph_digest = digest("other-source-graph");
    assert_eq!(
        source.bind_prediction(&actual_window, &changed, /*now_unix_micros*/ 200),
        Err(TaskLineageError::InvalidEvent)
    );
    let changed_window = window("future", /*start*/ 300);
    let changed_event = event(&source, "future", "a", /*at*/ 310);
    assert_eq!(
        source.bind_prediction(
            &changed_window,
            &changed_event,
            /*now_unix_micros*/ 200
        ),
        Err(TaskLineageError::InvalidWindow)
    );
    let mut unregistered = actual_window;
    unregistered.registration.registered_at_unix_micros = 100;
    assert_eq!(
        source.bind_prediction(
            &unregistered,
            &event(&source, "run", "a", /*now_unix_micros*/ 110),
            /*at*/ 200
        ),
        Err(TaskLineageError::InvalidWindow)
    );
}

#[test]
fn task_lineage_rejects_early_or_future_outcomes_and_duplicate_actions() {
    let source = source();
    let lineage = source
        .bind_prediction(
            &window("run", /*start*/ 100),
            &event(&source, "run", "a", /*now_unix_micros*/ 110),
            /*at*/ 200,
        )
        .unwrap();
    for time in [109, 201] {
        assert_eq!(
            lineage.training_sample(
                &TaskObservedOutcomeV1 {
                    action_id: id("support"),
                    outcome: FixedQ32::ONE,
                    observed_at_unix_micros: time,
                    evidence_digest: digest("observer-outcome"),
                },
                /*now_unix_micros*/ 200
            ),
            Err(TaskLineageError::InvalidOutcome)
        );
    }
    assert_eq!(
        lineage.held_out_target(vec![id("support"), id("support")]),
        Err(TaskLineageError::InvalidActions)
    );
}

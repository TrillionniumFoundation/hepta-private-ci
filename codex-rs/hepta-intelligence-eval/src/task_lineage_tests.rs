use super::*;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn scope() -> TaskSourceScopeV1 {
    TaskSourceScopeV1 {
        objective_digest: digest("support-contradict-objective"),
        task_definition_digest: digest("archived-cited-abstract-classification-v1"),
        source_archive_digest: digest("test-source-archive"),
    }
}

fn record(task: &str, source: &str, dependencies: &[&str]) -> TaskSourceRecordV1 {
    TaskSourceRecordV1 {
        source_file_digest: digest("test-source-file"),
        source_row_index: match task {
            "claim-b" => 2,
            "claim-c" => 3,
            "claim-d" => 4,
            _ => 1,
        },
        source_record_digest: digest(source),
        task_id: id(task),
        dependency_ids: dependencies.iter().map(|value| id(value)).collect(),
    }
}

fn graph_records() -> Vec<TaskSourceRecordV1> {
    vec![
        record("claim-a", "pair-a", &["doc-1"]),
        record("claim-b", "unscored-bridge", &["doc-1", "doc-2"]),
        record("claim-c", "pair-c", &["doc-2"]),
        record("claim-d", "pair-d", &["doc-3"]),
        record("claim-a", "second-pair-a", &["doc-1"]),
    ]
}

fn partition(training: &[&str], holdout: &[&str]) -> TaskCrossFoldInputsV1 {
    TaskCrossFoldInputsV1 {
        fold_id: id("fold-a"),
        training_records: training.iter().map(|value| digest(value)).collect(),
        holdout_records: holdout.iter().map(|value| digest(value)).collect(),
        training_windows: vec![id("actual-training-run")],
        holdout_windows: vec![id("preregistered-heldout-run")],
        model_digest: digest("frozen-nuisance-model"),
        predictions_digest: digest("frozen-nuisance-predictions"),
    }
}

#[test]
fn task_lineage_graph_is_canonical_and_includes_unscored_bridges() {
    let records = graph_records();
    let graph = FrozenTaskSourceLineageV1::freeze(&scope(), &records).unwrap();
    let mut reordered = records;
    reordered.reverse();
    reordered[3].dependency_ids.reverse();
    assert_eq!(
        graph,
        FrozenTaskSourceLineageV1::freeze(&scope(), &reordered).unwrap()
    );
    let a = graph.record(digest("pair-a")).unwrap();
    let c = graph.record(digest("pair-c")).unwrap();
    assert_eq!((&a.principal, &a.cluster), (&c.principal, &c.cluster));
    assert_ne!(a.episode, c.episode);
    assert_eq!(a, graph.record(digest("second-pair-a")).unwrap());
    assert_ne!(
        a.principal,
        graph.record(digest("pair-d")).unwrap().principal
    );
}

#[test]
fn task_lineage_rejects_cross_fold_dependency_and_repeated_task_leakage() {
    let graph = FrozenTaskSourceLineageV1::freeze(&scope(), &graph_records()).unwrap();
    for holdout in ["pair-c", "second-pair-a"] {
        assert_eq!(
            graph.cross_fold_partition(partition(&["pair-a"], &[holdout])),
            Err(TaskLineageError::DependentSplit)
        );
    }
    let native = graph
        .cross_fold_partition(partition(&["pair-a", "pair-c"], &["pair-d"]))
        .unwrap();
    assert_eq!(native.training_principals.len(), 1);
    assert_eq!(native.training_episodes.len(), 2);
    assert_eq!(native.holdout_principals.len(), 1);
}

#[test]
fn task_lineage_rejects_partial_task_dependencies_and_duplicate_records() {
    let mut records = graph_records();
    records[4].dependency_ids.push(id("doc-4"));
    assert_eq!(
        FrozenTaskSourceLineageV1::freeze(&scope(), &records),
        Err(TaskLineageError::InconsistentTask)
    );
    records = graph_records();
    records[4] = records[0].clone();
    assert_eq!(
        FrozenTaskSourceLineageV1::freeze(&scope(), &records),
        Err(TaskLineageError::DuplicateRecord)
    );
    records = graph_records();
    records[0].dependency_ids.push(id("doc-1"));
    assert_eq!(
        FrozenTaskSourceLineageV1::freeze(&scope(), &records),
        Err(TaskLineageError::DuplicateDependency)
    );
    records = graph_records();
    records[1].source_row_index = records[0].source_row_index;
    assert_eq!(
        FrozenTaskSourceLineageV1::freeze(&scope(), &records),
        Err(TaskLineageError::InconsistentTask)
    );
}

#[test]
fn task_lineage_binds_scope_and_exact_source_provenance() {
    let records = graph_records();
    let graph = FrozenTaskSourceLineageV1::freeze(&scope(), &records).unwrap();
    let mut changed_scope = scope();
    changed_scope.task_definition_digest = digest("other-task");
    let other = FrozenTaskSourceLineageV1::freeze(&changed_scope, &records).unwrap();
    assert_ne!(
        graph.record(digest("pair-a")),
        other.record(digest("pair-a"))
    );
    let mut changed = records;
    changed[0].source_row_index += 100;
    let other = FrozenTaskSourceLineageV1::freeze(&scope(), &changed).unwrap();
    assert_ne!(graph.source_graph_digest(), other.source_graph_digest());
    changed[0].source_row_index = 0;
    assert_eq!(
        FrozenTaskSourceLineageV1::freeze(&scope(), &changed),
        Err(TaskLineageError::SourceRow)
    );
}

#[test]
fn task_lineage_rejects_unknown_or_reused_fold_membership_and_bounds() {
    let graph = FrozenTaskSourceLineageV1::freeze(&scope(), &graph_records()).unwrap();
    assert_eq!(
        graph.cross_fold_partition(partition(&["pair-a"], &["unknown"])),
        Err(TaskLineageError::UnknownRecord)
    );
    assert_eq!(
        graph.cross_fold_partition(partition(&["pair-a"], &["pair-a"])),
        Err(TaskLineageError::DuplicateMembership)
    );
    let mut oversized = record("task", "row", &[]);
    oversized.dependency_ids = (0..129).map(|index| id(&format!("doc-{index}"))).collect();
    assert_eq!(
        FrozenTaskSourceLineageV1::freeze(&scope(), &[oversized]),
        Err(TaskLineageError::ResourceLimit)
    );
}

//! Synthetic source-graph tests, not independent retention measurements.
#![allow(clippy::unwrap_used)]
use super::*;
use crate::TaskSourceRecordV1;
use crate::TaskSourceScopeV1;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;

fn source() -> PairedReviewSourcePlanV1 {
    let input = inputs(6);
    PairedReviewSourcePlanV1 {
        base_plan: input.base_plan,
        folds: input.folds,
        unscored_source_records: input.unscored_source_records,
        tasks: input.tasks,
        runtime: input.runtime,
        policy: input.policy,
        metrics: input.metrics,
        source_scope: TaskSourceScopeV1 {
            objective_digest: digest("paired-objective"),
            task_definition_digest: digest("tasks"),
            source_archive_digest: digest("archive"),
        },
        source_records: (0..8)
            .map(|i| TaskSourceRecordV1 {
                source_file_digest: digest("file"),
                source_row_index: i + 1,
                source_record_digest: digest(&format!("row-{i}")),
                task_id: id(&format!("task-{i}")),
                dependency_ids: vec![id(&format!("doc-{i}"))],
            })
            .collect(),
    }
}

#[test]
fn retention_cannot_inflate_sample_count_by_repeating_an_old_task() {
    let original = source();
    let mut pairs = original
        .tasks
        .iter()
        .map(|task| Assignment {
            evaluation_record_digest: task.source_record_digest.to_string(),
            old_record_digest: task.source_record_digest.to_string(),
        })
        .collect::<Vec<_>>();
    assert_eq!(assignments(&original, &original, &pairs).unwrap().len(), 6);
    let first = pairs[0].old_record_digest.clone();
    pairs[1].old_record_digest = first;
    assert!(assignments(&original, &original, &pairs).is_err());
    pairs.remove(1);
    assert!(assignments(&original, &original, &pairs).is_err());
}

#[test]
fn different_retention_rows_share_their_real_old_source_dependencies() {
    let old = source();
    let mut main = source();
    let mut pairs = Vec::new();
    for task in &mut main.tasks {
        let old_id = task.source_record_digest;
        let new_id = Digest32::of_bytes(&[b"new".as_slice(), old_id.as_array()].concat());
        let mut record = old
            .source_records
            .iter()
            .find(|record| record.source_record_digest == old_id)
            .unwrap()
            .clone();
        record.source_record_digest = new_id;
        record.task_id = id(&format!("new-{}", record.source_row_index));
        main.source_records.push(record);
        task.source_record_digest = new_id;
        pairs.push(Assignment {
            evaluation_record_digest: new_id.to_string(),
            old_record_digest: old_id.to_string(),
        });
    }
    assert_eq!(assignments(&main, &old, &pairs).unwrap().len(), 6);
    let first: Digest32 = pairs[0].evaluation_record_digest.parse().unwrap();
    main.source_records
        .iter_mut()
        .find(|record| record.source_record_digest == first)
        .unwrap()
        .dependency_ids
        .clear();
    assert!(assignments(&main, &old, &pairs).is_err());
    main.source_records.retain(|record| {
        record.source_record_digest != pairs[0].old_record_digest.parse::<Digest32>().unwrap()
    });
    assert!(assignments(&main, &old, &pairs).is_err());
}

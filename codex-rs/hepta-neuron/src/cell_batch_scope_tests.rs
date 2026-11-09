use super::*;
use pretty_assertions::assert_eq;

#[test]
fn one_prepared_transition_per_scope_preserves_independent_batch_and_next_state() {
    let mut owner = owner(&["run1", "run2"]);
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 3, /*max_batch*/ 3,
    ));
    let prepare = |owner: &CellPartitionOwnerV1, request| {
        checked(prepare_cell_step(
            &definition(),
            owner,
            &Encoder,
            request,
            /*now_micros*/ 10,
        ))
    };
    checked(queue.enqueue(prepare(&owner, input("run1")), /*now_micros*/ 11));
    let mut later = input("run1");
    later.operation_id = id("next-operation");
    assert_eq!(
        queue.enqueue(prepare(&owner, later.clone()), /*now_micros*/ 11),
        Err(CellExecutionError::OperationConflict),
    );
    assert!(checked(owner.pending_inference(&scope("run1"))).is_none());
    checked(queue.enqueue(prepare(&owner, input("run2")), /*now_micros*/ 11));
    let mut backend = Batch {
        calls: 0,
        omit: false,
    };
    let results = queue.dispatch_next(&mut owner, &mut backend, || 12);
    assert_eq!(results.len(), 2);
    for result in results {
        let proposed = checked(decide_cell(checked(result.result), /*now_micros*/ 13));
        checked(commit_cell_step(
            &mut owner, proposed, /*now_micros*/ 14,
        ));
    }
    assert_eq!(backend.calls, 1);
    later.monotonic_micros = 15;
    let next = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        later,
        /*now_micros*/ 15,
    ));
    checked(queue.enqueue(next, /*now_micros*/ 16));
    let results = queue.dispatch_next(&mut owner, &mut backend, || 17);
    assert_eq!(results.len(), 1);
    for result in results {
        let proposed = checked(decide_cell(checked(result.result), /*now_micros*/ 18));
        checked(commit_cell_step(
            &mut owner, proposed, /*now_micros*/ 19,
        ));
    }
    assert_eq!(backend.calls, 2);
    assert_eq!(
        ["run1", "run2"].map(|run| checked(owner.snapshot(&scope(run))).revision),
        [2, 1],
    );
}

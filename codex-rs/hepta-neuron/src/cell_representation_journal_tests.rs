use super::*;
use pretty_assertions::assert_eq;
use std::sync::Arc;

#[test]
fn committed_representation_recovers_exact_original_channels_without_inference() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    let prepared = checked(prepare_cell_step(
        &definition(),
        &journal,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    let mut inferred = checked(infer_cell(
        prepared,
        &mut journal,
        &mut Model {
            calls: 0,
            latency: 20,
        },
        /*now_micros*/ 11,
    ));
    // Capacity is not model output. It must not leak into retained shared storage.
    inferred.output.drive_q24.reserve(512);
    inferred.output.prediction_q24.reserve(512);
    let proposed = checked(decide_cell(inferred, /*now_micros*/ 12));
    let expected = CellRepresentationV1 {
        drive_q24: proposed.tick.drive_q24.clone(),
        prediction_q24: proposed.tick.prediction_q24.clone(),
    };
    let committed = checked(commit_cell_step(
        &mut journal,
        proposed,
        /*now_micros*/ 13,
    ));
    assert_eq!(committed.representation.as_ref(), &expected);
    for values in [
        &committed.representation.drive_q24,
        &committed.representation.prediction_q24,
    ] {
        assert_eq!(values.capacity(), values.len());
    }
    let mut next = input("run1");
    next.operation_id = id("next-operation");
    next.monotonic_micros = 20;
    let next = proposal(&mut journal, next);
    checked(commit_cell_step(&mut journal, next, /*now_micros*/ 23));
    let bytes = journal_bytes(&mut journal);
    let mut caller = checked(journal.reconcile(
        &committed.scope,
        &committed.operation_id,
        committed.operation_digest,
    ))
    .expect("original committed receipt");
    assert!(Arc::ptr_eq(
        &caller.representation,
        &committed.representation
    ));
    assert!(Arc::get_mut(&mut caller.representation).is_none());
    let detached = Arc::make_mut(&mut caller.representation);
    detached.drive_q24[0] += 1;
    detached.prediction_q24[0] -= 1;
    assert!(!Arc::ptr_eq(
        &caller.representation,
        &committed.representation
    ));
    assert_eq!(committed.representation.as_ref(), &expected);
    assert_eq!(
        checked(journal.reconcile(
            &committed.scope,
            &committed.operation_id,
            committed.operation_digest,
        )),
        Some(committed.clone())
    );
    assert_eq!(journal_bytes(&mut journal), bytes);
    drop(journal);
    let mut reopened = fixture.open();
    let replayed = match checked(enter_cell_step(
        &definition(),
        &reopened,
        &Encoder,
        input("run1"),
        /*now_micros*/ 500,
    )) {
        CellStepEntryV1::Replayed(receipt) => *receipt,
        CellStepEntryV1::Ready(_) => panic!("committed representation must use original readback"),
    };
    assert_eq!(replayed, committed);
    let cold_readback = checked(reopened.reconcile(
        &committed.scope,
        &committed.operation_id,
        committed.operation_digest,
    ))
    .expect("original cold receipt");
    assert!(Arc::ptr_eq(
        &replayed.representation,
        &cold_readback.representation
    ));
    assert_eq!(journal_bytes(&mut reopened), bytes);
}

#[test]
fn representation_substitution_is_rejected_before_any_commit_bytes() {
    for prediction in [false, true] {
        let fixture = Fixture::new();
        let mut journal = fixture.open();
        let mut proposed = proposal(&mut journal, input("run1"));
        let representation = Arc::make_mut(&mut proposed.receipt.representation);
        if prediction {
            representation.prediction_q24[0] += 1;
        } else {
            representation.drive_q24[0] += 1;
        }
        let before = (
            journal_bytes(&mut journal),
            checked(journal.witness.current()),
        );
        assert_eq!(
            commit_cell_step(&mut journal, proposed, /*now_micros*/ 13),
            Err(CellExecutionError::OperationConflict),
        );
        assert_eq!(
            (
                journal_bytes(&mut journal),
                checked(journal.witness.current())
            ),
            before,
        );
        drop(journal);
        let reopened = fixture.open();
        assert!(checked(reopened.pending_inference(&scope("run1"))).is_some());
        assert_eq!(checked(reopened.snapshot(&scope("run1"))).revision, 0);
    }
}

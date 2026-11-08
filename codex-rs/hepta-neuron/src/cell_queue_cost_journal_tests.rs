use pretty_assertions::assert_eq;

use super::*;
use crate::cell_inference::admission_for_step;
use crate::cell_inference::feature_request;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;

#[test]
fn unmeasured_admission_reserves_measurement_and_commit_and_measurement_is_bound() {
    for max_records in [2, 3] {
        let fixture = Fixture::new();
        let mut journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"), fixture.witness(), specs(), max_records,
        ));
        let prepared = checked(prepare_cell_step(
            &definition(), &journal, &Encoder, input("run1"), /*now_micros*/ 10,
        ));
        let mut admission = checked(admission_for_step(&prepared, /*now_micros*/ 11));
        admission.host_queue_age_micros = None;
        let request = feature_request(&prepared.model_request);
        let digest = checked(neuron_feature_request_digest_v1(&request));
        if max_records == 2 {
            let unchanged = (journal_bytes(&mut journal), checked(journal.witness.current()));
            assert_eq!(journal.admit_inference(admission), Err(CellExecutionError::CapacityExceeded));
            assert_eq!((journal_bytes(&mut journal), checked(journal.witness.current())), unchanged);
            assert_eq!(checked(journal.pending_inference(&scope("run1"))), None);
            continue;
        }
        checked(journal.admit_inference(admission.clone()));
        let before = (journal_bytes(&mut journal), checked(journal.witness.current()));
        assert_eq!(journal.record_host_queue_age(
            &scope("run1"), &id("another-operation"), digest, /*host_queue_age_micros*/ 1,
        ), Err(CellExecutionError::OperationConflict));
        assert_eq!(journal.record_host_queue_age(
            &scope("run1"), &admission.operation_id, d("another-request"), /*host_queue_age_micros*/ 1,
        ), Err(CellExecutionError::OperationConflict));
        assert_eq!(journal.record_host_queue_age(
            &scope("run2"), &admission.operation_id, digest, /*host_queue_age_micros*/ 1,
        ), Err(CellExecutionError::InferenceNotAdmitted));
        assert_eq!(journal.reset_at_frontier(
            &scope("run2"), d("new-source"), /*writer_epoch*/ 2,
        ), Err(CellExecutionError::CapacityExceeded));
        assert_eq!((journal_bytes(&mut journal), checked(journal.witness.current())), before);

        let mut control = RecordedControl::new();
        checked(control.execute_feature(&request));
        checked(journal.record_host_queue_age(
            &scope("run1"), &admission.operation_id, digest, /*host_queue_age_micros*/ 1,
        ));
        let measured = (journal_bytes(&mut journal), checked(journal.witness.current()));
        checked(journal.record_host_queue_age(
            &scope("run1"), &admission.operation_id, digest, /*host_queue_age_micros*/ 1,
        ));
        assert_eq!(journal.record_host_queue_age(
            &scope("run1"), &admission.operation_id, digest, /*host_queue_age_micros*/ 2,
        ), Err(CellExecutionError::OperationConflict));
        assert_eq!(journal.reset_at_frontier(
            &scope("run2"), d("new-source"), /*writer_epoch*/ 2,
        ), Err(CellExecutionError::CapacityExceeded));
        assert_eq!((journal_bytes(&mut journal), checked(journal.witness.current())), measured);
        drop(journal);
        let mut journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"), fixture.witness(), specs(), max_records,
        ));
        let inferred = checked(recover_cell_inference(
            &definition(), &journal, &Encoder, input("run1"), &mut control, /*now_micros*/ 12,
        ));
        let proposed = checked(decide_cell(inferred, /*now_micros*/ 12));
        let receipt = checked(commit_cell_step(&mut journal, proposed, /*now_micros*/ 13));
        assert_eq!(receipt.cost.queue_age_micros, 4);
        assert_eq!(journal.head.map(|head| head.sequence), Some(3));
        drop(journal);
        let journal = fixture.open();
        assert_eq!(checked(journal.lookup(
            &receipt.scope, &receipt.operation_id, receipt.semantic_request_digest,
        )), Some(receipt));
        assert_eq!((control.executions, control.reads), (1, 1));
    }
}

#[derive(Clone, Copy)]
enum History {
    LegacyPending,
    LegacyCommitted,
    CurrentPending,
}

#[test]
fn legacy_committed_history_replays_but_all_unmeasured_pending_history_holds() {
    for history in [History::LegacyPending, History::LegacyCommitted, History::CurrentPending] {
        let fixture = Fixture::new();
        let mut journal = fixture.open();
        let prepared = checked(prepare_cell_step(
            &definition(), &journal, &Encoder, input("run1"), /*now_micros*/ 10,
        ));
        let mut admission = checked(admission_for_step(&prepared, /*now_micros*/ 11));
        admission.host_queue_age_micros = None;
        match history {
            History::CurrentPending => {
                checked(journal.admit_inference(admission.clone()));
                assert_eq!(journal_bytes(&mut journal)[HEADER_BYTES + 4], 3);
            }
            History::LegacyPending | History::LegacyCommitted => {
                // Produce the exact former tag-2 bytes, with no new marker.
                let mut bytes = encode_admission(/*index*/ 0, &admission);
                assert_eq!(bytes.pop(), Some(0));
                bytes[0] = 2;
                checked(journal.persist(bytes.clone()));
                checked(apply_record(&bytes, &specs(), &mut journal.owner));
            }
        }
        let mut control = RecordedControl::new();
        let native_receipt = checked(control.execute_feature(&feature_request(&prepared.model_request)));
        let committed = match history {
            History::LegacyCommitted => {
                // The former binary could already have committed tag 0 after
                // tag 2. Replay retains those exact persisted policy and costs.
                let output = checked(InferenceControlModelPort::new(
                    &mut crate::cell_inference::ReceiptPort(native_receipt),
                ).execute(&prepared.model_request));
                let proposed = checked(decide_cell(InferredCellStepV1 {
                    prepared, output, not_before_micros: 11,
                }, /*now_micros*/ 12));
                Some(checked(commit_cell_step(&mut journal, proposed, /*now_micros*/ 13)))
            }
            History::LegacyPending | History::CurrentPending => None,
        };
        drop(journal);
        let mut journal = fixture.open();
        match committed {
            Some(receipt) => {
                assert_eq!(checked(journal.lookup(
                    &receipt.scope, &receipt.operation_id, receipt.semantic_request_digest,
                )), Some(receipt));
                assert_eq!(checked(journal.pending_inference(&scope("run1"))), None);
            }
            None => {
                let unchanged = (journal_bytes(&mut journal), checked(journal.witness.current()));
                assert_eq!(checked(journal.pending_inference(&scope("run1"))), Some(admission.clone()));
                assert!(matches!(recover_cell_inference(
                    &definition(), &journal, &Encoder, input("run1"), &mut control, /*now_micros*/ 50,
                ), Err(CellExecutionError::UnmeasuredQueueCost)));
                assert!(matches!(enter_cell_step(
                    &definition(), &journal, &Encoder, input("run1"), /*now_micros*/ 50,
                ), Err(CellExecutionError::InferencePending)));
                assert_eq!(checked(journal.pending_inference(&scope("run1"))), Some(admission));
                assert_eq!((journal_bytes(&mut journal), checked(journal.witness.current())), unchanged);
            }
        }
        assert_eq!((control.executions, control.reads), (1, 0));
    }
}

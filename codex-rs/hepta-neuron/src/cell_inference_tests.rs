use super::*;
use crate::*;
use crate::cell_test_support::*;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use pretty_assertions::assert_eq;

#[test]
fn any_backend_error_retains_admission_and_duplicate_prepared_work_cannot_execute() {
    for error in [NeuronModelError::Unavailable, NeuronModelError::Rejected, NeuronModelError::Indeterminate] {
        let mut owner = owner(&["run1"]);
        let first = checked(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/10));
        let duplicate = checked(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/10));
        let mut control = RecordedControl::new();
        control.failure = Some(error);
        assert!(matches!(infer_cell(first, &mut owner, &mut control, /*now_micros*/11), Err(CellExecutionError::Backend(actual)) if actual == error));
        assert!(matches!(infer_cell(duplicate, &mut owner, &mut control, /*now_micros*/12), Err(CellExecutionError::InferencePending)));
        assert!(matches!(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/12), Err(CellExecutionError::InferencePending)));
        assert_eq!(control.executions, 1);
        assert_eq!(control.reads, 0);
        assert!(checked(owner.pending_inference(&scope("run1"))).is_some());
    }
}

#[test]
fn output_lost_before_commit_is_recovered_by_reading_the_original_request_only() {
    let mut owner = owner(&["run1"]);
    let prepared = checked(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/10));
    let mut control = RecordedControl::new();
    drop(checked(infer_cell(prepared, &mut owner, &mut control, /*now_micros*/11)));
    let original = checked(owner.pending_inference(&scope("run1")));
    let mut changed = input("run1");
    changed.observation = b"changed".to_vec();
    assert!(matches!(recover_cell_inference(&definition(), &owner, &Encoder, changed, &mut control, /*now_micros*/12), Err(CellExecutionError::OperationConflict)));
    assert_eq!(control.reads, 0);
    let inferred = checked(recover_cell_inference(&definition(), &owner, &Encoder, input("run1"), &mut control, /*now_micros*/12));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), original);
    let proposed = checked(decide_cell(inferred, /*now_micros*/13));
    let receipt = checked(commit_cell_step(&mut owner, proposed, /*now_micros*/14));
    assert_eq!(receipt.cost.model_latency_micros, 20);
    assert_eq!((control.executions, control.reads), (1, 1));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
    match checked(enter_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/15)) {
        CellStepEntryV1::Replayed(replayed) => assert_eq!(*replayed, receipt),
        CellStepEntryV1::Ready(_) => panic!("settled request must replay"),
    }
}

#[test]
fn late_recovery_preserves_usage_and_settles_pending_as_abstention() {
    let mut owner = owner(&["run1"]);
    let prepared = checked(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/10));
    let mut control = RecordedControl::new();
    drop(checked(infer_cell(prepared, &mut owner, &mut control, /*now_micros*/11)));
    let inferred = checked(recover_cell_inference(&definition(), &owner, &Encoder, input("run1"), &mut control, /*now_micros*/101));
    let proposed = checked(decide_cell(inferred, /*now_micros*/102));
    let receipt = checked(commit_cell_step(&mut owner, proposed, /*now_micros*/103));
    assert_eq!(receipt.selected_candidate, id("abstain"));
    assert!(receipt.deadline_exceeded);
    assert_eq!(receipt.cost.model_latency_micros, 20);
    assert_eq!((control.executions, control.reads), (1, 1));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}

#[test]
fn crossing_deadline_after_decision_also_forces_abstention_at_commit() {
    let mut owner = owner(&["run1"]);
    let proposed = proposal(&mut owner, input("run1"));
    assert_eq!(proposed.receipt().selected_candidate, id("a"));
    let receipt = checked(commit_cell_step(&mut owner, proposed, /*now_micros*/100));
    assert_eq!(receipt.selected_candidate, id("abstain"));
    assert!(receipt.deadline_exceeded);
    assert_eq!(receipt.cost.model_latency_micros, 20);
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}

#[test]
fn missing_and_unsuccessful_readbacks_never_release_the_pending_request() {
    for status in [
        None,
        Some(NeuronFeatureTerminalStatusV1::Failed),
        Some(NeuronFeatureTerminalStatusV1::Cancelled),
        Some(NeuronFeatureTerminalStatusV1::Indeterminate),
    ] {
        let mut owner = owner(&["run1"]);
        let prepared = checked(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/10));
        let mut control = RecordedControl::new();
        drop(checked(infer_cell(prepared, &mut owner, &mut control, /*now_micros*/11)));
        let pending = match checked(owner.pending_inference(&scope("run1"))) {
            Some(value) => value,
            None => panic!("dispatch must retain an admission"),
        };
        let request = feature_request(&pending.model_request);
        control.receipt = status.map(|status| {
            let good = feature_receipt(&request, /*latency*/20);
            checked(build_neuron_feature_receipt_v1(&request, good.runtime_tuple, NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest, head_digest: request.head_digest,
                drive_q24: Vec::new(), prediction_q24: Vec::new(), observed_memory_bytes: 4096,
                transient_allocation_bytes: 4096, queue_age_micros: 3, latency_micros: 20, status,
            }))
        });
        assert!(recover_cell_inference(&definition(), &owner, &Encoder, input("run1"), &mut control, /*now_micros*/12).is_err());
        assert_eq!(checked(owner.pending_inference(&scope("run1"))), Some(pending));
        assert_eq!(control.executions, 1);
        assert!(matches!(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/12), Err(CellExecutionError::InferencePending)));
    }
}

#[test]
fn receipt_capacity_is_checked_before_spending_compute() {
    let mut owner = checked(CellPartitionOwnerV1::new(/*max_partitions*/1, /*max_receipts_per_partition*/1));
    checked(owner.admit(scope("run1"), &definition(), d("frontier"), /*writer_epoch*/1));
    let proposed = proposal(&mut owner, input("run1"));
    checked(commit_cell_step(&mut owner, proposed, /*now_micros*/13));
    let mut next = input("run1");
    next.operation_id = id("second");
    next.monotonic_micros = 14;
    let prepared = checked(prepare_cell_step(&definition(), &owner, &Encoder, next, /*now_micros*/14));
    let mut control = RecordedControl::new();
    assert!(matches!(infer_cell(prepared, &mut owner, &mut control, /*now_micros*/15), Err(CellExecutionError::CapacityExceeded)));
    assert_eq!(control.executions, 0);
}

#[test]
fn native_stage_clocks_cannot_move_before_admission_or_decision() {
    let mut owner = owner(&["run1"]);
    let prepared = checked(prepare_cell_step(&definition(), &owner, &Encoder, input("run1"), /*now_micros*/10));
    let mut control = RecordedControl::new();
    let inferred = checked(infer_cell(prepared, &mut owner, &mut control, /*now_micros*/20));
    assert!(matches!(decide_cell(inferred, /*now_micros*/19), Err(CellExecutionError::DeadlineExceeded)));
    assert!(matches!(recover_cell_inference(&definition(), &owner, &Encoder, input("run1"), &mut control, /*now_micros*/19), Err(CellExecutionError::DeadlineExceeded)));
    assert_eq!(control.reads, 0);
    let recovered = checked(recover_cell_inference(&definition(), &owner, &Encoder, input("run1"), &mut control, /*now_micros*/21));
    let proposal = checked(decide_cell(recovered, /*now_micros*/22));
    assert_eq!(commit_cell_step(&mut owner, proposal, /*now_micros*/21), Err(CellExecutionError::DeadlineExceeded));
    assert!(checked(owner.pending_inference(&scope("run1"))).is_some());
    let recovered = checked(recover_cell_inference(&definition(), &owner, &Encoder, input("run1"), &mut control, /*now_micros*/23));
    let proposal = checked(decide_cell(recovered, /*now_micros*/24));
    checked(commit_cell_step(&mut owner, proposal, /*now_micros*/25));
    assert_eq!((control.executions, control.reads), (1, 2));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}

use super::*;
use crate::cell_test_support::*;
use crate::*;
use pretty_assertions::assert_eq;

fn prepared(owner: &CellPartitionOwnerV1, run: &str) -> PreparedCellStepV1 {
    checked(prepare_cell_step(
        &definition(),
        owner,
        &Encoder,
        input(run),
        /*now_micros*/ 10,
    ))
}

struct Batch {
    requests: Vec<Vec<StableId>>,
}

impl CellMicrobatchInferenceControlPortV1 for Batch {
    fn execute_feature_batch(
        &mut self,
        requests: &[NeuronFeatureRequestV1],
    ) -> Result<Vec<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.requests.push(
            requests
                .iter()
                .map(|request| request.request_id.clone())
                .collect(),
        );
        Ok(requests
            .iter()
            .rev()
            .map(|request| feature_receipt(request, /*latency*/ 20))
            .collect())
    }
}

#[test]
fn byte_backpressure_rejects_before_admission_and_cancel_releases_exact_capacity() {
    let owner = owner(&["run1", "run2"]);
    let first = prepared(&owner, "run1");
    let bytes = checked(retained_input_bytes(&first));
    let limits = CellBatchQueueLimitsV1 {
        max_queued: 2,
        max_batch: 2,
        max_queued_payload_bytes: bytes,
        max_batch_payload_bytes: bytes,
    };
    let mut queue = checked(CellBatchQueueV1::with_limits(limits));
    checked(queue.enqueue(first, /*now_micros*/ 11));
    assert_eq!(
        queue.enqueue(prepared(&owner, "run2"), /*now_micros*/ 11),
        Err(CellExecutionError::CapacityExceeded)
    );
    assert_eq!(checked(owner.pending_inference(&scope("run2"))), None);
    assert_eq!(
        queue.observation(),
        CellBatchQueueObservationV1 {
            queued: 1,
            retained_payload_bytes: bytes,
            limits,
        }
    );
    let before = checked(owner.snapshot(&scope("run1")));
    assert_eq!(
        queue.cancel_queued(&scope("run1"), &id("operation")),
        CellQueuedCancellationV1::RemovedBeforeQueueDispatch
    );
    assert_eq!(checked(owner.snapshot(&scope("run1"))), before);
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
    checked(queue.enqueue(prepared(&owner, "run2"), /*now_micros*/ 12));
    assert_eq!(
        queue.observation(),
        CellBatchQueueObservationV1 {
            queued: 1,
            retained_payload_bytes: bytes,
            limits,
        }
    );
}

#[test]
fn spare_input_capacity_is_charged_and_an_undispatchable_item_is_rejected() {
    let owner = owner(&["run1"]);
    let mut input = input("run1");
    input.observation.reserve_exact(4096);
    let item = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input,
        /*now_micros*/ 10,
    ));
    assert!(checked(retained_input_bytes(&item)) >= 4096);
    let mut queue = checked(CellBatchQueueV1::with_limits(CellBatchQueueLimitsV1 {
        max_queued: 2,
        max_batch: 1,
        max_queued_payload_bytes: 8192,
        max_batch_payload_bytes: 128,
    }));
    assert_eq!(
        queue.enqueue(item, /*now_micros*/ 11),
        Err(CellExecutionError::CapacityExceeded)
    );
    assert_eq!(queue.observation().queued, 0);
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}

#[test]
fn batch_bytes_split_compatible_work_without_dropping_or_sharing_cell_state() {
    let mut owner = owner(&["run1", "run2", "run3"]);
    let bytes = checked(retained_input_bytes(&prepared(&owner, "run1")));
    let mut queue = checked(CellBatchQueueV1::with_limits(CellBatchQueueLimitsV1 {
        max_queued: 3,
        max_batch: 3,
        max_queued_payload_bytes: 3 * bytes,
        max_batch_payload_bytes: 2 * bytes,
    }));
    for run in ["run1", "run2", "run3"] {
        checked(queue.enqueue(prepared(&owner, run), /*now_micros*/ 11));
    }
    let mut model = Batch {
        requests: Vec::new(),
    };
    let first = queue.dispatch_next(&mut owner, &mut model, /*clock_micros*/ || 12);
    assert_eq!(first.len(), 2);
    assert_eq!(queue.observation().retained_payload_bytes, bytes);
    assert_eq!(checked(owner.pending_inference(&scope("run3"))), None);
    for result in first {
        let proposal = checked(decide_cell(checked(result.result), /*now_micros*/ 13));
        let receipt = checked(commit_cell_step(
            &mut owner, proposal, /*now_micros*/ 14,
        ));
        assert_eq!(receipt.scope, result.scope);
    }
    let second = queue.dispatch_next(&mut owner, &mut model, /*clock_micros*/ || 15);
    assert_eq!(second.len(), 1);
    assert_eq!(second[0].scope, scope("run3"));
    assert_eq!(
        model.requests.iter().map(Vec::len).collect::<Vec<_>>(),
        vec![2, 1]
    );
    assert_eq!(queue.observation().retained_payload_bytes, 0);
    assert_eq!(checked(owner.snapshot(&scope("run3"))).checkpoint, None);
}

#[test]
fn queue_cancellation_is_scope_exact_and_never_clears_dispatched_pending_work() {
    let mut owner = owner(&["run1", "run2"]);
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 2, /*max_batch*/ 2,
    ));
    for run in ["run1", "run2"] {
        checked(queue.enqueue(prepared(&owner, run), /*now_micros*/ 11));
    }
    let mut wrong_scope = scope("run1");
    wrong_scope.principal_digest = d("other-principal");
    assert_eq!(
        queue.cancel_queued(&wrong_scope, &id("operation")),
        CellQueuedCancellationV1::NotQueued
    );
    assert_eq!(
        queue.cancel_queued(&scope("run1"), &id("operation")),
        CellQueuedCancellationV1::RemovedBeforeQueueDispatch
    );
    let results = queue.dispatch_next(
        &mut owner,
        &mut Batch {
            requests: Vec::new(),
        },
        /*clock_micros*/ || 12,
    );
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].scope, scope("run2"));
    let pending = checked(owner.pending_inference(&scope("run2")));
    assert!(pending.is_some());
    assert_eq!(
        queue.cancel_queued(&scope("run2"), &id("operation")),
        CellQueuedCancellationV1::NotQueued
    );
    assert_eq!(checked(owner.pending_inference(&scope("run2"))), pending);
    assert!(matches!(
        prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            input("run2"),
            /*now_micros*/ 13
        ),
        Err(CellExecutionError::InferencePending)
    ));
}

#[test]
fn expired_batch_releases_transient_queue_buffers_without_creating_a_reservation() {
    let mut owner = owner(&["run1"]);
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 1, /*max_batch*/ 1,
    ));
    checked(queue.enqueue(prepared(&owner, "run1"), /*now_micros*/ 11));
    let mut model = Batch {
        requests: Vec::new(),
    };
    let results = queue.dispatch_next(&mut owner, &mut model, /*clock_micros*/ || 100);
    assert!(matches!(
        results[0].result,
        Err(CellExecutionError::DeadlineExceeded)
    ));
    assert_eq!(queue.observation().retained_payload_bytes, 0);
    assert!(model.requests.is_empty());
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}

#[test]
fn spare_candidate_capacity_cannot_bypass_byte_backpressure() {
    let owner = owner(&["run1"]);
    let mut input = input("run1");
    input.candidates.reserve_exact(4096);
    let item = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input,
        /*now_micros*/ 10,
    ));
    let mut queue = checked(CellBatchQueueV1::with_limits(CellBatchQueueLimitsV1 {
        max_queued: 2,
        max_batch: 1,
        max_queued_payload_bytes: 65536,
        max_batch_payload_bytes: 65536,
    }));
    assert_eq!(
        queue.enqueue(item, /*now_micros*/ 11),
        Err(CellExecutionError::CapacityExceeded)
    );
    assert_eq!(queue.observation().retained_payload_bytes, 0);
}

#[test]
fn removing_a_queued_duplicate_does_not_claim_the_original_operation_was_cancelled() {
    let mut owner = owner(&["run1"]);
    let queued = prepared(&owner, "run1");
    let external = prepared(&owner, "run1");
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 1, /*max_batch*/ 1,
    ));
    checked(queue.enqueue(queued, /*now_micros*/ 11));
    let _inferred = checked(infer_cell(
        external,
        &mut owner,
        &mut Model {
            calls: 0,
            latency: 20,
        },
        /*now_micros*/ 12,
    ));
    let pending = checked(owner.pending_inference(&scope("run1")));
    assert!(pending.is_some());
    assert_eq!(
        queue.cancel_queued(&scope("run1"), &id("operation")),
        CellQueuedCancellationV1::RemovedBeforeQueueDispatch
    );
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), pending);
}

#[test]
fn canonicalizing_input_identifier_storage_preserves_the_admitted_operation() {
    let mut owner = owner(&["run1"]);
    let mut item = prepared(&owner, "run1");
    let expected_request = item.model_request.clone();
    let bytes = checked(retained_input_bytes(&item));
    for id in [
        &mut item.input.operation_id,
        &mut item.input.candidates[0].candidate_id,
    ] {
        let mut oversized = String::with_capacity(1024 * 1024);
        oversized.push_str(id.as_str());
        *id = checked(StableId::new(oversized));
    }
    let mut queue = checked(CellBatchQueueV1::with_limits(CellBatchQueueLimitsV1 {
        max_queued: 1,
        max_batch: 1,
        max_queued_payload_bytes: bytes,
        max_batch_payload_bytes: bytes,
    }));
    checked(queue.enqueue(item, /*now_micros*/ 11));
    assert_eq!(queue.observation().retained_payload_bytes, bytes);
    let results = queue.dispatch_next(
        &mut owner,
        &mut Batch {
            requests: Vec::new(),
        },
        /*clock_micros*/ || 12,
    );
    assert_eq!(results.len(), 1);
    let inferred = checked(
        results
            .into_iter()
            .next()
            .expect("one admitted request")
            .result,
    );
    assert_eq!(inferred.prepared.model_request, expected_request);
    assert!(checked(owner.pending_inference(&scope("run1"))).is_some());
}

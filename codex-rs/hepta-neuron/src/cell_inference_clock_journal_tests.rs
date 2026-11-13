use pretty_assertions::assert_eq;

use super::*;
use crate::cell_inference::feature_request;
use crate::cell_inference::infer_cell_with_clock;

#[test]
fn single_admission_sync_rechecks_deadline_clock_and_queue_before_contact() {
    for (deadline_micros, rollback, maximum_queue_age) in
        [(100, false, 100), (200, true, 100), (200, false, 10)]
    {
        let fixture = Fixture::new();
        let clock = Arc::new(AtomicU64::new(90));
        let witness = AdvancingWitness {
            inner: fixture.witness(),
            clock_micros: Arc::clone(&clock),
            elapsed_per_ack_micros: 20,
        };
        let mut definition = definition();
        definition.max_queue_age_micros = maximum_queue_age;
        let mut specs = specs();
        for spec in &mut specs {
            spec.definition = definition.clone();
        }
        let mut journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"),
            witness,
            specs.clone(),
            /*max_records*/ 64,
        ));
        let before = checked(journal.snapshot(&scope("run1")));
        let mut request = input("run1");
        request.deadline_micros = deadline_micros;
        let prepared = checked(prepare_cell_step(
            &definition,
            &journal,
            &Encoder,
            request.clone(),
            /*now_micros*/ 10,
        ));
        let mut control = RecordedControl::new();
        let mut samples = 0;
        let result = infer_cell_with_clock(prepared, &mut journal, &mut control, || {
            samples += 1;
            let now = clock.load(Ordering::SeqCst);
            if rollback && samples == 2 {
                now - 21
            } else {
                now
            }
        });
        assert!(matches!(result, Err(CellExecutionError::DeadlineExceeded)));
        assert_eq!(clock.load(Ordering::SeqCst), 110);
        assert_eq!((control.executions, control.reads), (0, 0));
        drop(journal);
        let journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"),
            fixture.witness(),
            specs,
            /*max_records*/ 64,
        ));
        let pending = checked(journal.pending_inference(&request.scope))
            .expect("durable admission survives refusal");
        assert_eq!(pending.host_queue_age_micros, None);
        assert_eq!(checked(journal.snapshot(&request.scope)), before);
        assert!(matches!(
            recover_cell_inference(
                &definition,
                &journal,
                &Encoder,
                request,
                &mut control,
                /*now_micros*/ 150,
            ),
            Err(CellExecutionError::UnmeasuredQueueCost)
        ));
        assert_eq!((control.executions, control.reads), (0, 0));
    }
}

#[derive(Clone, Copy, Debug)]
enum Returned {
    Receipt,
    NativeError,
    WrongRequest,
    CorruptReceipt,
    LostCostAck,
}

struct Control {
    recorded: RecordedControl,
    original_request: Option<NeuronFeatureRequestV1>,
    returned: Returned,
    lose_cost_ack: Arc<AtomicBool>,
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.original_request = Some(request.clone());
        let mut receipt = self.recorded.execute_feature(request)?;
        match self.returned {
            Returned::Receipt => {}
            Returned::NativeError => return Err(NeuronModelError::Indeterminate),
            Returned::WrongRequest => receipt.request_digest = d("another-request"),
            Returned::CorruptReceipt => receipt.receipt_digest = d("corrupt-receipt"),
            Returned::LostCostAck => self.lose_cost_ack.store(true, Ordering::SeqCst),
        }
        Ok(receipt)
    }
}

impl CellInferenceReadbackPortV1 for Control {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        if self.original_request.as_ref() != Some(request) {
            return Err(NeuronModelError::Rejected);
        }
        self.recorded.read_feature(request)
    }
}

#[test]
fn single_queue_cost_and_policy_survive_errors_and_lost_measurement_ack() {
    let mut expected = None;
    for returned in [
        Returned::Receipt,
        Returned::NativeError,
        Returned::WrongRequest,
        Returned::CorruptReceipt,
        Returned::LostCostAck,
    ] {
        let fixture = Fixture::new();
        let clock = Arc::new(AtomicU64::new(90));
        let lose_cost_ack = Arc::new(AtomicBool::new(false));
        let witness = AdvancingWitness {
            inner: FailOnce {
                inner: fixture.witness(),
                fail: Arc::clone(&lose_cost_ack),
            },
            clock_micros: Arc::clone(&clock),
            elapsed_per_ack_micros: 20,
        };
        let mut definition = definition();
        definition.max_queue_age_micros = 21;
        let mut specs = specs();
        for spec in &mut specs {
            spec.definition = definition.clone();
        }
        let mut journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"),
            witness,
            specs.clone(),
            /*max_records*/ 64,
        ));
        let other_partition = checked(journal.snapshot(&scope("run2")));
        let mut request = input("run1");
        request.deadline_micros = 200;
        let prepared = checked(prepare_cell_step(
            &definition,
            &journal,
            &Encoder,
            request.clone(),
            /*now_micros*/ 10,
        ));
        let mut control = Control {
            recorded: RecordedControl::new(),
            original_request: None,
            returned,
            lose_cost_ack,
        };
        let result = infer_cell_with_clock(prepared, &mut journal, &mut control, || {
            clock.load(Ordering::SeqCst)
        });
        match returned {
            Returned::Receipt => {
                let proposed = checked(decide_cell(checked(result), /*now_micros*/ 150));
                // 20 micros of admission wait plus 3 from the native queue.
                // The later cost-record fsync is not pre-dispatch queue time.
                assert_eq!(clock.load(Ordering::SeqCst), 130);
                assert_eq!(proposed.receipt().cost.queue_age_micros, 23);
                assert_eq!(proposed.receipt().selected_candidate, id("abstain"));
                assert!(!proposed.receipt().deadline_exceeded);
                expected = Some((proposed.receipt().clone(), proposed.checkpoint().clone()));
            }
            Returned::LostCostAck => {
                assert!(matches!(result, Err(CellExecutionError::CommitUncertain)));
                assert_eq!(
                    journal.pending_inference(&request.scope),
                    Err(CellExecutionError::CommitUncertain)
                );
            }
            Returned::NativeError | Returned::WrongRequest | Returned::CorruptReceipt => {
                assert!(matches!(result, Err(CellExecutionError::Backend(_))));
            }
        }
        drop(journal);
        let mut journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"),
            fixture.witness(),
            specs.clone(),
            /*max_records*/ 64,
        ));
        let pending = checked(journal.pending_inference(&request.scope))
            .expect("original request remains admitted");
        assert_eq!(pending.host_queue_age_micros, Some(20));
        assert_eq!(
            Some(feature_request(&pending.model_request)),
            control.original_request
        );
        let inferred = checked(recover_cell_inference(
            &definition,
            &journal,
            &Encoder,
            request,
            &mut control,
            /*now_micros*/ 150,
        ));
        let proposed = checked(decide_cell(inferred, /*now_micros*/ 150));
        let (receipt, checkpoint) = expected.as_ref().expect("successful baseline");
        assert_eq!(
            (proposed.receipt(), proposed.checkpoint()),
            (receipt, checkpoint),
            "{returned:?}"
        );
        let committed = checked(commit_cell_step(
            &mut journal,
            proposed,
            /*now_micros*/ 151,
        ));
        assert_eq!(&committed, receipt);
        assert_eq!(
            (control.recorded.executions, control.recorded.reads),
            (1, 1)
        );
        assert_eq!(checked(journal.pending_inference(&committed.scope)), None);
        assert_eq!(checked(journal.snapshot(&scope("run2"))), other_partition);
        drop(journal);
        let journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"),
            fixture.witness(),
            specs,
            /*max_records*/ 64,
        ));
        assert_eq!(
            checked(journal.lookup(
                &committed.scope,
                &committed.operation_id,
                committed.semantic_request_digest,
            )),
            Some(committed)
        );
    }
}

#[test]
fn single_uncertain_admission_never_contacts_native_or_invents_queue_cost() {
    let fixture = Fixture::new();
    let fail = Arc::new(AtomicBool::new(false));
    let mut journal = checked(CellOwnerJournalV1::open(
        fixture.file("journal"),
        FailOnce {
            inner: fixture.witness(),
            fail: Arc::clone(&fail),
        },
        specs(),
        /*max_records*/ 64,
    ));
    let prepared = checked(prepare_cell_step(
        &definition(),
        &journal,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    let mut control = RecordedControl::new();
    fail.store(true, Ordering::SeqCst);
    assert!(matches!(
        infer_cell_with_clock(prepared, &mut journal, &mut control, || 11),
        Err(CellExecutionError::CommitUncertain)
    ));
    drop(journal);
    let journal = fixture.open();
    assert!(matches!(
        recover_cell_inference(
            &definition(),
            &journal,
            &Encoder,
            input("run1"),
            &mut control,
            /*now_micros*/ 12,
        ),
        Err(CellExecutionError::UnmeasuredQueueCost)
    ));
    assert_eq!((control.executions, control.reads), (0, 0));
}

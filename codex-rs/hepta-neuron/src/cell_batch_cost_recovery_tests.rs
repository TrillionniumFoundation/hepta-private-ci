use pretty_assertions::assert_eq;

use super::*;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;

#[derive(Clone, Copy, Debug)]
enum Returned {
    Receipt,
    NativeError,
    WrongMembership,
    CorruptReceipt,
    LostCostAck,
}

struct Batch {
    returned: Returned,
    receipts: Vec<NeuronFeatureReceiptV1>,
    calls: usize,
    reads: usize,
    lose_cost_ack: Arc<AtomicBool>,
}

impl CellMicrobatchInferenceControlPortV1 for Batch {
    fn execute_feature_batch(
        &mut self,
        requests: &[NeuronFeatureRequestV1],
    ) -> Result<Vec<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.calls += 1;
        self.receipts = requests
            .iter()
            .map(|request| feature_receipt(request, /*latency*/ 20))
            .collect();
        match self.returned {
            Returned::Receipt => Ok(self.receipts.clone()),
            Returned::NativeError => Err(NeuronModelError::Indeterminate),
            Returned::WrongMembership => Ok(Vec::new()),
            Returned::CorruptReceipt => {
                let mut receipts = self.receipts.clone();
                receipts[0].receipt_digest = d("corrupt-receipt");
                Ok(receipts)
            }
            Returned::LostCostAck => {
                self.lose_cost_ack.store(true, Ordering::SeqCst);
                Ok(self.receipts.clone())
            }
        }
    }
}

impl CellInferenceReadbackPortV1 for Batch {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.reads += 1;
        let digest = checked(neuron_feature_request_digest_v1(request));
        Ok(self
            .receipts
            .iter()
            .find(|receipt| receipt.request_digest == digest)
            .cloned())
    }
}

struct LoseCostAck<W> {
    inner: W,
    lose: Arc<AtomicBool>,
}

impl<W: AnchorWitnessStore> AnchorWitnessStore for LoseCostAck<W> {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)?;
        if self.lose.swap(false, Ordering::SeqCst) {
            return Err(WitnessStoreError::Unavailable);
        }
        Ok(())
    }
}

#[test]
fn batch_queue_cost_and_policy_survive_native_errors_and_lost_measurement_ack() {
    let mut expected = None;
    for returned in [
        Returned::Receipt,
        Returned::NativeError,
        Returned::WrongMembership,
        Returned::CorruptReceipt,
        Returned::LostCostAck,
    ] {
        let fixture = Fixture::new();
        let clock = Arc::new(AtomicU64::new(90));
        let lose_cost_ack = Arc::new(AtomicBool::new(false));
        let witness = LoseCostAck {
            inner: AdvancingWitness {
                inner: fixture.witness(),
                clock_micros: Arc::clone(&clock),
                elapsed_per_ack_micros: 20,
            },
            lose: Arc::clone(&lose_cost_ack),
        };
        let mut definition = definition();
        definition.max_queue_age_micros = 100;
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
        let mut request = input("run1");
        request.deadline_micros = 200;
        let prepared = checked(prepare_cell_step(
            &definition,
            &journal,
            &Encoder,
            request.clone(),
            /*now_micros*/ 10,
        ));
        let mut queue = checked(CellBatchQueueV1::new(
            /*max_queued*/ 1, /*max_batch*/ 1,
        ));
        checked(queue.enqueue(prepared, /*now_micros*/ 11));
        let mut batch = Batch {
            returned,
            receipts: Vec::new(),
            calls: 0,
            reads: 0,
            lose_cost_ack,
        };
        let mut results =
            queue.dispatch_next(&mut journal, &mut batch, || clock.load(Ordering::SeqCst));
        assert_eq!(results.len(), 1);
        let result = results.remove(0).result;
        // Host time is 110 - 11 = 99, including admission fsync, frozen
        // before native dispatch. The cost-record fsync advances to 130 and
        // must not be retroactively charged as pre-dispatch queue time.
        assert_eq!(clock.load(Ordering::SeqCst), 130);
        match returned {
            Returned::Receipt => {
                let proposed = checked(decide_cell(checked(result), /*now_micros*/ 150));
                assert_eq!(proposed.receipt().cost.queue_age_micros, 102);
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
            Returned::NativeError => assert!(matches!(
                result,
                Err(CellExecutionError::Backend(NeuronModelError::Indeterminate))
            )),
            Returned::WrongMembership => assert!(matches!(
                result,
                Err(CellExecutionError::ModelBindingMismatch)
            )),
            Returned::CorruptReceipt => {
                assert!(matches!(result, Err(CellExecutionError::Backend(_))))
            }
        }
        drop(journal);
        let mut journal = checked(CellOwnerJournalV1::open(
            fixture.file("journal"),
            fixture.witness(),
            specs.clone(),
            /*max_records*/ 64,
        ));
        let pending =
            checked(journal.pending_inference(&request.scope)).expect("original pending request");
        assert_eq!(pending.host_queue_age_micros, Some(99));
        let inferred = checked(recover_cell_inference(
            &definition,
            &journal,
            &Encoder,
            request,
            &mut batch,
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
        assert_eq!((batch.calls, batch.reads), (1, 1));
        assert_eq!(checked(journal.pending_inference(&committed.scope)), None);
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

use super::*;
use crate::SharedCpuNeuronInferenceControlV3;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;

struct BlockingClock {
    block_next: AtomicBool,
    entered: mpsc::SyncSender<()>,
    resume: Mutex<mpsc::Receiver<()>>,
}

impl AuthorityClock for BlockingClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if self.block_next.swap(false, Ordering::SeqCst) {
            self.entered.send(()).expect("entered physical call");
            self.resume
                .lock()
                .expect("resume receiver")
                .recv_timeout(Duration::from_secs(5))
                .expect("release actual physical call");
        }
        Ok(1_000)
    }
}

#[test]
fn goal_scope_clones_reuse_one_loaded_cpu_and_original_writer_without_a_slot_guard() {
    let (directory, path, pin, encoder, head) = installed_model();
    let driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned model");
    let request = NeuronFeatureRequestV1 {
        request_id: StableId::new("cpu.scope.one").expect("request"),
        generation: Generation::new(1).expect("model generation"),
        model_id: StableId::new(driver.manifest().model_id.clone()).expect("model"),
        encoder_digest: encoder.parse().expect("encoder"),
        head_digest: head.parse().expect("head"),
        weights_digest: driver.manifest().weights_digest.parse().expect("weights"),
        input_digest: pin,
        feature_vector_q24: vec![2 << 24, 4 << 24],
        expected_output_width: 1,
    };
    let journal = directory.path().join("scope-shared-control.log");
    let control = DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("sole writer");
    let (entered_send, entered) = mpsc::sync_channel(1);
    let (resume, resume_receive) = mpsc::sync_channel(1);
    let clock = Arc::new(BlockingClock {
        block_next: AtomicBool::new(false),
        entered: entered_send,
        resume: Mutex::new(resume_receive),
    });
    let physical = CpuNeuronInferenceControlV1::open(control, clock.clone(), &path, pin, config())
        .expect("one physical load");
    let mut current = SharedCpuNeuronInferenceControlV3::new(physical);
    let mut successor = current.clone();
    let mut next = request.clone();
    next.request_id = StableId::new("cpu.scope.two").expect("next request");
    clock.block_next.store(true, Ordering::SeqCst);
    let first_request = request.clone();
    let executing = std::thread::spawn(move || {
        let receipt = current
            .execute_feature(&first_request)
            .expect("actual first physical execution");
        (current, receipt)
    });
    entered
        .recv_timeout(Duration::from_secs(5))
        .expect("physical invocation holds its lease");
    assert_eq!(
        successor.execute_feature(&next),
        Err(NeuronModelError::Unavailable)
    );
    assert_eq!(
        successor.reconcile_feature(&request),
        Err(NeuronModelError::Unavailable)
    );
    resume.send(()).expect("release physical call");
    let (first, original) = executing.join().expect("joined physical owner");
    assert_eq!(
        (original.drive_q24.clone(), original.prediction_q24.clone()),
        (vec![17 * (1 << 24) / 8], vec![11 * (1 << 24) / 8])
    );
    assert_eq!(
        successor.reconcile_feature(&request).expect("first truth"),
        DurableNeuronFeatureResolutionV2::Observed(Box::new(original.clone()))
    );
    // Cloning the current physical port never reopens its model source. The
    // fixture removes that source only after the actual loader has consumed it.
    std::fs::remove_file(path).expect("retire fixture source");
    drop(first);
    assert!(DurableInferenceControl::open(&journal, /*capacity*/ 8).is_err());
    let next_receipt = successor
        .execute_feature(&next)
        .expect("same loaded CPU on the second scope");
    assert_eq!(next_receipt.drive_q24, original.drive_q24);
    let mut invalid = next.clone();
    invalid.generation = Generation::new(2).expect("foreign model generation");
    assert_eq!(
        successor.execute_feature(&invalid),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(
        successor
            .execute_feature(&next)
            .expect("slot returned on rejection"),
        next_receipt
    );
    drop(successor);
    let recovered =
        DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("original reopen");
    assert_eq!(recovered.resident_feature_records(), 2);
    for (request, receipt) in [(request, original), (next, next_receipt)] {
        assert_eq!(
            recovered
                .feature_record(&request)
                .expect("original record")
                .expect("exists")
                .state,
            codex_hepta_infer_core::durable_control::feature::FeatureOperationStateV1::Observed(
                Box::new(receipt)
            )
        );
    }
}

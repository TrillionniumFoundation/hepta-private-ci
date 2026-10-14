use super::*;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{channel, RecvTimeoutError};
use std::thread;
use std::time::{Duration, Instant};

use codex_hepta_infer_core::{
    NeuronFeatureObservationV1, NeuronFeatureRequestV1, NeuronFeatureReceiptV1,
    NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1,
    build_neuron_feature_receipt_v1,
};
use crate::{
    AmcnFencedNeuronModelPort, NeuronInferenceControlPort, NeuronModelPort,
};

fn d(bytes: &str) -> Digest32 {
    Digest32::of_bytes(bytes.as_bytes())
}
fn id(s: &str) -> StableId {
    StableId::new(s).expect("test identifier")
}
fn generation() -> Generation {
    Generation::new(7).expect("test generation")
}
fn header() -> AmcnEpochHeaderV1 {
    AmcnEpochHeaderV1 {
        scope: id("amcn:epoch:tenant"),
        generation: generation(),
        sequence: 1,
        source_epoch: 1,
        withdrawal_epoch: 1,
        artifacts_epoch: 1,
        source_frontier_digest: d("source.cut.1"),
        withdrawal_head_digest: d("withdrawal.1"),
        quarantine_head_digest: d("quarantine.1"),
        runtime_anchor_digest: d("runtime.anchor.1"),
        event_digest: d("event.1"),
        predecessor_event_digest: Digest32::ZERO,
    }
}
fn request() -> NeuronModelRequestV1 {
    NeuronModelRequestV1 {
        request_id: id("amcn:epoch:tick"),
        config_id: id("amcn:epoch:config"),
        generation: generation(),
        model_id: id("amcn:epoch:model"),
        encoder_digest: d("encoder"),
        head_digest: d("head"),
        weights_digest: d("weights"),
        input_digest: d("input"),
        feature_vector_q24: vec![1 << 22, -(1 << 21)],
        expected_output_width: 3,
    }
}
fn binding(req: &NeuronModelRequestV1, h: &AmcnEpochHeaderV1, artifact: Digest32)
    -> AmcnFencedModelBindingV1
{
    AmcnFencedModelBindingV1 {
        scope: h.scope.clone(),
        request_id: req.request_id.clone(),
        config_id: req.config_id.clone(),
        generation: req.generation,
        model_id: req.model_id.clone(),
        encoder_digest: req.encoder_digest,
        head_digest: req.head_digest,
        weights_digest: req.weights_digest,
        input_digest: req.input_digest,
        expected_output_width: req.expected_output_width,
        artifact_manifest_digest: artifact,
        source_frontier_digest: h.source_frontier_digest,
        withdrawal_registry_head_digest: h.withdrawal_head_digest,
        quarantine_journal_head_digest: h.quarantine_head_digest,
        runtime_anchor_digest: h.runtime_anchor_digest,
    }
}
fn index() -> AmcnShadowEpochIndex {
    let h = header();
    AmcnShadowEpochIndex::from_external_floor(
        h.clone(), &h, [d("artifact.a"), d("artifact.b")], [],
    ).expect("original current floor registered by test")
}
fn source_withdrawal_successor(prev: &AmcnEpochHeaderV1) -> AmcnEpochHeaderV1 {
    AmcnEpochHeaderV1 {
        sequence: prev.sequence + 1,
        source_epoch: prev.source_epoch + 1,
        withdrawal_epoch: prev.withdrawal_epoch + 1,
        artifacts_epoch: prev.artifacts_epoch + 1,
        source_frontier_digest: d("source.cut.2"),
        withdrawal_head_digest: d("withdrawal.2"),
        quarantine_head_digest: d("quarantine.2"),
        event_digest: d("event.2"),
        predecessor_event_digest: prev.event_digest,
        ..prev.clone()
    }
}
struct ActualControl {
    called: Arc<AtomicUsize>,
    shared_epoch: AmcnShadowEpochIndex,
}
impl NeuronInferenceControlPort for ActualControl {
    fn execute_feature(&mut self, req: &NeuronFeatureRequestV1)
        -> Result<NeuronFeatureReceiptV1, NeuronModelError>
    {
        self.called.fetch_add(1, Ordering::SeqCst);
        assert!(
            matches!(self.shared_epoch.state.try_write(), Err(std::sync::TryLockError::WouldBlock)),
            "original InferenceControl must execute WHILE the source epoch is read-locked"
        );
        build_neuron_feature_receipt_v1(
            req,
            NeuronModelRuntimeTupleV1 {
                model_id: req.model_id.clone(),
                model_manifest_digest: d("manifest"),
                weights_digest: req.weights_digest,
                tokenizer_digest: d("tokenizer"),
                preprocessor_digest: d("preprocessor"),
                quantization_digest: d("quantization"),
                runtime_digest: d("runtime"),
                device_digest: d("host-device"),
            },
            NeuronFeatureObservationV1 {
                encoder_digest: req.encoder_digest,
                head_digest: req.head_digest,
                drive_q24: vec![1 << 24; req.expected_output_width],
                prediction_q24: vec![0; req.expected_output_width],
                observed_memory_bytes: 1024,
                transient_allocation_bytes: 256,
                queue_age_micros: 1,
                latency_micros: 7,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            }
        ).map_err(|_| NeuronModelError::Rejected)
    }
}

#[test]
fn amcn_epoch_shadow_original_inference_port_holds_constant_time_read_lease() {
    let shared = index();
    let req = request();
    let token = shared.header().expect("snapshot");
    let expected = binding(&req, &token, d("artifact.a"));
    let count = Arc::new(AtomicUsize::new(0));
    let mut control = ActualControl {
        called: Arc::clone(&count), shared_epoch: shared.clone(),
    };
    let mut lease = shared.candidate_fence(token);
    let mut model = AmcnFencedNeuronModelPort::new(&mut lease, &mut control, expected);
    let output = model.execute(&req).expect("actual receipt verified through original port");
    assert_eq!(output.drive_q24, vec![1 << 24; req.expected_output_width]);
    assert_eq!(count.load(Ordering::SeqCst), 1);
    assert!(!AMCN_EPOCH_SHADOW_PRODUCTION_ACCEPTED);
}

#[test]
fn amcn_epoch_shadow_source_withdrawal_blocks_old_head_even_if_bytes_reappear() {
    let shared = index();
    let req = request();
    let old = shared.header().expect("old cut");
    let first_binding = binding(&req, &old, d("artifact.a"));
    let count = Arc::new(AtomicUsize::new(0));
    let mut control = ActualControl { called: Arc::clone(&count), shared_epoch: shared.clone() };
    let mut initial = shared.candidate_fence(old.clone());
    let mut port = AmcnFencedNeuronModelPort::new(&mut initial, &mut control, first_binding.clone());
    port.execute(&req).expect("initial research model");
    assert_eq!(count.load(Ordering::SeqCst), 1);

    let next = source_withdrawal_successor(&old);
    shared.observe_committed_owner_change(&old, next.clone(), [], [d("artifact.a")])
        .expect("original owner reports durable withdrawal, no power is granted");
    assert_eq!(port.execute(&req), Err(NeuronModelError::Rejected));
    assert_eq!(count.load(Ordering::SeqCst), 1);
    drop(port);
    let mut later = shared.candidate_fence(next.clone());
    let new_binding = binding(&req, &next, d("artifact.a"));
    let mut bad = AmcnFencedNeuronModelPort::new(&mut later, &mut control, new_binding);
    assert_eq!(bad.execute(&req), Err(NeuronModelError::Rejected));
    assert_eq!(count.load(Ordering::SeqCst), 1);
    drop(bad);
    let mut allowed = shared.candidate_fence(next.clone());
    let valid = binding(&req, &next, d("artifact.b"));
    AmcnFencedNeuronModelPort::new(&mut allowed, &mut control, valid)
        .execute(&req).expect("independent unaffected research Cell");
    assert_eq!(count.load(Ordering::SeqCst), 2);
}

#[test]
fn amcn_epoch_shadow_concurrent_owner_epoch_write_waits_for_reader_model() {
    let shared = index();
    let req = request();
    let old = shared.header().expect("current owner floor");
    let bound = binding(&req, &old, d("artifact.a"));
    let (inside_tx, inside_rx) = channel::<()>();
    let (release_tx, release_rx) = channel::<()>();
    let (writer_begin_tx, writer_begin_rx) = channel::<()>();
    let (writer_end_tx, writer_end_rx) = channel::<()>();
    let for_model = shared.clone();
    let for_writer = shared.clone();
    let req_thread = req.clone();
    let bound_thread = bound.clone();
    let old_writer = old.clone();

    let model_thread = thread::spawn(move || {
        let mut lease = for_model.candidate_fence(old);
        lease.with_fenced_candidate(&bound_thread, &req_thread, || {
            inside_tx.send(()).expect("model acquired epoch read lease");
            release_rx.recv_timeout(Duration::from_secs(5))
                .map_err(|_| NeuronModelError::Indeterminate)?;
            Ok::<_, NeuronModelError>(())
        })
    });
    inside_rx.recv_timeout(Duration::from_secs(5)).expect("read model entered");
    let writer = thread::spawn(move || {
        writer_begin_tx.send(()).expect("writer start");
        let result = for_writer.observe_committed_owner_change(
            &old_writer, source_withdrawal_successor(&old_writer),
            [], [d("artifact.a")],
        );
        writer_end_tx.send(result).expect("writer done");
    });
    writer_begin_rx.recv_timeout(Duration::from_secs(5)).expect("writer attempted epoch");
    assert!(
        matches!(writer_end_rx.recv_timeout(Duration::from_millis(80)),
                 Err(RecvTimeoutError::Timeout)),
        "an owner withdrawal must WAIT while model holds its read lease"
    );
    release_tx.send(()).expect("model released");
    model_thread.join().expect("model thread").expect("old invocation permitted under lease");
    writer.join().expect("writer thread");
    writer_end_rx.recv_timeout(Duration::from_secs(5))
        .expect("writer completes after model")
        .expect("withdrawal committed");
    assert_eq!(shared.header().expect("updated header").sequence, 2);
}

#[test]
fn amcn_epoch_shadow_rollback_fork_and_malformed_owner_transitions_fail() {
    let shared = index();
    let original = shared.header().expect("base");
    let successor = source_withdrawal_successor(&original);

    let mut wrong_previous = successor.clone();
    wrong_previous.predecessor_event_digest = d("not-original-head");
    assert_eq!(
        shared.observe_committed_owner_change(&original, wrong_previous, [], []),
        Err(NeuronModelError::Rejected)
    );
    let mut fake_source = successor.clone();
    fake_source.source_epoch = original.source_epoch;
    assert_eq!(
        shared.observe_committed_owner_change(&original, fake_source, [], []),
        Err(NeuronModelError::Rejected)
    );
    let mut old_generation = successor.clone();
    old_generation.generation = Generation::new(8).expect("new generation");
    assert_eq!(
        shared.observe_committed_owner_change(&original, old_generation, [], []),
        Err(NeuronModelError::Rejected)
    );
    shared.observe_committed_owner_change(
        &original, successor.clone(), [], [d("artifact.a")],
    ).expect("first withdrawal");
    assert_eq!(
        shared.observe_committed_owner_change(&original, successor.clone(), [], []),
        Err(NeuronModelError::Rejected)
    );
    // Restoring internally valid older bytes cannot satisfy an independent
    // floor retained at the LATEST version.
    assert!(matches!(
        AmcnShadowEpochIndex::from_external_floor(
            original, &successor, [d("artifact.a")], [],
        ), Err(NeuronModelError::Rejected)
    ));
}

#[test]
fn amcn_epoch_shadow_unregistered_head_is_never_a_grant() {
    let shared = index();
    let req = request();
    let old = shared.header().expect("header");
    let bound = binding(&req, &old, d("unregistered-head"));
    let mut lease = shared.candidate_fence(old);
    let count = AtomicUsize::new(0);
    let result = lease.with_fenced_candidate(&bound, &req, || {
        count.fetch_add(1, Ordering::SeqCst);
        Ok::<_, NeuronModelError>(())
    });
    assert_eq!(result, Err(NeuronModelError::Rejected));
    assert_eq!(count.load(Ordering::SeqCst), 0);
}

#[test]
fn amcn_epoch_shadow_steady_state_1024_calls_are_bounded_header_checks_not_store_scans() {
    let shared = index();
    let req = request();
    let token = shared.header().expect("current");
    let binding = binding(&req, &token, d("artifact.b"));
    let count = AtomicUsize::new(0);
    let start = Instant::now();
    for _ in 0..1024 {
        let mut fence = shared.candidate_fence(token.clone());
        fence.with_fenced_candidate(&binding, &req, || {
            count.fetch_add(1, Ordering::Relaxed);
            Ok::<_, NeuronModelError>(())
        }).expect("indexed research eligibility");
    }
    let total = start.elapsed().as_micros();
    assert_eq!(count.load(Ordering::Relaxed), 1024);
    assert!(total < 60_000_000, "research test loop must remain bounded");
    eprintln!(
        "AMCN Shadow Epoch (not target-host latency qualification): \
         1024 sequential checks / {total} observed microseconds"
    );
}

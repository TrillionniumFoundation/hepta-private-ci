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
        enrolled_manifest_set_digest: digest_manifest_set(
            ENROLLED_DOMAIN,
            &HashSet::from([d("artifact.a"), d("artifact.b")]),
        ),
        quarantined_manifest_set_digest: digest_manifest_set(
            QUARANTINED_DOMAIN, &HashSet::new(),
        ),
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
        quarantined_manifest_set_digest: digest_manifest_set(
            QUARANTINED_DOMAIN, &HashSet::from([d("artifact.a")]),
        ),
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
    for _ in 0..500 {
        if shared.owner_change_pending() {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert!(shared.owner_change_pending(),
            "writer publishes pending withdrawal BEFORE waiting for old read leases");
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
fn amcn_epoch_shadow_rollback_fork_and_malformed_owner_transitions_fail_closed() {
    let original = header();
    let successor = source_withdrawal_successor(&original);
    let mut wrong_previous = successor.clone();
    wrong_previous.predecessor_event_digest = d("not-original-head");
    let mut fake_source = successor.clone();
    fake_source.source_epoch = original.source_epoch;
    let mut wrong_generation = successor.clone();
    wrong_generation.generation = Generation::new(8).expect("new generation");

    // An indeterminate attempted owner update is a durable *fence*, not an
    // excuse to clear pending and continue serving prior parameters.
    for wrong in [wrong_previous, fake_source, wrong_generation] {
        let shared = index();
        assert_eq!(
            shared.observe_committed_owner_change(&original, wrong, [], []),
            Err(NeuronModelError::Rejected)
        );
        assert!(shared.owner_change_pending());
        assert_eq!(shared.header(), Err(NeuronModelError::Indeterminate));
        let req = request();
        let original_binding = binding(&req, &original, d("artifact.a"));
        let called = AtomicUsize::new(0);
        let mut fence = shared.candidate_fence(original.clone());
        assert_eq!(
            fence.with_fenced_candidate(&original_binding, &req, || {
                called.fetch_add(1, Ordering::SeqCst);
                Ok::<_, NeuronModelError>(())
            }),
            Err(NeuronModelError::Rejected)
        );
        assert_eq!(called.load(Ordering::SeqCst), 0);
    }

    let shared = index();
    shared.observe_committed_owner_change(
        &original, successor.clone(), [], [d("artifact.a")],
    ).expect("first current withdrawal");
    assert!(!shared.owner_change_pending());
    assert_eq!(
        shared.observe_committed_owner_change(&original, successor.clone(), [], []),
        Err(NeuronModelError::Rejected)
    );
    assert!(shared.owner_change_pending());

    // A restored older index cannot authenticate a newer independent floor.
    assert!(matches!(
        AmcnShadowEpochIndex::from_external_floor(
            original, &successor, [d("artifact.a")], [],
        ),
        Err(NeuronModelError::Rejected)
    ));
}

#[test]
fn amcn_epoch_shadow_writer_pending_refuses_second_head_without_waiting_for_model() {
    let shared = index();
    let base = shared.header().expect("research floor");
    let req = request();
    let bound = binding(&req, &base, d("artifact.b"));
    let (entered_tx, entered_rx) = channel::<()>();
    let (release_tx, release_rx) = channel::<()>();
    let first = shared.clone();
    let original = base.clone();

    let first_thread = thread::spawn(move || {
        let mut lease = first.candidate_fence(original);
        lease.with_fenced_candidate(&bound, &req, || {
            entered_tx.send(()).expect("held read lease");
            release_rx.recv_timeout(Duration::from_secs(5))
                .map_err(|_| NeuronModelError::Indeterminate)?;
            Ok::<_, NeuronModelError>(())
        })
    });
    entered_rx.recv_timeout(Duration::from_secs(5)).expect("first Cell inside lease");
    let write = shared.clone();
    let base_for_writer = base.clone();
    let writer = thread::spawn(move || {
        write.observe_committed_owner_change(
            &base_for_writer, source_withdrawal_successor(&base_for_writer),
            [], [d("artifact.a")],
        )
    });
    for _ in 0..500 {
        if shared.owner_change_pending() {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert!(shared.owner_change_pending(), "withdrawal pending reaches all Cells");
    // New work must be rejected. We cannot acquire a second reader on every
    // RwLock implementation while a writer is queued, so run it on another
    // thread rather than deadlocking the first model's release signal.
    let next = shared.clone();
    let request_second = request();
    let expected_second = base.clone();
    let second = thread::spawn(move || {
        let new_bound = binding(&request_second, &expected_second, d("artifact.b"));
        let counter = AtomicUsize::new(0);
        let mut lease = next.candidate_fence(expected_second);
        let reply = lease.with_fenced_candidate(&new_bound, &request_second, || {
            counter.fetch_add(1, Ordering::SeqCst);
            Ok::<_, NeuronModelError>(())
        });
        (reply, counter.load(Ordering::SeqCst))
    });
    release_tx.send(()).expect("release first reader");
    first_thread.join().expect("first model").expect("started before withdrawal pending");
    writer.join().expect("writer").expect("withdrawal completed");
    let (second_reply, new_calls) = second.join().expect("second reader");
    assert_eq!(second_reply, Err(NeuronModelError::Rejected));
    assert_eq!(new_calls, 0);
}

#[test]
fn amcn_epoch_shadow_exact_signed_floor_cannot_restore_omitted_quarantine_member() {
    let old = header();
    let committed = source_withdrawal_successor(&old);
    // Same current header and correct enrolled population. The restored
    // payload deliberately hides a withdrawn Head: its commitment differs.
    assert!(matches!(
        AmcnShadowEpochIndex::from_external_floor(
            committed.clone(), &committed,
            [d("artifact.a"), d("artifact.b")], [],
        ),
        Err(NeuronModelError::Rejected)
    ));
    // Deleting a registered candidate while claiming the exact current
    // floor is equally invalid.
    assert!(matches!(
        AmcnShadowEpochIndex::from_external_floor(
            old.clone(), &old, [d("artifact.b")], [],
        ),
        Err(NeuronModelError::Rejected)
    ));
    let valid = AmcnShadowEpochIndex::from_external_floor(
        committed.clone(), &committed,
        [d("artifact.a"), d("artifact.b")], [d("artifact.a")],
    ).expect("exactly signed-set-bound restore");
    let req = request();
    let b = binding(&req, &committed, d("artifact.a"));
    let mut fence = valid.candidate_fence(committed);
    assert_eq!(
        fence.with_fenced_candidate(&b, &req, || Ok::<_, NeuronModelError>(())),
        Err(NeuronModelError::Rejected)
    );
}

#[test]
fn amcn_epoch_shadow_owner_update_must_commit_complete_candidate_sets() {
    let original = header();
    let successor = source_withdrawal_successor(&original);
    let mut wrong = successor.clone();
    wrong.quarantined_manifest_set_digest = d("omitted-single-revoked-head");
    let epoch = index();
    assert_eq!(
        epoch.observe_committed_owner_change(&original, wrong, [], [d("artifact.a")]),
        Err(NeuronModelError::Rejected)
    );
    assert!(epoch.owner_change_pending());
    assert_eq!(epoch.header(), Err(NeuronModelError::Indeterminate));

    // Exact same candidate membership; only a proper owner mutation may
    // enlarge the index. A newly admitted cell must be reflected in the
    // enrollment commitment and monotonic Artifact epoch.
    let epoch = index();
    let mut next = original.clone();
    next.sequence += 1;
    next.predecessor_event_digest = original.event_digest;
    next.event_digest = d("event.new-Cell");
    next.artifacts_epoch += 1;
    next.quarantine_head_digest = d("quarantine.new-Cell");
    next.enrolled_manifest_set_digest = digest_manifest_set(
        ENROLLED_DOMAIN,
        &HashSet::from([d("artifact.a"), d("artifact.b"), d("artifact.c")]),
    );
    epoch.observe_committed_owner_change(
        &original, next.clone(), [d("artifact.c")], [],
    ).expect("exactly committed enrollment");
    let req = request();
    let bound = binding(&req, &next, d("artifact.c"));
    let mut lease = epoch.candidate_fence(next);
    lease.with_fenced_candidate(&bound, &req, || Ok::<_, NeuronModelError>(()))
        .expect("new enrolled candidate exists, without any production grant");
    assert!(!AMCN_EPOCH_SHADOW_PRODUCTION_ACCEPTED);
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
fn amcn_epoch_shadow_2048_distinct_cells_share_one_bounded_encoder_epoch() {
    let h = header();
    let manifests: Vec<Digest32> = (0..2048)
        .map(|n| d(&format!("shared-stem-cell:{n}")))
        .collect();
    let mut current = h.clone();
    current.enrolled_manifest_set_digest = digest_manifest_set(
        ENROLLED_DOMAIN, &manifests.iter().copied().collect(),
    );
    let index = AmcnShadowEpochIndex::from_external_floor(
        current.clone(), &current, manifests.iter().copied(), [],
    ).expect("source/Artifact owner snapshot enrolled research population");
    let req = request();
    let called = AtomicUsize::new(0);
    let started = Instant::now();
    for manifest in manifests {
        let b = binding(&req, &current, manifest);
        let mut reader = index.candidate_fence(current.clone());
        reader.with_fenced_candidate(&b, &req, || {
            called.fetch_add(1, Ordering::Relaxed);
            Ok::<_, NeuronModelError>(())
        }).expect("same shared Stem epoch for independently enrolled tiny Heads");
    }
    assert_eq!(called.load(Ordering::Relaxed), 2048);
    assert_eq!(index.header().expect("header").sequence, 1);
    eprintln!(
        "AMCN 2048 distinct source-bound Head lookups (fixture, not host p95): {} us",
        started.elapsed().as_micros()
    );
}

#[test]
fn amcn_epoch_shadow_adversarial_iterators_reject_before_unbounded_allocation() {
    use std::cell::Cell;
    let current = header();
    let consumed = Cell::new(0_usize);
    // This iterator represents more unique source/Head manifests than an
    // operator is permitted to register. The validator must stop at
    // MAX+1, not materialize the entire untrusted input first.
    let large = (0..(AMCN_EPOCH_MANIFEST_LIMIT + 20)).map(|i| {
        consumed.set(consumed.get() + 1);
        d(&format!("untrusted-Head-{i}"))
    });
    assert!(matches!(
        AmcnShadowEpochIndex::from_external_floor(
            current.clone(), &current, large, [],
        ), Err(NeuronModelError::Rejected)
    ));
    assert_eq!(consumed.get(), AMCN_EPOCH_MANIFEST_LIMIT + 1);

    let source = index();
    let valid = source.header().expect("actual floor");
    let next = source_withdrawal_successor(&valid);
    let exceeded = Cell::new(0);
    let too_many = (0..(AMCN_EPOCH_QUARANTINE_LIMIT + 99)).map(|i| {
        exceeded.set(exceeded.get() + 1);
        d(&format!("untrusted-revocation-{i}"))
    });
    assert_eq!(
        source.observe_committed_owner_change(&valid, next, [], too_many),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(exceeded.get(), AMCN_EPOCH_QUARANTINE_LIMIT + 1);
    // Once a conflicting external withdrawal is attempted the research
    // cache cannot resume on a stale assumption, even after rejection.
    assert!(source.owner_change_pending());
    assert_eq!(source.header(), Err(NeuronModelError::Indeterminate));

    assert!(matches!(
        AmcnShadowEpochIndex::from_external_floor(
            current.clone(), &current,
            [d("artifact.a"), d("artifact.a")], [],
        ), Err(NeuronModelError::Rejected)
    ));
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

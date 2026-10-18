use super::*;
use crate::NeuronOperationFailureV2;
use crate::NeuronOperationStatusV2;

fn bootstrap(fixture: &Fixture, witness: MemoryWitness) -> NeuronRuntimeV2<MemoryWitness> {
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store, index) = contexts(&native, &config, &body);
    checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store,
        index,
        witness,
    ))
}

fn recover(fixture: &Fixture, witness: MemoryWitness) -> NeuronRuntimeV2<MemoryWitness> {
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store, index) = contexts(&native, &config, &body);
    checked(NeuronRuntimeV2::recover(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store,
        index,
        witness,
    ))
}

pub(super) struct RejectedModel;
impl NeuronModelPort for RejectedModel {
    fn execute(
        &mut self,
        _: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}
impl DurableNeuronModelPort for RejectedModel {
    fn reconcile(
        &mut self,
        _: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

pub(super) struct UnknownModel {
    pub(super) executions: usize,
    pub(super) queries: usize,
}
impl NeuronModelPort for UnknownModel {
    fn execute(
        &mut self,
        _: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.executions += 1;
        Err(NeuronModelError::Indeterminate)
    }
}
impl DurableNeuronModelPort for UnknownModel {
    fn reconcile(
        &mut self,
        _: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        self.queries += 1;
        Ok(NeuronModelResolutionV2::Unknown)
    }
}

#[test]
fn wrong_dimension_leaves_no_reservation_and_does_not_pin_the_next_request() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture, MemoryWitness::default());
    let mut invalid = input(1, Digest32::ZERO);
    invalid.feature_vector_q24.pop();
    invalid.input_feature_digest = canonical_feature_vector_digest_v1(&invalid.feature_vector_q24);
    let digest = checked(invalid.semantic_digest());
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    assert!(matches!(
        runtime.tick_guarded(&mut model, invalid.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::Configuration(
            NeuronRuntimeError::InvalidInput
        ))
    ));
    assert_eq!(
        checked(runtime.query_operation(&invalid.tick_id, digest)),
        NeuronOperationStatusV2::NotRecorded
    );
    assert_eq!(checked(runtime.index.pending()), None);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn foreign_scope_and_stale_clock_are_rejected_before_prepare() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture, MemoryWitness::default());
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    let mut foreign = input(1, Digest32::ZERO);
    foreign.subject_id = id("wrong.subject");
    assert!(matches!(
        runtime.tick_guarded(&mut model, foreign, &mut Allow),
        Err(NeuronRuntimeV2Error::ContextMismatch)
    ));
    assert_eq!(checked(runtime.index.pending()), None);
    let first = checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    let mut stale = input(2, first.next_anchor.checkpoint_digest);
    stale.monotonic_time_micros = 1_000;
    assert!(matches!(
        runtime.tick_guarded(&mut model, stale, &mut Allow),
        Err(NeuronRuntimeV2Error::Mechanism(SparseError::Clock))
    ));
    assert_eq!(checked(runtime.index.pending()), None);
    checked(runtime.tick_guarded(
        &mut model,
        input(2, first.next_anchor.checkpoint_digest),
        &mut Allow,
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[test]
fn terminal_failure_survives_restart_prevents_resurrection_and_releases_admission() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    let request = input(1, Digest32::ZERO);
    let digest = checked(request.semantic_digest());
    assert!(matches!(
        runtime.tick_guarded(&mut RejectedModel, request.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::TerminalFailure(
            NeuronOperationFailureV2::ModelRejected
        ))
    ));
    assert_eq!(checked(runtime.index.pending()), None);
    drop(runtime);
    let mut runtime = recover(&fixture, witness);
    assert_eq!(
        checked(runtime.query_operation(&request.tick_id, digest)),
        NeuronOperationStatusV2::Failed(NeuronOperationFailureV2::ModelRejected)
    );
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    assert!(matches!(
        runtime.tick_guarded(&mut model, request.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::TerminalFailure(
            NeuronOperationFailureV2::ModelRejected
        ))
    ));
    let mut changed = request.clone();
    changed.monotonic_time_micros += 1;
    assert!(matches!(
        runtime.tick_guarded(&mut model, changed, &mut Allow),
        Err(NeuronRuntimeV2Error::Index(
            NeuronRuntimeIndexError::Conflict
        ))
    ));
    let mut next = request;
    next.tick_id = id("replacement.request");
    checked(runtime.tick_guarded(&mut model, next, &mut Allow));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn indeterminate_model_is_query_only_before_and_after_restart() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    let request = input(1, Digest32::ZERO);
    let digest = checked(request.semantic_digest());
    let mut model = UnknownModel {
        executions: 0,
        queries: 0,
    };
    assert!(matches!(
        runtime.tick_guarded(&mut model, request.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::Model(NeuronModelError::Indeterminate))
    ));
    assert_eq!(
        checked(runtime.query_operation(&request.tick_id, digest)),
        NeuronOperationStatusV2::OutcomeUnknown
    );
    assert!(
        runtime
            .tick_guarded(&mut model, request.clone(), &mut Allow)
            .is_err()
    );
    assert_eq!((model.executions, model.queries), (1, 1));
    drop(runtime);
    let mut runtime = recover(&fixture, witness);
    assert!(
        runtime
            .tick_guarded(&mut model, request, &mut Allow)
            .is_err()
    );
    assert_eq!((model.executions, model.queries), (1, 2));
}

#[test]
fn reserved_and_dispatched_recovery_are_distinct() {
    for dispatched in [false, true] {
        let fixture = Fixture::new();
        let witness = MemoryWitness::default();
        let mut runtime = bootstrap(&fixture, witness.clone());
        let request = input(1, Digest32::ZERO);
        let digest = checked(request.semantic_digest());
        let key = NeuronOperationKeyV2 {
            tick_id: request.tick_id.clone(),
            input_semantic_digest: digest,
        };
        checked(runtime.index.prepare(key.clone(), None));
        if dispatched {
            checked(runtime.index.mark_dispatched(&key));
        }
        drop(runtime);
        let mut runtime = recover(&fixture, witness);
        assert_eq!(
            checked(runtime.query_operation(&request.tick_id, digest)),
            if dispatched {
                NeuronOperationStatusV2::OutcomeUnknown
            } else {
                NeuronOperationStatusV2::NotExecuted
            }
        );
        let calls = Arc::new(AtomicUsize::new(0));
        let mut model = FakeDurableModel::new(Arc::clone(&calls));
        assert_eq!(
            runtime
                .tick_guarded(&mut model, request, &mut Allow)
                .is_ok(),
            !dispatched
        );
        assert_eq!(calls.load(Ordering::SeqCst), usize::from(!dispatched));
    }
}

#[test]
fn lost_terminal_failure_ack_recovers_as_failure_not_as_a_rerunnable_request() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    let request = input(1, Digest32::ZERO);
    let digest = checked(request.semantic_digest());
    let key = NeuronOperationKeyV2 {
        tick_id: request.tick_id.clone(),
        input_semantic_digest: digest,
    };
    checked(runtime.index.prepare(key.clone(), None));
    checked(runtime.index.mark_dispatched(&key));
    runtime.index.fail_next_append_after_sync();
    assert!(matches!(
        runtime.tick_guarded(&mut RejectedModel, request.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::Index(
            NeuronRuntimeIndexError::Indeterminate
        ))
    ));
    assert!(runtime.query_operation(&request.tick_id, digest).is_err());
    drop(runtime);
    let mut runtime = recover(&fixture, witness);
    assert_eq!(
        checked(runtime.query_operation(&request.tick_id, digest)),
        NeuronOperationStatusV2::Failed(NeuronOperationFailureV2::ModelRejected)
    );
}

#[test]
fn poisoned_store_is_not_reported_as_absence_and_never_blindly_reexecutes() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    runtime
        .store
        .fail_next_append(crate::generation_store_v2::GenerationStoreFailpointV2::DuringFrameWrite);
    let request = input(1, Digest32::ZERO);
    let digest = checked(request.semantic_digest());
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    assert!(
        runtime
            .tick_guarded(&mut model, request.clone(), &mut Allow)
            .is_err()
    );
    assert!(runtime.query_operation(&request.tick_id, digest).is_err());
    drop(runtime);
    let mut runtime = recover(&fixture, witness);
    assert_eq!(
        checked(runtime.query_operation(&request.tick_id, digest)),
        NeuronOperationStatusV2::OutcomeUnknown
    );
    assert!(
        runtime
            .tick_guarded(&mut model, request, &mut Allow)
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn real_sync_measurements_are_separate_from_the_original_durable_receipt() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture, MemoryWitness::default());
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(calls);
    let request = input(1, Digest32::ZERO);
    let first = checked(runtime.tick_guarded(&mut model, request.clone(), &mut Allow));
    let measurement = checked(runtime.last_measurement().cloned().ok_or("measured tick"));
    assert_eq!(
        measurement
            .store_after
            .io
            .since(measurement.store_before.io)
            .sync_calls,
        2
    );
    assert_eq!(
        measurement
            .index_after
            .io
            .since(measurement.index_before.io)
            .sync_calls,
        3
    );
    assert_eq!(measurement.witness_sync, None);
    assert!(measurement.store_after.file_bytes > measurement.store_before.file_bytes);
    assert_eq!(
        checked(runtime.tick_guarded(&mut model, request, &mut Allow)),
        first
    );
    let replay = checked(runtime.last_measurement().ok_or("measured replay"));
    assert_eq!(
        replay
            .store_after
            .io
            .since(replay.store_before.io)
            .sync_calls,
        0
    );
    assert_eq!(
        replay
            .index_after
            .io
            .since(replay.index_before.io)
            .sync_calls,
        0
    );
}

#[test]
fn repeated_failures_consume_bounded_history_and_do_not_dispatch_at_capacity() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture, MemoryWitness::default());
    for i in 0..16 {
        let mut request = input(1, Digest32::ZERO);
        request.tick_id = id(&format!("failed.{i}"));
        assert!(matches!(
            runtime.tick_guarded(&mut RejectedModel, request, &mut Allow),
            Err(NeuronRuntimeV2Error::TerminalFailure(_))
        ));
    }
    let capacity = checked(runtime.capacity_snapshot());
    assert_eq!(capacity.index.records, capacity.index.record_limit);
    assert!(capacity.index.near_limit());
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    assert!(matches!(
        runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow),
        Err(NeuronRuntimeV2Error::Index(
            NeuronRuntimeIndexError::Capacity
        ))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[cfg(unix)]
#[test]
fn path_replacement_is_detected_on_the_open_owner_before_further_work() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture, MemoryWitness::default());
    let saved = checked(fs::read(fixture.index()));
    checked(fs::rename(fixture.index(), fixture.0.join("old-index")));
    checked(fs::write(fixture.index(), saved));
    let request = input(1, Digest32::ZERO);
    assert!(
        runtime
            .query_operation(&request.tick_id, checked(request.semantic_digest()))
            .is_err()
    );
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    assert!(
        runtime
            .tick_guarded(&mut model, request, &mut Allow)
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[test]
#[ignore = "diagnostic benchmark, explicitly selected by exact-candidate qualification"]
fn runtime_v2_diagnostic_measurements() {
    use crate::FileNeuronWitnessStoreV2;
    use crate::NeuronWitnessContextV2;
    let source = checked(std::env::var("HEPTA_NEURON_DIAGNOSTIC_SOURCE_SHA"));
    assert_eq!(source.len(), 40);
    let executable = checked(std::env::current_exe());
    let executable_digest = Digest32::of_bytes(&checked(fs::read(executable))).to_string();
    for sample in 0..64 {
        let fixture = Fixture::new();
        let native = native_config();
        let config = runtime_config(&native);
        let body = body_bundle(native.generation);
        let (store_context, index_context) = contexts(&native, &config, &body);
        let witness_path = fixture.0.join("measured-witness");
        let witness_context = NeuronWitnessContextV2 {
            generation: native.generation,
            scope: scope(),
            key_epoch: 1,
            deletion_epoch: 1,
            max_records: 16,
        };
        let witness = checked(FileNeuronWitnessStoreV2::create(
            &witness_path,
            witness_context.clone(),
        ));
        let mut runtime = checked(NeuronRuntimeV2::bootstrap(
            &fixture.store(),
            &fixture.index(),
            native.clone(),
            scope(),
            config.clone(),
            body.clone(),
            store_context.clone(),
            index_context.clone(),
            witness,
        ));
        let mut model = FakeDurableModel::new(Arc::new(AtomicUsize::new(0)));
        checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
        let measurement = checked(
            runtime
                .last_measurement()
                .cloned()
                .ok_or("tick measurement"),
        );
        let witness_sync = checked(measurement.witness_sync.ok_or("real file witness measured"));
        assert_eq!(witness_sync.sync_calls, 1);
        assert_eq!(witness_sync.sync_errors, 0);
        drop(runtime);
        let started = Instant::now();
        let witness = checked(FileNeuronWitnessStoreV2::open_existing(
            &witness_path,
            witness_context,
        ));
        let recovered = checked(NeuronRuntimeV2::recover(
            &fixture.store(),
            &fixture.index(),
            native,
            scope(),
            config,
            body,
            store_context,
            index_context,
            witness,
        ));
        let recovery_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        assert_eq!(checked(recovered.pending_witness_count()), 0);
        let process_peak_rss_kib =
            fs::read_to_string("/proc/self/status")
                .ok()
                .and_then(|status| {
                    status.lines().find_map(|line| {
                        line.strip_prefix("VmHWM:")
                            .and_then(|value| value.split_whitespace().next())
                            .and_then(|value| value.parse::<u64>().ok())
                    })
                });
        println!(
            "NEURON_V2_DIAGNOSTIC {}",
            serde_json::json!({
                "schema": "hepta.neuron.diagnostic.v2",
                "source_sha": source,
                "test_binary_digest": executable_digest,
                "model_kind": "deterministic_fixture_not_production",
                "sample": sample,
                "measurement": measurement,
                "recovery_micros": recovery_micros,
                "process_peak_rss_kib": process_peak_rss_kib,
                "qualification": false,
            })
        );
    }
}

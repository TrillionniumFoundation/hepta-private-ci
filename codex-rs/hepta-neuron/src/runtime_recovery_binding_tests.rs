use super::*;

use std::io::Write;

use pretty_assertions::assert_eq;

#[derive(Clone, Default)]
struct CountingWitness {
    inner: MemoryWitness,
    swaps: Arc<AtomicU64>,
}

impl AnchorWitnessStore for CountingWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.swaps.fetch_add(1, Ordering::SeqCst);
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn configuration_drift_rejects_before_tail_repair_or_witness_catchup() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = CountingWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
        config.clone(),
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    checked(runtime.tick(&mut model, input(/*sequence*/ 1, Digest32::ZERO)));
    let acknowledged = checked(runtime.current_anchor()).expect("acknowledged checkpoint");
    witness.inner.fail_next_compare_and_swap();
    assert!(matches!(
        runtime.tick(
            &mut model,
            input(/*sequence*/ 2, acknowledged.checkpoint_digest)
        ),
        Err(NeuronRuntimeError::WitnessAfterCommit { .. })
    ));
    let latest = checked(runtime.current_anchor()).expect("unacknowledged durable checkpoint");
    drop(runtime);
    let valid_prefix = checked(fs::read(fixture.0.join("journal")));
    {
        let mut file = fixture.file();
        checked(std::io::Seek::seek(&mut file, std::io::SeekFrom::End(0)));
        checked(file.write_all(b"torn-tail"));
        checked(file.sync_all());
    }
    let original_bytes = checked(fs::read(fixture.0.join("journal")));
    let original_swaps = witness.swaps.load(Ordering::SeqCst);
    // These changes all pass native validation; only the complete persisted
    // runtime binding can reject their reuse of the old fast state.
    type RuntimeMutation = (&'static str, fn(&mut NeuronRuntimeConfigV1));
    let mutations: &[RuntimeMutation] = &[
        ("weights", |v| {
            v.weights_digest = Digest32::of_bytes(b"other")
        }),
        ("encoder", |v| {
            v.encoder_digest = Digest32::of_bytes(b"other")
        }),
        ("config_id", |v| {
            v.config_id = checked(StableId::new("other.config"))
        }),
        ("model_id", |v| {
            v.model_id = checked(StableId::new("other.model"))
        }),
        ("manifest", |v| {
            v.model_manifest_digest = Digest32::of_bytes(b"other")
        }),
        ("tokenizer", |v| {
            v.tokenizer_digest = Digest32::of_bytes(b"other")
        }),
        ("preprocessor", |v| {
            v.preprocessor_digest = Digest32::of_bytes(b"other")
        }),
        ("quantization", |v| {
            v.quantization_digest = Digest32::of_bytes(b"other")
        }),
        ("runtime", |v| {
            v.runtime_digest = Digest32::of_bytes(b"other")
        }),
        ("device", |v| v.device_digest = Digest32::of_bytes(b"other")),
        ("feature_dimension", |v| v.input_feature_dimension += 1),
        ("modulator_dimension", |v| v.modulator_dimension += 1),
        ("calibration", |v| {
            v.calibration.calibration_artifact_digest = Digest32::of_bytes(b"other")
        }),
        ("ood_artifact", |v| {
            v.calibration.ood_artifact_digest = Digest32::of_bytes(b"other")
        }),
        ("valid_from", |v| v.calibration.valid_from_sequence += 1),
        ("expires_after", |v| {
            v.calibration.expires_after_sequence += 1
        }),
        ("zero_confidence_error", |v| {
            v.calibration.zero_confidence_error_q24 -= 1
        }),
        ("in_domain_error", |v| {
            v.calibration.maximum_in_domain_error_q24 -= 1
        }),
        ("minimum_confidence", |v| {
            v.calibration.minimum_confidence_ppm += 1
        }),
        ("maximum_ood", |v| v.calibration.maximum_ood_ppm += 1),
        ("minimum_active", |v| v.calibration.minimum_active_ppm += 1),
        ("maximum_active", |v| v.calibration.maximum_active_ppm += 1),
        ("maximum_projection", |v| {
            v.calibration.maximum_projection_count += 1
        }),
        ("measured_ece", |v| v.calibration.measured_ece_ppm += 1),
        ("maximum_ece", |v| v.calibration.maximum_ece_ppm += 1),
        ("measured_false_acceptance", |v| {
            v.calibration.measured_false_acceptance_ppm += 1
        }),
        ("maximum_false_acceptance", |v| {
            v.calibration.maximum_false_acceptance_ppm += 1
        }),
        ("p95_latency", |v| {
            v.resource_envelope.p95_latency_micros += 1
        }),
        ("p99_latency", |v| {
            v.resource_envelope.p99_latency_micros += 1
        }),
        ("transient_allocation", |v| {
            v.resource_envelope.transient_allocation_bytes += 1
        }),
        ("checkpoint_bytes", |v| {
            v.resource_envelope.checkpoint_bytes += 1
        }),
        ("write_amplification", |v| {
            v.resource_envelope.write_amplification_ppm -= 1
        }),
    ];
    for (name, mutate) in mutations {
        let mut changed = config.clone();
        mutate(&mut changed);
        checked(changed.validate_native(&native));
        assert_eq!(
            NeuronRuntime::recover(
                fixture.file(),
                native.clone(),
                scope(),
                /*max_records*/ 4,
                changed,
                acknowledged,
                witness.clone(),
            )
            .err(),
            Some(NeuronRuntimeError::Journal(JournalError::ContextMismatch)),
            "{name} drift must not recover"
        );
        assert_eq!(
            (
                checked(fs::read(fixture.0.join("journal"))),
                checked(witness.current()),
                witness.swaps.load(Ordering::SeqCst),
            ),
            (original_bytes.clone(), Some(acknowledged), original_swaps),
            "{name} drift must not repair history or publish a witness"
        );
    }

    let mut recovered = checked(NeuronRuntime::recover(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        acknowledged,
        witness.clone(),
    ));
    assert_eq!(
        (
            checked(recovered.current_anchor()),
            checked(witness.current()),
            witness.swaps.load(Ordering::SeqCst),
            checked(fs::read(fixture.0.join("journal"))),
            model.calls,
        ),
        (
            Some(latest),
            Some(latest),
            original_swaps + 1,
            valid_prefix,
            2
        )
    );
    checked(recovered.tick(&mut model, input(/*sequence*/ 3, latest.checkpoint_digest)));
    assert_eq!(model.calls, 3);
}

#[test]
fn legacy_subject_only_history_is_not_implicitly_adopted() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let tick = input(/*sequence*/ 1, Digest32::ZERO);
    let mut legacy = checked(SparseJournal::open(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
    ));
    let receipt = checked(legacy.commit(
        Digest32::ZERO,
        &SparseTick {
            scope_digest: scope().scope_digest,
            objective_digest: tick.objective_digest,
            ndu_digest: tick.ndu_snapshot_digest,
            body_digest: body_digest(&config, &tick),
            input_digest: checked(tick.semantic_digest()),
            sequence: tick.logical_sequence,
            monotonic_micros: tick.monotonic_time_micros,
            drive_q24: vec![Q, Q / 2, 0, 0, 0],
            prediction_q24: vec![0; native.width],
        },
    ));
    let anchor = JournalAnchor {
        sequence: 1,
        checkpoint_digest: receipt.checkpoint_after,
    };
    drop(legacy);
    let bytes = checked(fs::read(fixture.0.join("journal")));
    let mut witness = CountingWitness::default();
    checked(witness.compare_and_swap(/*expected*/ None, anchor));
    assert_eq!(
        NeuronRuntime::recover(
            fixture.file(),
            native,
            scope(),
            /*max_records*/ 4,
            config,
            anchor,
            witness.clone(),
        )
        .err(),
        Some(NeuronRuntimeError::Journal(JournalError::ContextMismatch))
    );
    assert_eq!(
        (
            checked(fs::read(fixture.0.join("journal"))),
            checked(witness.current()),
            witness.swaps.load(Ordering::SeqCst),
        ),
        (bytes, Some(anchor), 1)
    );
}

#[test]
fn chain_recovery_checks_configuration_before_composing_segments() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = CountingWitness::default();
    let mut model = FakeModel::new();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 1,
        config.clone(),
        witness.clone(),
    ));
    let first = checked(runtime.tick(&mut model, input(/*sequence*/ 1, Digest32::ZERO)));
    checked(runtime.rollover(fixture.named_file("successor"), /*max_records*/ 1));
    checked(runtime.tick(
        &mut model,
        input(/*sequence*/ 2, first.tick.checkpoint_after),
    ));
    let latest = checked(runtime.current_anchor()).expect("last segment anchor");
    drop(runtime);
    let original_swaps = witness.swaps.load(Ordering::SeqCst);
    let mut changed = config.clone();
    changed.weights_digest = Digest32::of_bytes(b"other-weights");
    assert_eq!(
        NeuronRuntime::recover_chain_root(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 1,
            changed,
            witness.clone(),
        )
        .err(),
        Some(NeuronRuntimeError::Journal(JournalError::ContextMismatch))
    );
    assert_eq!(witness.swaps.load(Ordering::SeqCst), original_swaps);
    let mut recovered = checked(NeuronRuntime::recover_chain_root(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 1,
        config.clone(),
        witness,
    ));
    checked(recovered.recover_next_segment(fixture.named_file("successor"), /*max_records*/ 1));
    assert_eq!(checked(recovered.current_anchor()), Some(latest));
    checked(recovered.rollover(fixture.named_file("third"), /*max_records*/ 1));
    let third =
        checked(recovered.tick(&mut model, input(/*sequence*/ 3, latest.checkpoint_digest)));
    let canonical = checked(recovered.canonical_checkpoint(&third.tick, /*expires_unix_ms*/ 1000));
    assert_eq!(
        (
            canonical.encoder_digest,
            canonical.logical_sequence,
            model.calls
        ),
        (config.encoder_digest, 3, 3)
    );
}

#[test]
fn chain_recovery_does_not_initialize_missing_history_in_either_branch() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut witness = CountingWitness::default();
    let anchor = JournalAnchor {
        sequence: 2,
        checkpoint_digest: Digest32::of_bytes(b"independently-acknowledged-history"),
    };
    checked(witness.compare_and_swap(/*expected*/ None, anchor));
    for max_records in [1, 4] {
        assert_eq!(
            NeuronRuntime::recover_chain_root(
                fixture.file(),
                native.clone(),
                scope(),
                max_records,
                config.clone(),
                witness.clone(),
            )
            .err(),
            Some(NeuronRuntimeError::Journal(
                JournalError::AcknowledgedHistoryMissing
            ))
        );
        assert_eq!(
            (
                checked(fs::read(fixture.0.join("journal"))),
                checked(witness.current()),
                witness.swaps.load(Ordering::SeqCst),
            ),
            (Vec::<u8>::new(), Some(anchor), 1)
        );
    }
}

#[test]
fn subject_or_objective_drift_is_rejected_before_model_dispatch() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = CountingWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    let original_bytes = checked(fs::read(fixture.0.join("journal")));
    let mut wrong_subject = input(/*sequence*/ 1, Digest32::ZERO);
    wrong_subject.subject_id = checked(StableId::new("different.subject"));
    let mut wrong_objective = input(/*sequence*/ 1, Digest32::ZERO);
    wrong_objective.objective_digest = Digest32::of_bytes(b"different-objective");
    let mut model = FakeModel::new();
    for input in [wrong_subject, wrong_objective] {
        assert_eq!(
            runtime.tick(&mut model, input).err(),
            Some(NeuronRuntimeError::Journal(JournalError::ContextMismatch))
        );
    }
    assert_eq!(
        (
            model.calls,
            checked(runtime.current_anchor()),
            checked(witness.current()),
            witness.swaps.load(Ordering::SeqCst),
            checked(fs::read(fixture.0.join("journal"))),
        ),
        (0, None, None, 0, original_bytes)
    );
}

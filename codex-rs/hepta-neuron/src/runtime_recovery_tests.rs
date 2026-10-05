use super::*;
use pretty_assertions::assert_eq;

fn pending_first_tick(
    fixture: &Fixture,
    native: &SparseConfig,
    config: &NeuronRuntimeConfigV1,
) -> (MemoryWitness, JournalAnchor, usize) {
    let witness = MemoryWitness::for_config(config);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
        config.clone(),
        witness.clone(),
    ));
    let header_size = checked(fs::metadata(fixture.0.join("journal"))).len() as usize;
    witness.fail_next_compare_and_swap();
    let mut model = FakeModel::new();
    let result = runtime.tick(&mut model, input(1, Digest32::ZERO));
    let anchor = checked(runtime.current_anchor()).expect("committed first tick");
    assert_eq!(
        result,
        Err(NeuronRuntimeError::WitnessAfterCommit {
            anchor,
            error: WitnessStoreError::Unavailable,
        })
    );
    assert_eq!(model.calls, 1);
    assert_eq!(witness.current(), Ok(None));
    // Discard volatile pending state, as a process exit before witness publication does.
    drop(runtime);
    (witness, anchor, header_size)
}

#[test]
fn enrolled_header_only_root_reopens_with_its_durable_empty_witness() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let config_digest = checked(config.semantic_digest());
    let witness = checked(crate::FileAnchorWitnessStore::open_bound(
        fixture.named_file("witness"),
        scope(),
        native.generation,
        /*max_records*/ 4,
        config_digest,
    ));
    drop(checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
        config.clone(),
        witness,
    )));
    let original = checked(fs::read(fixture.0.join("journal")));
    let witness = checked(crate::FileAnchorWitnessStore::open_bound(
        fixture.named_file("witness"),
        scope(),
        native.generation,
        /*max_records*/ 4,
        config_digest,
    ));
    let recovered = checked(NeuronRuntime::recover_unacknowledged(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness,
    ));
    assert_eq!(recovered.current_anchor(), Ok(None));
    assert_eq!(recovered.current_eligibility_sample(), Ok(None));
    drop(recovered);
    assert_eq!(checked(fs::read(fixture.0.join("journal"))), original);
}

#[test]
fn first_committed_tick_reconciles_after_losing_volatile_pending_state() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let (witness, anchor, _) = pending_first_tick(&fixture, &native, &config);
    let original = checked(fs::read(fixture.0.join("journal")));
    let mut recovered = checked(NeuronRuntime::recover_unacknowledged(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    assert_eq!(recovered.current_anchor(), Ok(Some(anchor)));
    assert_eq!(witness.current(), Ok(Some(anchor)));
    let mut model = FakeModel::new();
    checked(recovered.tick(&mut model, input(2, anchor.checkpoint_digest)));
    assert_eq!(model.calls, 1);
    drop(recovered);
    assert!(checked(fs::read(fixture.0.join("journal"))).starts_with(&original));
}

#[test]
fn unacknowledged_recovery_cannot_adopt_multiple_complete_ticks() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let (witness, first, _) = pending_first_tick(&fixture, &native, &config);
    let second = input(2, first.checkpoint_digest);
    let mut journal = checked(SparseJournal::open(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
    ));
    // The low-level mechanism can build this history; a canonical owner stops
    // after its first tick until the independently enrolled witness acknowledges.
    checked(journal.commit(
        first.checkpoint_digest,
        &SparseTick {
            scope_digest: scope().scope_digest,
            objective_digest: second.objective_digest,
            ndu_digest: second.ndu_snapshot_digest,
            body_digest: body_digest(&config, &second),
            input_digest: checked(second.semantic_digest()),
            sequence: second.logical_sequence,
            monotonic_micros: second.monotonic_time_micros,
            drive_q24: vec![Q, Q / 2, 0, 0, 0],
            prediction_q24: vec![0; native.width],
        },
    ));
    drop(journal);
    let original = checked(fs::read(fixture.0.join("journal")));
    for bytes in [original.clone(), {
        let mut partial_third = original;
        partial_third.extend_from_slice(b"partial third frame");
        partial_third
    }] {
        checked(fs::write(fixture.0.join("journal"), &bytes));
        assert_eq!(
            NeuronRuntime::recover_unacknowledged(
                fixture.file(),
                native.clone(),
                scope(),
                /*max_records*/ 4,
                config.clone(),
                witness.clone(),
            )
            .err(),
            Some(NeuronRuntimeError::Journal(JournalError::Corrupt))
        );
        assert_eq!(witness.current(), Ok(None));
        assert_eq!(checked(fs::read(fixture.0.join("journal"))), bytes);
    }
}

#[test]
fn unacknowledged_recovery_rejects_a_partial_second_frame_without_repair() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let (witness, _, _) = pending_first_tick(&fixture, &native, &config);
    let path = fixture.0.join("journal");
    let mut bytes = checked(fs::read(&path));
    bytes.extend_from_slice(b"partial second frame");
    checked(fs::write(&path, &bytes));
    assert_eq!(
        NeuronRuntime::recover_unacknowledged(
            fixture.file(),
            native,
            scope(),
            /*max_records*/ 4,
            config,
            witness.clone(),
        )
        .err(),
        Some(NeuronRuntimeError::Journal(JournalError::Corrupt))
    );
    assert_eq!(witness.current(), Ok(None));
    assert_eq!(checked(fs::read(&path)), bytes);
}

#[test]
fn unacknowledged_first_partial_frame_recovers_only_the_enrolled_header() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let (witness, _, header_size) = pending_first_tick(&fixture, &native, &config);
    let path = fixture.0.join("journal");
    let full = checked(fs::read(&path));
    let frame_size = full.len() - header_size;
    for tail in [1, frame_size / 2, frame_size - 1] {
        checked(fs::write(&path, &full[..header_size + tail]));
        let recovered = checked(NeuronRuntime::recover_unacknowledged(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 4,
            config.clone(),
            witness.clone(),
        ));
        assert_eq!(recovered.current_anchor(), Ok(None));
        assert_eq!(witness.current(), Ok(None));
        drop(recovered);
        assert_eq!(checked(fs::read(&path)), full[..header_size]);
    }
}

#[test]
fn unacknowledged_recovery_context_drift_rejects_before_tail_repair() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let (witness, _, header_size) = pending_first_tick(&fixture, &native, &config);
    let path = fixture.0.join("journal");
    let full = checked(fs::read(&path));
    let original = full[..header_size + (full.len() - header_size) / 2].to_vec();
    checked(fs::write(&path, &original));
    let mut other_config = config.clone();
    other_config.encoder_digest = Digest32::of_bytes(b"another encoder");
    let mut other_scope = scope();
    other_scope.scope_digest = Digest32::of_bytes(b"another subject");
    let mut other_native = native.clone();
    other_native.generation = checked(Generation::new(/*value*/ 2));
    for (native, scope, config, error) in [
        (
            native.clone(),
            scope(),
            other_config,
            NeuronRuntimeError::RecoveryWitnessMismatch,
        ),
        (
            native,
            other_scope,
            config,
            NeuronRuntimeError::Witness(WitnessStoreError::ContextMismatch),
        ),
        (
            other_native.clone(),
            scope(),
            runtime_config(&other_native),
            NeuronRuntimeError::Witness(WitnessStoreError::ContextMismatch),
        ),
    ] {
        assert_eq!(
            NeuronRuntime::recover_unacknowledged(
                fixture.file(),
                native,
                scope,
                /*max_records*/ 4,
                config,
                witness.clone(),
            )
            .err(),
            Some(error)
        );
        assert_eq!(checked(fs::read(&path)), original);
        assert_eq!(witness.current(), Ok(None));
    }
}

#[test]
fn acknowledged_witness_cannot_reenter_unacknowledged_recovery() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::for_config(&config);
    let anchor = {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 4,
            config.clone(),
            witness.clone(),
        ));
        checked(runtime.tick(&mut FakeModel::new(), input(1, Digest32::ZERO)));
        checked(runtime.current_anchor()).expect("acknowledged first tick")
    };
    let path = fixture.0.join("journal");
    let mut original = checked(fs::read(&path));
    original.extend_from_slice(b"partial next frame");
    checked(fs::write(&path, &original));
    assert_eq!(
        NeuronRuntime::recover_unacknowledged(
            fixture.file(),
            native,
            scope(),
            /*max_records*/ 4,
            config,
            witness.clone(),
        )
        .err(),
        Some(NeuronRuntimeError::RecoveryWitnessMismatch)
    );
    assert_eq!(checked(fs::read(&path)), original);
    assert_eq!(witness.current(), Ok(Some(anchor)));
}

fn acknowledged_three_segment_chain(
    fixture: &Fixture,
    native: &SparseConfig,
    config: &NeuronRuntimeConfigV1,
) -> MemoryWitness {
    let witness = MemoryWitness::for_config(config);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 2,
        config.clone(),
        witness.clone(),
    ));
    let mut predecessor = Digest32::ZERO;
    for sequence in 1..=5 {
        if sequence == 3 {
            checked(runtime.rollover(fixture.named_file("successor"), /*max_records*/ 2));
        } else if sequence == 5 {
            checked(runtime.rollover(fixture.named_file("last"), /*max_records*/ 2));
        }
        let output = checked(runtime.tick(&mut FakeModel::new(), input(sequence, predecessor)));
        predecessor = output.tick.checkpoint_after;
    }
    witness
}

#[test]
fn unacknowledged_recovery_rejects_empty_files_and_successor_segments() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    acknowledged_three_segment_chain(&fixture, &native, &config);
    for name in ["missing", "successor"] {
        let file = fixture.named_file(name);
        let path = fixture.0.join(name);
        let original = checked(fs::read(&path));
        assert_eq!(
            NeuronRuntime::recover_unacknowledged(
                file,
                native.clone(),
                scope(),
                /*max_records*/ 4,
                config.clone(),
                MemoryWitness::for_config(&config),
            )
            .err(),
            Some(NeuronRuntimeError::Journal(JournalError::Corrupt))
        );
        assert_eq!(checked(fs::read(&path)), original);
    }
}

#[test]
fn acknowledged_chain_root_damage_is_rejected_without_initialization_or_tail_repair() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = acknowledged_three_segment_chain(&fixture, &native, &config);
    let anchor = checked(witness.current());
    let path = fixture.0.join("journal");
    let full = checked(fs::read(&path));
    let frame_size = 304 + 16 * native.width;
    for damaged in [
        Vec::new(),
        full[..full.len() - 1].to_vec(),
        full[..full.len() - frame_size / 2].to_vec(),
        {
            let mut extra = full.clone();
            extra.extend_from_slice(b"partial excess frame");
            extra
        },
    ] {
        checked(fs::write(&path, &damaged));
        assert_eq!(
            NeuronRuntime::recover_chain_root(
                fixture.file(),
                native.clone(),
                scope(),
                /*max_records*/ 2,
                config.clone(),
                witness.clone(),
            )
            .err(),
            Some(NeuronRuntimeError::Journal(
                JournalError::AcknowledgedHistoryMissing,
            ))
        );
        assert_eq!(checked(fs::read(&path)), damaged);
        assert_eq!(witness.current(), Ok(anchor));
    }
}

#[test]
fn acknowledged_intermediate_segment_damage_is_rejected_without_tail_repair() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = acknowledged_three_segment_chain(&fixture, &native, &config);
    let anchor = checked(witness.current());
    let path = fixture.0.join("successor");
    let full = checked(fs::read(&path));
    let frame_size = 304 + 16 * native.width;
    for damaged in [
        Vec::new(),
        full[..full.len() - 1].to_vec(),
        full[..full.len() - frame_size / 2].to_vec(),
        {
            let mut extra = full.clone();
            extra.extend_from_slice(b"partial excess frame");
            extra
        },
    ] {
        checked(fs::write(&path, &damaged));
        let mut recovered = checked(NeuronRuntime::recover_chain_root(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 2,
            config.clone(),
            witness.clone(),
        ));
        let root_anchor = checked(recovered.current_anchor());
        assert_eq!(
            recovered.recover_next_segment(fixture.named_file("successor"), /*max_records*/ 2),
            Err(NeuronRuntimeError::Journal(
                JournalError::AcknowledgedHistoryMissing,
            ))
        );
        assert_eq!(checked(fs::read(&path)), damaged);
        assert_eq!(recovered.current_anchor(), Ok(root_anchor));
        assert_eq!(witness.current(), Ok(anchor));
    }
}

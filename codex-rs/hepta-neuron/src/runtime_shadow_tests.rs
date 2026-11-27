use super::*;
use pretty_assertions::assert_eq;

#[test]
fn shadow_advances_actual_journal_and_recovers_without_calibrated_publication() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = NeuronShadowConfigV1::from(&runtime_config(&native));
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
        config.clone(),
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    assert_eq!(
        runtime.tick(&mut model, input(1, Digest32::ZERO)).err(),
        Some(NeuronRuntimeError::InvalidCalibration)
    );
    assert_eq!(model.calls, 0);
    let first = checked(runtime.tick_shadow(&mut model, input(1, Digest32::ZERO)));
    assert!(first.abstain);
    assert!(!first.authority.grants_any());
    assert_eq!(
        first.input_digest,
        checked(input(1, Digest32::ZERO).semantic_digest())
    );
    assert_eq!(model.calls, 1);
    let anchor = checked(runtime.current_anchor()).expect("committed shadow anchor");
    assert_eq!(checked(witness.current()), Some(anchor));
    drop(runtime);
    let mut recovered = checked(NeuronRuntime::recover_shadow(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        anchor,
        witness,
    ));
    let second = checked(recovered.tick_shadow(&mut model, input(2, anchor.checkpoint_digest)));
    assert_eq!(second.checkpoint_before, first.checkpoint_after);
    assert_eq!(model.calls, 2);
    assert!(second.abstain);
}

#[test]
fn shadow_witness_reconciliation_keeps_one_model_call_and_rejects_another_tick() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = NeuronShadowConfigV1::from(&runtime_config(&native));
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    witness.fail_next_compare_and_swap();
    let mut model = FakeModel::new();
    let tick = input(1, Digest32::ZERO);
    assert!(matches!(
        runtime.tick_shadow(&mut model, tick.clone()),
        Err(NeuronRuntimeError::WitnessAfterCommit { .. })
    ));
    let mut changed = tick.clone();
    changed.ndu_snapshot_digest = Digest32::of_bytes(b"other live NDU snapshot");
    assert_eq!(
        runtime.tick_shadow(&mut model, changed).err(),
        Some(NeuronRuntimeError::PendingReconciliation)
    );
    let output = checked(runtime.tick_shadow(&mut model, tick));
    assert_eq!(model.calls, 1);
    assert_eq!(
        checked(witness.current()),
        checked(runtime.current_anchor())
    );
    assert!(output.abstain);
}

#[test]
fn shadow_identity_failure_does_not_commit_and_calibrated_profile_cannot_enter_shadow() {
    let fixture = Fixture::new();
    let native = native_config();
    let calibrated = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
        NeuronShadowConfigV1::from(&calibrated),
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    model.corrupt_head = true;
    assert_eq!(
        runtime
            .tick_shadow(&mut model, input(1, Digest32::ZERO))
            .err(),
        Some(NeuronRuntimeError::ModelBindingMismatch)
    );
    assert_eq!(checked(runtime.current_anchor()), None);
    drop(runtime);
    let mut calibrated = checked(NeuronRuntime::bootstrap(
        fixture.named_file("calibrated"),
        native,
        scope(),
        /*max_records*/ 4,
        calibrated,
        MemoryWitness::default(),
    ));
    assert_eq!(
        calibrated
            .tick_shadow(&mut model, input(1, Digest32::ZERO))
            .err(),
        Some(NeuronRuntimeError::InvalidConfig)
    );
    assert_eq!(model.calls, 1);
}

#[test]
fn shadow_rejects_foreign_initial_owner_context_before_model() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = NeuronShadowConfigV1::from(&runtime_config(&native));
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let mut wrong_subject = input(1, Digest32::ZERO);
    wrong_subject.subject_id = checked(StableId::new("subject.foreign"));
    let mut wrong_objective = input(1, Digest32::ZERO);
    wrong_objective.objective_digest = Digest32::of_bytes(b"foreign-objective");
    for request in [wrong_subject, wrong_objective] {
        assert_eq!(
            runtime.tick_shadow(&mut model, request).err(),
            Some(NeuronRuntimeError::Journal(JournalError::ContextMismatch))
        );
        assert_eq!(model.calls, 0, "foreign shadow context invoked the model");
        assert_eq!(checked(runtime.current_anchor()), None);
        assert_eq!(checked(witness.current()), None);
    }
    checked(runtime.tick_shadow(&mut model, input(1, Digest32::ZERO)));
    assert_eq!(
        model.calls, 1,
        "rejected context must leave valid work available"
    );
}

#[test]
fn shadow_rejects_invalid_successor_sequence_clock_and_body_before_model() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = NeuronShadowConfigV1::from(&runtime_config(&native));
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick_shadow(&mut model, input(1, Digest32::ZERO)));
    let predecessor = first.checkpoint_after;
    let anchor = checked(runtime.current_anchor());
    let mut stale_clock = input(2, predecessor);
    stale_clock.monotonic_time_micros = 1_000;
    let mut wrong_body = input(2, predecessor);
    wrong_body.body_generation = Some(2);
    for (request, expected) in [
        (input(3, predecessor), SparseError::Sequence),
        (stale_clock, SparseError::Clock),
        (wrong_body, SparseError::ScopeDrift),
    ] {
        assert_eq!(
            runtime.tick_shadow(&mut model, request).err(),
            Some(NeuronRuntimeError::Journal(JournalError::Mechanism(
                expected
            )))
        );
        assert_eq!(model.calls, 1, "invalid shadow successor invoked the model");
        assert_eq!(checked(runtime.current_anchor()), anchor);
        assert_eq!(checked(witness.current()), anchor);
    }
    let second = checked(runtime.tick_shadow(&mut model, input(2, predecessor)));
    assert_eq!(second.checkpoint_before, predecessor);
    assert_eq!(model.calls, 2);
}

#[test]
fn full_shadow_journal_rejects_before_another_model_call() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = NeuronShadowConfigV1::from(&runtime_config(&native));
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 1,
        config,
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick_shadow(&mut model, input(1, Digest32::ZERO)));
    let anchor = checked(runtime.current_anchor());
    assert_eq!(
        runtime
            .tick_shadow(&mut model, input(2, first.checkpoint_after))
            .err(),
        Some(NeuronRuntimeError::Journal(JournalError::Capacity))
    );
    assert_eq!(model.calls, 1, "full shadow journal invoked the model");
    assert_eq!(checked(runtime.current_anchor()), anchor);
    assert_eq!(checked(witness.current()), anchor);
}

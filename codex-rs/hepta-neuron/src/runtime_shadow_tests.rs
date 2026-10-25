use super::*;
use pretty_assertions::assert_eq;

#[test]
fn shadow_advances_actual_journal_and_recovers_without_calibrated_publication() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = NeuronShadowConfigV1::from(&runtime_config(&native));
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(), native.clone(), scope(), /*max_records*/ 4,
        config.clone(), witness.clone(),
    ));
    let mut model = FakeModel::new();
    assert_eq!(runtime.tick(&mut model, input(1, Digest32::ZERO)).err(),
        Some(NeuronRuntimeError::InvalidCalibration));
    assert_eq!(model.calls, 0);
    let first = checked(runtime.tick_shadow(&mut model, input(1, Digest32::ZERO)));
    assert!(first.abstain);
    assert!(!first.authority.grants_any());
    assert_eq!(first.input_digest, checked(input(1, Digest32::ZERO).semantic_digest()));
    assert_eq!(model.calls, 1);
    let anchor = checked(runtime.current_anchor()).expect("committed shadow anchor");
    assert_eq!(checked(witness.current()), Some(anchor));
    drop(runtime);
    let mut recovered = checked(NeuronRuntime::recover_shadow(
        fixture.file(), native, scope(), /*max_records*/ 4, config, anchor, witness,
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
        fixture.file(), native, scope(), /*max_records*/ 4, config, witness.clone(),
    ));
    witness.fail_next_compare_and_swap();
    let mut model = FakeModel::new();
    let tick = input(1, Digest32::ZERO);
    assert!(matches!(runtime.tick_shadow(&mut model, tick.clone()),
        Err(NeuronRuntimeError::WitnessAfterCommit { .. })));
    let mut changed = tick.clone();
    changed.ndu_snapshot_digest = Digest32::of_bytes(b"other live NDU snapshot");
    assert_eq!(runtime.tick_shadow(&mut model, changed).err(),
        Some(NeuronRuntimeError::PendingReconciliation));
    let output = checked(runtime.tick_shadow(&mut model, tick));
    assert_eq!(model.calls, 1);
    assert_eq!(checked(witness.current()), checked(runtime.current_anchor()));
    assert!(output.abstain);
}

#[test]
fn shadow_identity_failure_does_not_commit_and_calibrated_profile_cannot_enter_shadow() {
    let fixture = Fixture::new();
    let native = native_config();
    let calibrated = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap_shadow(
        fixture.file(), native.clone(), scope(), /*max_records*/ 4,
        NeuronShadowConfigV1::from(&calibrated), MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    model.corrupt_head = true;
    assert_eq!(runtime.tick_shadow(&mut model, input(1, Digest32::ZERO)).err(),
        Some(NeuronRuntimeError::ModelBindingMismatch));
    assert_eq!(checked(runtime.current_anchor()), None);
    drop(runtime);
    let mut calibrated = checked(NeuronRuntime::bootstrap(
        fixture.named_file("calibrated"), native, scope(), /*max_records*/ 4,
        calibrated, MemoryWitness::default(),
    ));
    assert_eq!(calibrated.tick_shadow(&mut model, input(1, Digest32::ZERO)).err(),
        Some(NeuronRuntimeError::InvalidConfig));
    assert_eq!(model.calls, 1);
}

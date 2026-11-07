// Append to codex-rs/hepta-neuron/src/runtime_tests.rs
// Target baseline: 78fdb0cf8537e3a84fc6e0a849707559c80881e8

#[test]
fn recovery_rejects_external_witness_mismatch() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        16,
        config.clone(),
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let output = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    let real_anchor = checked(runtime.current_anchor()).expect("anchor");
    assert_eq!(output.tick.checkpoint_after, real_anchor.checkpoint_digest);
    drop(runtime);

    let wrong_anchor = JournalAnchor {
        sequence: real_anchor.sequence,
        checkpoint_digest: Digest32::of_bytes(b"wrong-external-anchor"),
    };
    assert!(matches!(
        NeuronRuntime::recover(
            fixture.file(),
            native,
            scope(),
            16,
            config,
            wrong_anchor,
            witness.clone(),
        ),
        Err(NeuronRuntimeError::RecoveryWitnessMismatch)
    ));
    assert_eq!(checked(witness.current()), Some(real_anchor));
}

#[test]
fn corrupted_feature_digest_rejects_before_model_execution() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        16,
        config,
        witness.clone(),
    ));
    let mut request = input(1, Digest32::ZERO);
    request.input_feature_digest = Digest32::of_bytes(b"tampered-feature-vector");
    let mut model = FakeModel::new();

    assert_eq!(
        runtime.tick(&mut model, request).err(),
        Some(NeuronRuntimeError::FeatureDigestMismatch)
    );
    assert_eq!(model.calls, 0);
    assert_eq!(checked(runtime.current_anchor()), None);
    assert_eq!(checked(witness.current()), None);
}

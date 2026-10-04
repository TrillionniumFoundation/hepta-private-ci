use super::*;
use pretty_assertions::assert_eq;

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

#[test]
fn complete_current_checkpoint_is_acknowledged_readonly_and_survives_cold_reopen() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    let absent = JournalAnchor {
        sequence: 1,
        checkpoint_digest: digest("not present"),
    };
    assert_eq!(
        checked(runtime.current_acknowledged_sparse_checkpoint_v2(absent)),
        None
    );
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(calls.clone());
    let first = checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    let second = checked(runtime.tick_guarded(
        &mut model,
        input(2, first.next_anchor.checkpoint_digest),
        &mut Allow,
    ));
    let before = (
        runtime.store.held_fixture_bytes(),
        runtime.index.held_fixture_bytes(),
    );
    let actual = checked(runtime.current_acknowledged_sparse_checkpoint_v2(first.next_anchor))
        .expect("real current checkpoint");
    assert_eq!(
        actual,
        runtime
            .checkpoint
            .clone()
            .expect("same original owner state")
    );
    assert_eq!(actual.digest(), second.next_anchor.checkpoint_digest);
    assert!(matches!(
        runtime.current_acknowledged_sparse_checkpoint_v2(absent),
        Err(NeuronRuntimeV2Error::RecoveryMismatch)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        (
            runtime.store.held_fixture_bytes(),
            runtime.index.held_fixture_bytes()
        ),
        before
    );
    drop(runtime);
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store, index) = contexts(&native, &config, &body);
    let recovered = checked(NeuronRuntimeV2::recover(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store,
        index,
        witness,
    ));
    assert_eq!(
        checked(recovered.current_acknowledged_sparse_checkpoint_v2(first.next_anchor)),
        Some(actual)
    );
}

#[test]
fn current_checkpoint_read_rejects_pending_and_foreign_witness_without_reconcile() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    let mut model = FakeDurableModel::new(Arc::new(AtomicUsize::new(0)));
    let first = checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    let request = input(2, first.next_anchor.checkpoint_digest);
    checked(runtime.index.prepare(
        NeuronOperationKeyV2 {
            tick_id: request.tick_id.clone(),
            input_semantic_digest: checked(request.semantic_digest()),
        },
        Some(first.next_anchor),
    ));
    let before = runtime.index.held_fixture_bytes();
    assert!(matches!(
        runtime.current_acknowledged_sparse_checkpoint_v2(first.next_anchor),
        Err(NeuronRuntimeV2Error::PendingOperation)
    ));
    assert_eq!(runtime.index.held_fixture_bytes(), before);
    *checked(witness.current.lock()) = None;
    assert!(
        runtime
            .current_acknowledged_sparse_checkpoint_v2(first.next_anchor)
            .is_err()
    );
    assert_eq!(runtime.index.held_fixture_bytes(), before);
}

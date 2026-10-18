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
fn tick_anchor_reads_exact_acknowledged_head_and_survives_cold_reopen() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    assert_eq!(checked(runtime.current_tick_anchor()), None);
    let mut model = FakeDurableModel::new(Arc::new(AtomicUsize::new(0)));
    let committed = checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    let anchor = Some(committed.next_anchor);
    assert_eq!(checked(runtime.current_tick_anchor()), anchor);
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
    assert_eq!(checked(recovered.current_tick_anchor()), anchor);
}

#[test]
fn tick_anchor_refuses_pending_index_without_reconciling_or_writing() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture, MemoryWitness::default());
    let request = input(1, Digest32::ZERO);
    let input_semantic_digest = checked(request.semantic_digest());
    checked(runtime.index.prepare(
        NeuronOperationKeyV2 {
            tick_id: request.tick_id,
            input_semantic_digest,
        },
        /*expected_anchor*/ None,
    ));
    let before = runtime.index.held_fixture_bytes();
    assert!(matches!(
        runtime.current_tick_anchor(),
        Err(NeuronRuntimeV2Error::PendingOperation)
    ));
    assert_eq!(runtime.index.held_fixture_bytes(), before);
    assert_eq!(checked(runtime.store.current_anchor()), None);
}

#[test]
fn tick_anchor_refuses_witness_divergence_even_with_matching_local_head() {
    let fixture = Fixture::new();
    let witness = MemoryWitness::default();
    let mut runtime = bootstrap(&fixture, witness.clone());
    let mut model = FakeDurableModel::new(Arc::new(AtomicUsize::new(0)));
    checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    *checked(witness.current.lock()) = None;
    assert!(matches!(
        runtime.current_tick_anchor(),
        Err(NeuronRuntimeV2Error::RecoveryMismatch)
    ));
}

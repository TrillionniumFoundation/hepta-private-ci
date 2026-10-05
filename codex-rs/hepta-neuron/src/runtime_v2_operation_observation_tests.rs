//! Uses the original runtime, generation/index files and full commit codec.
use super::*;

#[test]
fn whole_export_reads_the_same_acknowledged_operation_without_model_effects() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native.clone(),
        scope(),
        config.clone(),
        body.clone(),
        store_context.clone(),
        index_context.clone(),
        witness.clone(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    let request = input(1, Digest32::ZERO);
    let input_digest = checked(request.semantic_digest());
    assert!(
        runtime
            .export_acknowledged_operation_v2(&request.tick_id, input_digest)
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let commit = checked(runtime.tick_guarded(&mut model, request.clone(), &mut Allow));
    let before_store = runtime.store.held_fixture_bytes();
    let before_index = runtime.index.held_fixture_bytes();
    let observed =
        checked(runtime.export_acknowledged_operation_v2(&request.tick_id, input_digest));
    assert_eq!(observed.commit(), &commit);
    assert_eq!(observed.scope(), scope());
    assert_eq!(observed.generation(), 1);
    assert!(observed.record().witness_acknowledged);
    assert_eq!(observed.current_witness(), commit.next_anchor);
    assert_eq!(runtime.store.held_fixture_bytes(), before_store);
    assert_eq!(runtime.index.held_fixture_bytes(), before_index);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let bytes = observed.bytes().to_vec();
    let pin = Digest32::of_bytes(&bytes);
    assert_eq!(
        checked(NeuronAcknowledgedOperationV2::from_bytes(
            bytes.clone(),
            pin
        ))
        .commit(),
        &commit
    );
    assert!(
        NeuronAcknowledgedOperationV2::from_bytes(
            bytes.clone(),
            digest("foreign protected source")
        )
        .is_err()
    );
    let mut changed = bytes.clone();
    changed[16] ^= 1;
    let repinned = Digest32::of_bytes(&changed);
    assert!(NeuronAcknowledgedOperationV2::from_bytes(changed, repinned).is_err());
    assert!(
        runtime
            .export_acknowledged_operation_v2(&request.tick_id, digest("foreign input"))
            .is_err()
    );
    drop(runtime);
    let mut recovered = checked(NeuronRuntimeV2::recover(
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
    assert_eq!(
        checked(recovered.export_acknowledged_operation_v2(&request.tick_id, input_digest)).bytes(),
        bytes
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

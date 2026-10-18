use super::closure::RejectedModel;
use super::closure::UnknownModel;
use super::*;

#[test]
fn immutable_archive_keeps_full_receipts_and_failure_tombstones_without_model_reexecution() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store, index) = contexts(&native, &config, &body);
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store,
        index,
        MemoryWitness::default(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    let request = input(1, Digest32::ZERO);
    let commit = checked(runtime.tick_guarded(&mut model, request.clone(), &mut Allow));
    let failed = input(2, commit.next_anchor.checkpoint_digest);
    assert!(
        runtime
            .tick_guarded(&mut RejectedModel, failed.clone(), &mut Allow)
            .is_err()
    );
    let archive =
        checked(runtime.export_generation_archive(MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1));
    assert_eq!(archive.operation_count(), 2);
    assert_eq!(
        checked(archive.query_operation(&request.tick_id, checked(request.semantic_digest()))),
        NeuronOperationStatusV2::Committed {
            commit: Box::new(commit),
            witness_acknowledged: true
        }
    );
    assert_eq!(
        checked(archive.query_operation(&failed.tick_id, checked(failed.semantic_digest()))),
        NeuronOperationStatusV2::Failed(crate::NeuronOperationFailureV2::ModelRejected)
    );
    assert!(
        archive
            .query_operation(&request.tick_id, digest("changed-input"))
            .is_err()
    );
    let reopened = checked(NeuronGenerationArchiveV1::from_bytes(
        archive.bytes().to_vec(),
        archive.digest(),
    ));
    assert_eq!(
        checked(reopened.query_operation(&failed.tick_id, checked(failed.semantic_digest()))),
        NeuronOperationStatusV2::Failed(crate::NeuronOperationFailureV2::ModelRejected)
    );
    let mut changed = archive.bytes().to_vec();
    changed[40] ^= 1;
    assert!(NeuronGenerationArchiveV1::from_bytes(changed, archive.digest()).is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn unknown_work_cannot_be_archived_or_freed() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store, index) = contexts(&native, &config, &body);
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store,
        index,
        MemoryWitness::default(),
    ));
    let mut unknown = UnknownModel {
        executions: 0,
        queries: 0,
    };
    assert!(
        runtime
            .tick_guarded(&mut unknown, input(1, Digest32::ZERO), &mut Allow)
            .is_err()
    );
    assert!(matches!(
        runtime.export_generation_archive(MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1),
        Err(NeuronRuntimeV2Error::PendingOperation)
    ));
    assert_eq!(unknown.executions, 1);
}

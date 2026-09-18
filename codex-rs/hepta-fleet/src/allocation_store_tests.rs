use super::*;

#[test]
fn store_reopens_exact_committed_generation() {
    let temp = tempfile::tempdir().expect("temp");
    let state_root = temp.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let mut store =
        FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
    assert_eq!(store.current().revision, 1);
    let expected = store.current().state_digest.clone();
    let revision = store.current().revision;
    store
        .commit(revision, 7, 200, LeaseLedger::new())
        .expect("commit");
    drop(store);

    let reopened =
        FleetAllocationStore::open_or_initialize(&state_root, 8, 300).expect("reopen");
    assert_eq!(reopened.current().revision, 2);
    assert_ne!(reopened.current().state_digest, expected);
    assert_eq!(reopened.current().writer_epoch, 7);
}

#[test]
fn stale_revision_cannot_overwrite_a_committed_generation() {
    let temp = tempfile::tempdir().expect("temp");
    let state_root = temp.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let mut store =
        FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
    store
        .commit(1, 7, 200, LeaseLedger::new())
        .expect("commit");
    assert!(matches!(
        store.commit(1, 7, 300, LeaseLedger::new()),
        Err(FleetAllocationStoreError::StaleRevision {
            expected: 1,
            current: 2
        })
    ));
}

#[test]
fn tampered_retained_predecessor_fails_reopen() {
    let temp = tempfile::tempdir().expect("temp");
    let state_root = temp.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let mut store =
        FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
    store
        .commit(1, 7, 200, LeaseLedger::new())
        .expect("revision two");
    store
        .commit(2, 7, 300, LeaseLedger::new())
        .expect("revision three");
    drop(store);

    let path = state_path(&state_root.join(STATE_DIRECTORY), 2);
    let mut predecessor: FleetAllocationStateV1 =
        serde_json::from_slice(&std::fs::read(&path).expect("read predecessor"))
            .expect("decode predecessor");
    predecessor.committed_at_ms += 1;
    std::fs::write(
        path,
        serde_json::to_vec(&predecessor).expect("encode tampered predecessor"),
    )
    .expect("tamper predecessor");

    assert!(FleetAllocationStore::open_or_initialize(&state_root, 9, 400).is_err());
}

#[test]
fn tampered_latest_generation_fails_reopen() {
    let temp = tempfile::tempdir().expect("temp");
    let state_root = temp.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let mut store =
        FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
    store
        .commit(1, 7, 200, LeaseLedger::new())
        .expect("commit");
    let path = state_path(&state_root.join(STATE_DIRECTORY), 2);
    let mut bytes = std::fs::read(&path).expect("read");
    let index = bytes
        .iter()
        .position(|byte| *byte == b'7')
        .expect("writer epoch byte");
    bytes[index] = b'8';
    std::fs::write(path, bytes).expect("tamper");
    assert!(FleetAllocationStore::open_or_initialize(&state_root, 9, 300).is_err());
}
#[test]
fn state_generation_retention_is_bounded() {
    let temp = tempfile::tempdir().expect("temp");
    let state_root = temp.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let mut store =
        FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
    for step in 0..64_u64 {
        let revision = store.current().revision;
        store
            .commit(revision, 7, 200 + step, LeaseLedger::new())
            .expect("commit");
    }
    let state_dir = state_root.join(STATE_DIRECTORY);
    let count = std::fs::read_dir(state_dir).expect("read state dir").count();
    assert_eq!(count, RETAIN_STATE_GENERATIONS);
}


//! Read the original witness without releasing its lock or repairing bytes.

use super::*;
use pretty_assertions::assert_eq;

fn original_bytes(store: &mut FileAnchorWitnessStore) -> (Vec<u8>, u64) {
    let file = checked(store.file.get_mut());
    let cursor = checked(file.stream_position());
    checked(file.seek(SeekFrom::Start(0)));
    let mut bytes = Vec::new();
    checked(file.read_to_end(&mut bytes));
    checked(file.seek(SeekFrom::Start(cursor)));
    (bytes, cursor)
}

fn replace_original(store: &mut FileAnchorWitnessStore, bytes: &[u8], cursor: u64) {
    let file = checked(store.file.get_mut());
    checked(file.seek(SeekFrom::Start(0)));
    checked(file.write_all(bytes));
    checked(file.set_len(bytes.len() as u64));
    checked(file.sync_all());
    checked(file.seek(SeekFrom::Start(cursor)));
}

#[test]
fn witness_current_physical_corruption_fences_reads_and_cas_after_restore() {
    for (offset, expected_error) in [
        (0, WitnessStoreError::ContextMismatch),
        (HEADER + RECORD - 1, WitnessStoreError::Corrupt),
    ] {
        let fixture = Fixture::new();
        let mut store = checked(FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        ));
        checked(store.compare_and_swap(None, anchor(1)));
        let (original, cursor) = original_bytes(&mut store);
        let mut corrupt = original.clone();
        corrupt[offset] ^= 1;
        replace_original(&mut store, &corrupt, cursor);
        assert_eq!(store.current(), Err(expected_error));
        assert_eq!(original_bytes(&mut store), (corrupt, cursor));
        replace_original(&mut store, &original, cursor);
        assert_eq!(store.current(), Err(WitnessStoreError::Poisoned));
        assert_eq!(
            store.compare_and_swap(Some(anchor(1)), anchor(2)),
            Err(WitnessStoreError::Poisoned)
        );
        assert_eq!(original_bytes(&mut store), (original.clone(), cursor));
        drop(store);
        let mut recovered = checked(FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        ));
        assert_eq!(checked(recovered.current()), Some(anchor(1)));
        assert_eq!(original_bytes(&mut recovered).0, original);
    }
}

#[test]
fn witness_current_rehashed_history_cannot_preserve_cached_frontier() {
    let fixture = Fixture::new();
    let mut store = checked(FileAnchorWitnessStore::open(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 8,
    ));
    checked(store.compare_and_swap(None, anchor(1)));
    checked(store.compare_and_swap(Some(anchor(1)), anchor(2)));
    let (original, cursor) = original_bytes(&mut store);
    let substituted = JournalAnchor {
        sequence: 1,
        checkpoint_digest: Digest32::of_bytes(b"changed valid earlier checkpoint"),
    };
    let mut changed = original.clone();
    changed[HEADER..HEADER + RECORD].copy_from_slice(&encode_record(None, substituted));
    changed[HEADER + RECORD..].copy_from_slice(&encode_record(Some(substituted), anchor(2)));
    replace_original(&mut store, &changed, cursor);
    // Both records remain valid, linked and the same length, with the same
    // final anchor. Only a comparison of the original full history detects it.
    assert_eq!(
        store.compare_and_swap(Some(anchor(2)), anchor(3)),
        Err(WitnessStoreError::Corrupt)
    );
    assert_eq!(original_bytes(&mut store), (changed, cursor));
    replace_original(&mut store, &original, cursor);
    assert_eq!(store.current(), Err(WitnessStoreError::Poisoned));
    assert_eq!(
        store.compare_and_swap(Some(anchor(2)), anchor(3)),
        Err(WitnessStoreError::Poisoned)
    );
    assert_eq!(original_bytes(&mut store), (original, cursor));
}

#[test]
fn witness_current_shared_reads_preserve_original_cursor_and_lock() {
    let fixture = Fixture::new();
    let mut store = checked(FileAnchorWitnessStore::open(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 8,
    ));
    checked(store.compare_and_swap(None, anchor(1)));
    checked(store.compare_and_swap(Some(anchor(1)), anchor(2)));
    checked(checked(store.file.get_mut()).seek(SeekFrom::Start(7)));
    let before = original_bytes(&mut store);
    std::thread::scope(|threads| {
        for _ in 0..4 {
            let original = &store;
            threads.spawn(move || {
                for _ in 0..16 {
                    assert_eq!(checked(original.current()), Some(anchor(2)));
                }
            });
        }
    });
    assert_eq!(original_bytes(&mut store), before);
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::Busy)
    );
    assert_eq!(
        store.compare_and_swap(Some(anchor(1)), anchor(2)),
        Err(WitnessStoreError::Conflict)
    );
    assert_eq!(original_bytes(&mut store), before);
}

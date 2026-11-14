use super::super::*;
use super::TempJournal;
use super::key;

use pretty_assertions::assert_eq;

fn locked_bytes(store: &mut LockedFileProductEvaluationExecutionStoreV1) -> Vec<u8> {
    let cursor = store.file.stream_position().expect("fixture cursor");
    store.file.seek(SeekFrom::Start(0)).expect("fixture seek");
    let mut bytes = Vec::new();
    (&mut *store.file)
        .take(MAX_FILE_BYTES + 1)
        .read_to_end(&mut bytes)
        .expect("read original locked fixture");
    store
        .file
        .seek(SeekFrom::Start(cursor))
        .expect("restore fixture cursor");
    bytes
}

fn replace_locked(store: &mut LockedFileProductEvaluationExecutionStoreV1, bytes: &[u8]) {
    store.file.seek(SeekFrom::Start(0)).expect("fixture seek");
    store.file.write_all(bytes).expect("fixture mutation");
    store
        .file
        .set_len(bytes.len() as u64)
        .expect("fixture length");
    store.file.sync_all().expect("persist fixture mutation");
}

#[test]
fn current_reread_preserves_bytes_cursor_and_original_append_owner() {
    let temporary = TempJournal::new();
    let mut store = temporary.create();
    let empty = store.anchor();
    assert_eq!(store.read_current_anchor(), Ok(empty));
    store.claim(&key("completed")).expect("claim");
    store
        .complete(&key("completed"), b"original")
        .expect("complete");
    store.claim(&key("pending")).expect("pending claim");
    let expected = store.anchor();
    let before = locked_bytes(&mut store);
    for cursor in [0, 7, before.len() as u64, before.len() as u64 + 11] {
        store
            .file
            .seek(SeekFrom::Start(cursor))
            .expect("set arbitrary cursor");
        assert_eq!(store.read_current_anchor(), Ok(expected));
        assert_eq!(store.file.stream_position().expect("cursor"), cursor);
        assert_eq!(locked_bytes(&mut store), before);
    }
    assert_eq!(store.readback(&key("pending")), Ok(State::Pending));
    store
        .complete(&key("pending"), b"new original completion")
        .expect("same original writer remains usable");
    assert_eq!(store.read_current_anchor(), Ok(store.anchor()));
    assert_eq!(
        store.readback(&key("pending")),
        Ok(State::Completed(b"new original completion".to_vec()))
    );
}

#[test]
fn current_rejects_same_length_corruption_and_cannot_be_rearmed() {
    let temporary = TempJournal::new();
    let mut store = temporary.create();
    store.claim(&key("plan")).expect("claim");
    store.complete(&key("plan"), b"original").expect("complete");
    let expected = store.anchor();
    let before = locked_bytes(&mut store);
    let mut corrupt = before.clone();
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    replace_locked(&mut store, &corrupt);
    store.file.seek(SeekFrom::Start(9)).expect("set cursor");
    assert_eq!(store.read_current_anchor(), Err(FileError::Corrupt));
    assert_eq!(store.file.stream_position().expect("cursor"), 9);
    assert_eq!(locked_bytes(&mut store), corrupt);
    assert_eq!(store.anchor(), expected);
    replace_locked(&mut store, &before);
    assert_eq!(store.read_current_anchor(), Err(FileError::Indeterminate));
    assert_eq!(store.readback(&key("plan")), Err(StoreError::Indeterminate));
    assert_eq!(store.claim(&key("next")), Err(StoreError::Indeterminate));
    assert_eq!(
        store.complete(&key("plan"), b"original"),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(locked_bytes(&mut store), before);
}

#[test]
fn current_rejects_rehashed_valid_same_length_replacement() {
    let original_file = TempJournal::new();
    let replacement_file = TempJournal::new();
    let mut original = original_file.create();
    let mut replacement = replacement_file.create();
    for store in [&mut original, &mut replacement] {
        store.claim(&key("plan")).expect("claim");
    }
    original
        .complete(&key("plan"), b"accepted")
        .expect("original completion");
    replacement
        .complete(&key("plan"), b"rejected")
        .expect("different valid completion");
    let expected = original.anchor();
    let original_bytes = locked_bytes(&mut original);
    let replacement_bytes = locked_bytes(&mut replacement);
    assert_eq!(original_bytes.len(), replacement_bytes.len());
    assert_eq!(replacement.read_current_anchor(), Ok(replacement.anchor()));
    assert_ne!(replacement.anchor(), expected);
    replace_locked(&mut original, &replacement_bytes);
    original.file.seek(SeekFrom::Start(13)).expect("set cursor");
    assert_eq!(original.read_current_anchor(), Err(FileError::Rollback));
    assert_eq!(original.file.stream_position().expect("cursor"), 13);
    assert_eq!(locked_bytes(&mut original), replacement_bytes);
    assert_eq!(original.anchor(), expected);
    assert_eq!(
        original.readback(&key("plan")),
        Err(StoreError::Indeterminate)
    );
}

#[test]
fn current_refuses_length_changes_without_repair() {
    for mutation in ["header", "tail", "extra", "oversized"] {
        let temporary = TempJournal::new();
        let mut store = temporary.create();
        store.claim(&key("plan")).expect("claim");
        store.complete(&key("plan"), b"original").expect("complete");
        let original = locked_bytes(&mut store);
        let changed_length = match mutation {
            "header" => HEADER as u64 - 1,
            "tail" => original.len() as u64 - 1,
            "extra" => original.len() as u64 + 1,
            "oversized" => MAX_FILE_BYTES + 1,
            _ => unreachable!("fixture mutation"),
        };
        store.file.set_len(changed_length).expect("change length");
        store.file.sync_all().expect("persist length");
        let suspect = locked_bytes(&mut store);
        store.file.seek(SeekFrom::Start(17)).expect("set cursor");
        let expected = if mutation == "oversized" {
            FileError::Capacity
        } else {
            FileError::Corrupt
        };
        assert_eq!(store.read_current_anchor(), Err(expected));
        assert_eq!(store.file.stream_position().expect("cursor"), 17);
        assert_eq!(locked_bytes(&mut store), suspect);
        assert_eq!(
            store.file.metadata().expect("metadata").len(),
            changed_length
        );
        replace_locked(&mut store, &original);
        assert_eq!(store.read_current_anchor(), Err(FileError::Indeterminate));
        assert_eq!(store.claim(&key("new")), Err(StoreError::Indeterminate));
        assert_eq!(locked_bytes(&mut store), original);
    }
}

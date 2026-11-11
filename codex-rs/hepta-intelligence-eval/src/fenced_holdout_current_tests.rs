//! Real locked-file CURRENT checks; descriptor fault injection is test-only.

use super::*;
use pretty_assertions::assert_eq;

fn bytes(store: &mut LockedFileFinalHoldoutCasStoreV1) -> Vec<u8> {
    let position = store.file.stream_position().expect("original cursor");
    store.file.seek(SeekFrom::Start(0)).expect("original rewind");
    let mut value = Vec::new();
    (&mut *store.file).take(MAX_BYTES + 1).read_to_end(&mut value)
        .expect("original physical bytes");
    store.file.seek(SeekFrom::Start(position)).expect("restore original cursor");
    value
}

fn replace_bytes(store: &mut LockedFileFinalHoldoutCasStoreV1, value: &[u8]) {
    assert_eq!(store.file.metadata().expect("original length").len(), value.len() as u64);
    let position = store.file.stream_position().expect("original cursor");
    store.file.seek(SeekFrom::Start(0)).expect("original rewind");
    store.file.write_all(value).expect("test adversarial same-handle write");
    store.file.sync_all().expect("test adversarial sync");
    store.file.seek(SeekFrom::Start(position)).expect("restore original cursor");
}

fn initialized(temp: &TempFile) -> LockedFileFinalHoldoutCasStoreV1 {
    let store = LockedFileFinalHoldoutCasStoreV1::create(temp.create(), digest("binding"))
        .expect("actual empty locked file");
    owner(store, None).into_store()
}

#[test]
fn holdout_current_same_length_mutation_fences_after_restore() {
    for through_cas in [false, true] {
        let temp = TempFile::new();
        let mut store = initialized(&temp);
        let retained = store.load(digest("binding")).expect("physical state")
            .expect("original fence");
        let original = bytes(&mut store);
        let mut changed = original.clone();
        let payload_byte = changed.len() - 33;
        changed[payload_byte] ^= 1;
        replace_bytes(&mut store, &changed);
        let rejected = if through_cas {
            store.compare_and_swap(digest("binding"), Some(retained.state_digest), &retained)
        } else {
            store.load(digest("binding")).map(|_| ())
        };
        assert_eq!(rejected, Err(FinalHoldoutCasStoreError::Indeterminate));
        assert!(store.poisoned);
        replace_bytes(&mut store, &original);
        assert_eq!(store.load(digest("binding")), Err(FinalHoldoutCasStoreError::Indeterminate));
        assert_eq!(
            store.compare_and_swap(digest("binding"), Some(retained.state_digest), &retained),
            Err(FinalHoldoutCasStoreError::Indeterminate)
        );
        assert_eq!(bytes(&mut store), original);
    }
}

#[test]
fn holdout_current_rehashed_history_cannot_preserve_cached_frontier() {
    let temp = TempFile::new();
    let store = initialized(&temp);
    let first = store.anchor().expect("first physical fence");
    drop(store);
    let store = LockedFileFinalHoldoutCasStoreV1::recover(
        temp.open(), digest("binding"), Some(first),
    ).expect("original prefix");
    let mut store = owner(store, Some(first)).into_store();
    let original = bytes(&mut store);
    let retained = store.state.clone();
    let mut changed = original.clone();
    let count = u32::from_be_bytes(changed[HEADER..HEADER + 4].try_into()
        .expect("first frame length")) as usize;
    let payload_start = HEADER + 4;
    let checksum_start = payload_start + count;
    changed[checksum_start - 1] ^= 1; // Earlier lease only; the later fence is unchanged.
    let checksum = Digest32::of_bytes(&changed[payload_start..checksum_start]);
    changed[checksum_start..checksum_start + 32].copy_from_slice(checksum.as_array());
    replace_bytes(&mut store, &changed);

    let replayed = super::super::current::read_physical(
        &mut store.file, digest("binding"), None,
    ).expect("self-consistent changed old frame");
    assert_eq!(replayed.state, retained, "terminal state alone would miss the replacement");
    assert_ne!(replayed.history_digest, store.history_digest);
    assert_eq!(store.load(digest("binding")), Err(FinalHoldoutCasStoreError::Indeterminate));
    replace_bytes(&mut store, &original);
    assert_eq!(store.load(digest("binding")), Err(FinalHoldoutCasStoreError::Indeterminate));
    assert_eq!(bytes(&mut store), original);
}

#[test]
fn holdout_current_preserves_cursor_lock_and_fences_read_errors() {
    let temp = TempFile::new();
    let mut store = initialized(&temp);
    let original = bytes(&mut store);
    for position in [0, 7, original.len() as u64 + 3] {
        store.file.seek(SeekFrom::Start(position)).expect("set original cursor");
        assert!(store.load(digest("binding")).expect("physical load").is_some());
        assert_eq!(store.file.stream_position().expect("preserved cursor"), position);
    }
    assert_eq!(
        LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), digest("binding"), store.anchor()).err(),
        Some(LockedFileCasErrorV1::Busy)
    );

    let state = store.state.clone();
    let length = store.length;
    let history_digest = store.history_digest;
    drop(store);
    // Test-only descriptor fault: retain the genuine original state and file,
    // but deny reads on its exclusively held handle. No production factory
    // accepts such a cache, and no alternate reader may satisfy this load.
    let file = OpenOptions::new().write(true).open(&temp.path).expect("write-only original file");
    let mut unreadable = LockedFileFinalHoldoutCasStoreV1 {
        file: acquire(file, digest("binding")).expect("exclusive fault descriptor"),
        binding: digest("binding"),
        state,
        length,
        history_digest,
        poisoned: false,
    };
    unreadable.file.seek(SeekFrom::Start(11)).expect("fault cursor");
    assert_eq!(unreadable.load(digest("binding")), Err(FinalHoldoutCasStoreError::Indeterminate));
    assert_eq!(unreadable.file.stream_position().expect("error restores cursor"), 11);
    assert!(unreadable.poisoned);
    assert_eq!(unreadable.load(digest("binding")), Err(FinalHoldoutCasStoreError::Indeterminate));
    drop(unreadable);
    assert_eq!(fs::read(&temp.path).expect("unchanged physical file"), original);
}

#[test]
fn holdout_current_cold_recovery_and_non_target_calls_preserve_original_bytes() {
    let empty = TempFile::new();
    let mut store = LockedFileFinalHoldoutCasStoreV1::create(empty.create(), digest("binding"))
        .expect("explicit empty original");
    let header = bytes(&mut store);
    assert_eq!(store.load(digest("binding")), Ok(None));
    drop(store);
    let mut store = LockedFileFinalHoldoutCasStoreV1::recover(
        empty.open(), digest("binding"), None,
    ).expect("recover original empty header");
    assert_eq!(store.load(digest("binding")), Ok(None));
    assert_eq!(bytes(&mut store), header);
    drop(store);

    let temp = TempFile::new();
    let store = LockedFileFinalHoldoutCasStoreV1::create(temp.create(), digest("binding"))
        .expect("original file");
    let mut first = owner(store, None);
    let frozen = plan("physical-current-plan");
    first.consume(&frozen).expect("actual original consumption");
    let minimum = first.anchor();
    let fence = first.fence().clone();
    let mut store = first.into_store();
    let original = bytes(&mut store);
    drop(store);
    let store = LockedFileFinalHoldoutCasStoreV1::recover(
        temp.open(), digest("binding"), Some(minimum),
    ).expect("exact original physical history");
    let mut recovered = FencedFinalHoldoutOwnerV1::recover(store, digest("binding"), fence)
        .expect("same original fence");
    assert_eq!(
        recovered.consume(&frozen).expect("read existing consumption").disposition,
        crate::HoldoutUseDispositionV1::IdempotentReplay
    );
    let mut store = recovered.into_store();
    let retained = store.load(digest("binding")).expect("physical original state")
        .expect("initialized original");
    assert_eq!(store.load(digest("different-binding")), Err(FinalHoldoutCasStoreError::Conflict));
    assert_eq!(
        store.compare_and_swap(digest("different-binding"), Some(retained.state_digest), &retained),
        Err(FinalHoldoutCasStoreError::Conflict)
    );
    assert_eq!(
        store.compare_and_swap(digest("binding"), Some(digest("wrong-expected")), &retained),
        Err(FinalHoldoutCasStoreError::Conflict)
    );
    let mut invalid = retained.clone();
    invalid.state_digest = Digest32::ZERO;
    assert_eq!(
        store.compare_and_swap(digest("binding"), Some(retained.state_digest), &invalid),
        Err(FinalHoldoutCasStoreError::Rejected)
    );
    assert!(!store.poisoned);
    store.compare_and_swap(digest("binding"), Some(retained.state_digest), &retained)
        .expect("idempotent original CAS");
    assert_eq!(store.load(digest("binding")), Ok(Some(retained)));
    assert_eq!(bytes(&mut store), original);
}

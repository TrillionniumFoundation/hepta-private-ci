//! Real-file faults with a separately asserted successful initial observation.
//! Every restore assertion follows a successful assertion of the first refusal.

use super::*;
use pretty_assertions::assert_eq;

fn read_held_bytes(file: &mut std::fs::File) -> std::io::Result<Vec<u8>> {
    // A duplicate of the original file shares its cursor. Restore it even if the read fails.
    let original_cursor = file.stream_position()?;
    let mut bytes = Vec::new();
    let read_result = file
        .seek(SeekFrom::Start(0))
        .and_then(|_| file.read_to_end(&mut bytes));
    let restore_result = file.seek(SeekFrom::Start(original_cursor));
    read_result?;
    restore_result?;
    Ok(bytes)
}

fn overwrite(file: &mut std::fs::File, bytes: &[u8]) {
    let original_cursor = file.stream_position().expect("original physical cursor");
    let write_result = file
        .seek(SeekFrom::Start(0))
        .and_then(|_| file.write_all(bytes))
        .and_then(|()| file.set_len(bytes.len() as u64))
        .and_then(|()| file.sync_all());
    let restore_result = file.seek(SeekFrom::Start(original_cursor));
    write_result.unwrap_or_else(|error| panic!("persist physical fault or restore: {error}"));
    restore_result.unwrap_or_else(|error| panic!("restore original physical cursor: {error}"));
}

fn populated() -> (
    TempFile,
    std::fs::File,
    FencedFinalHoldoutOwnerV1<LockedFileFinalHoldoutCasStoreV1>,
) {
    let temp = TempFile::new();
    let file = temp.create();
    // Keep the same open file description while the real store retains its exclusive lock.
    let observation = file.try_clone().expect("retain original physical handle");
    let store = LockedFileFinalHoldoutCasStoreV1::create(file, digest("binding"))
        .unwrap_or_else(|error| panic!("create physical store: {error}"));
    let mut original = owner(store, /*minimum*/ None);
    original
        .consume(&plan("physical-plan"))
        .unwrap_or_else(|error| panic!("consume actual original plan: {error}"));
    (temp, observation, original)
}

#[test]
fn original_holdout_load_refuses_same_length_corruption_and_restored_bytes() {
    let (temp, mut observation, original) = populated();
    let minimum = original.anchor();
    let mut store = original.into_store();
    let expected = store
        .load(digest("binding"))
        .unwrap_or_else(|error| panic!("initial physical read: {error}"));
    assert!(expected.is_some());
    let saved = read_held_bytes(&mut observation)
        .unwrap_or_else(|error| panic!("read actual bytes: {error}"));
    let mut corrupt = saved.clone();
    corrupt[HEADER + 4] ^= 0x80;
    assert_eq!(corrupt.len(), saved.len());
    overwrite(&mut observation, &corrupt);
    assert_eq!(
        store.load(digest("binding")),
        Err(FinalHoldoutCasStoreError::Indeterminate),
        "the first read must detect actual same-length corruption"
    );
    overwrite(&mut observation, &saved);
    assert_eq!(
        store.load(digest("binding")),
        Err(FinalHoldoutCasStoreError::Indeterminate),
        "restoring old bytes must not clear this handle's refusal"
    );
    drop(store);
    // This is explicitly a same-handle poison. An independently retained
    // refusal marker is required for a persistent cross-process guarantee.
    let mut reopened =
        LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), digest("binding"), Some(minimum))
            .unwrap_or_else(|error| panic!("separate owner at retained valid cut: {error}"));
    assert_eq!(reopened.load(digest("binding")), Ok(expected));
}

#[test]
fn original_holdout_cas_refuses_corruption_before_idempotent_return() {
    let (_temp, mut observation, original) = populated();
    let mut store = original.into_store();
    let current = store
        .load(digest("binding"))
        .unwrap_or_else(|error| panic!("initial physical read: {error}"))
        .unwrap_or_else(|| panic!("actual committed state is missing"));
    let expected = Some(current.state_digest);
    assert_eq!(
        store.compare_and_swap(digest("binding"), expected, &current),
        Ok(())
    );
    let saved = read_held_bytes(&mut observation)
        .unwrap_or_else(|error| panic!("read actual bytes: {error}"));
    let mut corrupt = saved.clone();
    corrupt[8] ^= 1;
    assert_eq!(corrupt.len(), saved.len());
    overwrite(&mut observation, &corrupt);
    assert_eq!(
        store.compare_and_swap(digest("binding"), expected, &current),
        Err(FinalHoldoutCasStoreError::Indeterminate)
    );
    assert_eq!(
        read_held_bytes(&mut observation).unwrap_or_else(|error| panic!("read fault: {error}")),
        corrupt
    );
    overwrite(&mut observation, &saved);
    assert_eq!(
        store.compare_and_swap(digest("binding"), expected, &current),
        Err(FinalHoldoutCasStoreError::Indeterminate)
    );
    assert_eq!(
        read_held_bytes(&mut observation).unwrap_or_else(|error| panic!("read restore: {error}")),
        saved
    );
}

#[test]
fn original_holdout_consumption_refuses_corruption_then_restoration() {
    let (_temp, mut observation, mut original) = populated();
    let frozen = plan("physical-plan");
    let (binding, receipt) = original
        .read_consumption(&frozen)
        .unwrap_or_else(|error| panic!("initial actual consumption: {error}"));
    assert_eq!(binding, digest("binding"));
    assert!(receipt.is_some());
    let saved = read_held_bytes(&mut observation)
        .unwrap_or_else(|error| panic!("read actual bytes: {error}"));
    let mut corrupt = saved.clone();
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    overwrite(&mut observation, &corrupt);
    assert_eq!(
        original.read_consumption(&frozen),
        Err(crate::FencedHoldoutError::Store(
            FinalHoldoutCasStoreError::Indeterminate
        ))
    );
    overwrite(&mut observation, &saved);
    assert_eq!(
        original.read_consumption(&frozen),
        Err(crate::FencedHoldoutError::Store(
            FinalHoldoutCasStoreError::Indeterminate
        ))
    );
}

#[test]
fn original_holdout_physical_length_changes_never_repair_or_clear_refusal() {
    for truncate in [true, false] {
        let (_temp, mut observation, original) = populated();
        let mut store = original.into_store();
        assert!(store.load(digest("binding")).is_ok());
        let saved =
            read_held_bytes(&mut observation).unwrap_or_else(|error| panic!("read bytes: {error}"));
        let mut changed = saved.clone();
        if truncate {
            changed.truncate(changed.len() - 1);
        } else {
            changed.extend_from_slice(&[0, 0, 0]);
        }
        overwrite(&mut observation, &changed);
        assert_eq!(
            store.load(digest("binding")),
            Err(FinalHoldoutCasStoreError::Indeterminate)
        );
        assert_eq!(
            read_held_bytes(&mut observation)
                .unwrap_or_else(|error| panic!("read changed: {error}")),
            changed
        );
        overwrite(&mut observation, &saved);
        assert_eq!(
            store.load(digest("binding")),
            Err(FinalHoldoutCasStoreError::Indeterminate)
        );
    }
}

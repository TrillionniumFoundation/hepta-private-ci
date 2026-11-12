//! Real-file faults with a separately asserted successful initial observation.
//! Every restore assertion follows a successful assertion of the first refusal.

use super::*;
use pretty_assertions::assert_eq;

fn overwrite(temp: &TempFile, bytes: &[u8]) {
    let mut file = temp.open();
    file.seek(SeekFrom::Start(0))
        .and_then(|_| file.write_all(bytes))
        .and_then(|()| file.set_len(bytes.len() as u64))
        .and_then(|()| file.sync_all())
        .unwrap_or_else(|error| panic!("persist physical fault or restore: {error}"));
}

fn populated() -> (
    TempFile,
    FencedFinalHoldoutOwnerV1<LockedFileFinalHoldoutCasStoreV1>,
) {
    let temp = TempFile::new();
    let store = LockedFileFinalHoldoutCasStoreV1::create(temp.create(), digest("binding"))
        .unwrap_or_else(|error| panic!("create physical store: {error}"));
    let mut original = owner(store, /*minimum*/ None);
    original
        .consume(&plan("physical-plan"))
        .unwrap_or_else(|error| panic!("consume actual original plan: {error}"));
    (temp, original)
}

#[test]
fn original_holdout_load_refuses_same_length_corruption_and_restored_bytes() {
    let (temp, original) = populated();
    let minimum = original.anchor();
    let mut store = original.into_store();
    let expected = store
        .load(digest("binding"))
        .unwrap_or_else(|error| panic!("initial physical read: {error}"));
    assert!(expected.is_some());
    let saved = fs::read(&temp.path).unwrap_or_else(|error| panic!("read actual bytes: {error}"));
    let mut corrupt = saved.clone();
    corrupt[HEADER + 4] ^= 0x80;
    assert_eq!(corrupt.len(), saved.len());
    overwrite(&temp, &corrupt);
    assert_eq!(
        store.load(digest("binding")),
        Err(FinalHoldoutCasStoreError::Indeterminate),
        "the first read must detect actual same-length corruption"
    );
    overwrite(&temp, &saved);
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
    let (temp, original) = populated();
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
    let saved = fs::read(&temp.path).unwrap_or_else(|error| panic!("read actual bytes: {error}"));
    let mut corrupt = saved.clone();
    corrupt[8] ^= 1;
    assert_eq!(corrupt.len(), saved.len());
    overwrite(&temp, &corrupt);
    assert_eq!(
        store.compare_and_swap(digest("binding"), expected, &current),
        Err(FinalHoldoutCasStoreError::Indeterminate)
    );
    assert_eq!(
        fs::read(&temp.path).unwrap_or_else(|error| panic!("read fault: {error}")),
        corrupt
    );
    overwrite(&temp, &saved);
    assert_eq!(
        store.compare_and_swap(digest("binding"), expected, &current),
        Err(FinalHoldoutCasStoreError::Indeterminate)
    );
    assert_eq!(
        fs::read(&temp.path).unwrap_or_else(|error| panic!("read restore: {error}")),
        saved
    );
}

#[test]
fn original_holdout_consumption_refuses_corruption_then_restoration() {
    let (temp, mut original) = populated();
    let frozen = plan("physical-plan");
    let (binding, receipt) = original
        .read_consumption(&frozen)
        .unwrap_or_else(|error| panic!("initial actual consumption: {error}"));
    assert_eq!(binding, digest("binding"));
    assert!(receipt.is_some());
    let saved = fs::read(&temp.path).unwrap_or_else(|error| panic!("read actual bytes: {error}"));
    let mut corrupt = saved.clone();
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    overwrite(&temp, &corrupt);
    assert_eq!(
        original.read_consumption(&frozen),
        Err(crate::FencedHoldoutError::Store(
            FinalHoldoutCasStoreError::Indeterminate
        ))
    );
    overwrite(&temp, &saved);
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
        let (temp, original) = populated();
        let mut store = original.into_store();
        assert!(store.load(digest("binding")).is_ok());
        let saved = fs::read(&temp.path).unwrap_or_else(|error| panic!("read bytes: {error}"));
        let mut changed = saved.clone();
        if truncate {
            changed.truncate(changed.len() - 1);
        } else {
            changed.extend_from_slice(&[0, 0, 0]);
        }
        overwrite(&temp, &changed);
        assert_eq!(
            store.load(digest("binding")),
            Err(FinalHoldoutCasStoreError::Indeterminate)
        );
        assert_eq!(
            fs::read(&temp.path).unwrap_or_else(|error| panic!("read changed: {error}")),
            changed
        );
        overwrite(&temp, &saved);
        assert_eq!(
            store.load(digest("binding")),
            Err(FinalHoldoutCasStoreError::Indeterminate)
        );
    }
}

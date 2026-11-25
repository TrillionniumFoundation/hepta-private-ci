use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[test]
fn locked_durable_inspection_holds_the_original_publication_lock_without_advancing() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store =
        HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), vec![1_u64, 7]).unwrap();
    let other = HostAuthorityFrontierStore::<Vec<u64>>::open(root, OWNER.into()).unwrap();
    let result = store.with_locked_durable(OWNER, |actual| {
        assert_eq!(actual, &[1, 7]);
        assert_eq!(
            other.compare_and_set(OWNER, &vec![1, 7], &vec![2, 9]),
            Err(AuthorityTrustError::Conflict)
        );
        assert_eq!(other.load(OWNER), Err(AuthorityTrustError::Conflict));
        Err::<(), _>("another owner's controlled failure")
    });
    assert_eq!(result, Ok(Err("another owner's controlled failure")));
    assert_eq!(store.load(OWNER), Ok(vec![1, 7]));
    assert_eq!(
        other.compare_and_set(OWNER, &vec![1, 7], &vec![2, 9]),
        Ok(())
    );
}

#[test]
fn locked_inspection_never_calls_back_after_a_failed_real_durable_read() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        Err(std::io::Error::other(
            "controlled sync failure after rename",
        ))
    }));
    assert_eq!(
        store.compare_and_set(OWNER, &1, &2),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(store.read(), Ok(2));
    let called = AtomicBool::new(false);
    assert_eq!(
        store.with_locked_durable(OWNER, |_| called.store(true, Ordering::SeqCst)),
        Err(AuthorityTrustError::Unavailable)
    );
    assert!(!called.load(Ordering::SeqCst));
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(store.with_locked_durable(OWNER, |actual| *actual), Ok(2));
    assert_eq!(store.load(OWNER), Ok(2));
}

#[test]
fn locked_inspection_detects_changed_bytes_after_an_external_owner_action() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root, OWNER.into(), 1_u64).unwrap();
    let path = directory.path().join(&store.name);
    let result = store.with_locked_durable(OWNER, |_| {
        // Only this private owner fixture can corrupt its actual protected
        // record. A callback result must not suppress post-action verification.
        std::fs::write(&path, b"{").unwrap();
        17
    });
    assert_eq!(result, Err(AuthorityTrustError::Invalid));
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Invalid));
}

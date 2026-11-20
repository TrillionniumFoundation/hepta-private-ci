use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

fn fail_sync(root: &RootAuthorityDirectory) -> Arc<AtomicUsize> {
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = calls.clone();
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(move || {
        observed.fetch_add(1, Ordering::SeqCst);
        Err(std::io::Error::other("controlled directory sync failure"))
    }));
    calls
}

#[test]
fn retained_exact_inode_and_bytes_avoid_only_redundant_sync() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    let calls = fail_sync(&root);
    assert_eq!(store.load(OWNER), Ok(1));
    assert_eq!(store.load(OWNER), Ok(1));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    // Another handle has no witness, even if the visible bytes are identical.
    assert!(matches!(
        HostAuthorityFrontierStore::<u64>::open(root.clone(), OWNER.into()),
        Err(AuthorityTrustError::Unavailable)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    *root.before_directory_sync.lock().unwrap() = None;
}

#[test]
fn a_real_second_handle_replacement_invalidates_the_retained_inode() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    let other = HostAuthorityFrontierStore::<u64>::open(root.clone(), OWNER.into()).unwrap();
    other.compare_and_set(OWNER, &1, &2).unwrap();
    let calls = fail_sync(&root);
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Unavailable));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(store.load(OWNER), Ok(2));
    // Equal logical value and complete bytes still cannot certify a new inode.
    other.compare_and_set(OWNER, &2, &2).unwrap();
    let calls = fail_sync(&root);
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Unavailable));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(store.load(OWNER), Ok(2));
}

#[test]
fn same_inode_same_length_changed_bytes_require_real_sync() {
    use std::io::Seek;
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    let (_, retained) = store.read_record().unwrap();
    let mut changed = retained.bytes.clone();
    let index = changed
        .windows(12)
        .position(|part| part == b"\"frontier\":1")
        .unwrap()
        + 11;
    changed[index] = b'2';
    let mut file = root.open_private(&store.name, OFlags::RDWR).unwrap();
    file.rewind().unwrap();
    file.write_all(&changed).unwrap();
    assert_eq!(
        file.metadata().unwrap().ino(),
        retained.file.metadata().unwrap().ino()
    );
    assert_eq!(file.metadata().unwrap().len(), retained.bytes.len() as u64);
    let calls = fail_sync(&root);
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Unavailable));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(store.load(OWNER), Ok(2));
}

#[test]
fn a_failed_read_forgets_a_previous_durability_witness() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    let path = directory.path().join(&store.name);
    let hidden = directory.path().join("controlled-temporary-removal");
    std::fs::rename(&path, &hidden).unwrap();
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Unavailable));
    std::fs::rename(&hidden, &path).unwrap();
    let calls = fail_sync(&root);
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Unavailable));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(store.load(OWNER), Ok(1));
}

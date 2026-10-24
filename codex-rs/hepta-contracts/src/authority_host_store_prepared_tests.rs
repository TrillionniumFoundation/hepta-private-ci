//! Actual original-store fences for clock preparation and late durability.
//! These use real files/flock and OS time; the existing test-only directory
//! helper changes only ownership provisioning for the ordinary test UID.

use super::*;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::os::unix::fs::MetadataExt;

#[test]
fn prepared_constructor_follows_temporary_validation_and_holds_original_lock() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let naming = HostAuthorityFrontierStore::<u64>::configured(root.clone(), OWNER.into()).unwrap();
    let canonical = directory.path().join(&naming.name);
    let temporary = directory.path().join(format!("{}.next", naming.name));
    let calls = Cell::new(0);
    let (store, initial) =
        HostAuthorityFrontierStore::initialize_prepared(root.clone(), OWNER.into(), || {
            calls.set(calls.get() + 1);
            // A constructor moved ahead of preparation fails these actual
            // inode observations. No canonical frontier is yet visible.
            let metadata = std::fs::symlink_metadata(&temporary).unwrap();
            assert!(metadata.is_file());
            assert_eq!(metadata.len(), 0);
            assert_eq!(metadata.mode() & 0o777, 0o600);
            assert_eq!(metadata.uid(), rustix::process::geteuid().as_raw());
            assert_eq!(metadata.nlink(), 1);
            assert!(!canonical.exists());
            assert!(matches!(
                naming.publication_lock(),
                Err(AuthorityTrustError::Conflict)
            ));
            Ok(7_u64)
        })
        .unwrap();
    assert_eq!(calls.get(), 1);
    assert_eq!(initial, 7);
    assert_eq!(store.load(OWNER), Ok(7));
    assert!(!temporary.exists());
    drop(store);
    let reopened = HostAuthorityFrontierStore::<u64>::open(root, OWNER.into()).unwrap();
    assert_eq!(reopened.load(OWNER), Ok(7));
}

#[test]
fn prepared_initialization_cannot_rebuild_existing_frontier() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 7_u64).unwrap();
    let retained = std::fs::read(directory.path().join(&store.name)).unwrap();
    let calls = Cell::new(0);
    let result = HostAuthorityFrontierStore::initialize_prepared(root, OWNER.into(), || {
        calls.set(calls.get() + 1);
        Ok(0_u64)
    });
    assert!(matches!(result, Err(AuthorityTrustError::Conflict)));
    assert_eq!(calls.get(), 0);
    assert_eq!(
        std::fs::read(directory.path().join(&store.name)).unwrap(),
        retained
    );
    assert_eq!(store.load(OWNER), Ok(7));
}

#[test]
fn prepared_cas_rejects_wrong_owner_preimage_and_contested_flock_before_constructor() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root, OWNER.into(), 7_u64).unwrap();
    let calls = Cell::new(0);
    let build = || {
        calls.set(calls.get() + 1);
        Ok(9_u64)
    };
    assert_eq!(
        store.compare_and_set_prepared("another-owner", &7, build),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(
        store.compare_and_set_prepared(OWNER, &6, build),
        Err(AuthorityTrustError::Conflict)
    );
    let competing = store.publication_lock().unwrap();
    assert_eq!(
        store.compare_and_set_prepared(OWNER, &7, build),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(calls.get(), 0);
    assert!(
        !directory
            .path()
            .join(format!("{}.next", store.name))
            .exists()
    );
    drop(competing);
    assert_eq!(store.load(OWNER), Ok(7));
    assert_eq!(store.compare_and_set_prepared(OWNER, &7, build), Ok(9));
    assert_eq!(calls.get(), 1);
    assert_eq!(store.load(OWNER), Ok(9));
}

#[test]
fn prepared_cas_does_not_follow_or_truncate_an_aliased_temporary() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root, OWNER.into(), 7_u64).unwrap();
    let outside = directory.path().join("other-owner-input");
    std::fs::write(&outside, b"retained bytes").unwrap();
    std::fs::set_permissions(&outside, std::fs::Permissions::from_mode(0o600)).unwrap();
    let temporary = directory.path().join(format!("{}.next", store.name));
    let calls = Cell::new(0);
    let build = || {
        calls.set(calls.get() + 1);
        Ok(9_u64)
    };
    std::os::unix::fs::symlink(&outside, &temporary).unwrap();
    assert_eq!(
        store.compare_and_set_prepared(OWNER, &7, build),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(calls.get(), 0);
    assert_eq!(std::fs::read(&outside).unwrap(), b"retained bytes");
    std::fs::remove_file(&temporary).unwrap();
    std::fs::hard_link(&outside, &temporary).unwrap();
    assert_eq!(
        store.compare_and_set_prepared(OWNER, &7, build),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(calls.get(), 0);
    assert_eq!(std::fs::read(&outside).unwrap(), b"retained bytes");
    assert_eq!(store.load(OWNER), Ok(7));
}

#[test]
fn prepared_constructor_failure_preserves_frontier_and_releases_owner_lock() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root, OWNER.into(), 7_u64).unwrap();
    let retained = std::fs::read(directory.path().join(&store.name)).unwrap();
    let result =
        store.compare_and_set_prepared(OWNER, &7, || Err(AuthorityTrustError::Unavailable));
    assert_eq!(result, Err(AuthorityTrustError::Unavailable));
    assert_eq!(
        std::fs::read(directory.path().join(&store.name)).unwrap(),
        retained
    );
    assert_eq!(store.load(OWNER), Ok(7));
    // A separately requested real CAS proves cancellation/error did not leave
    // an owner lock or an implicitly published replacement behind.
    assert_eq!(store.compare_and_set(OWNER, &7, &9), Ok(()));
    assert_eq!(store.load(OWNER), Ok(9));
}

#[test]
fn prepared_directory_sync_failure_keeps_visible_write_unacknowledged() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 7_u64).unwrap();
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        Err(std::io::Error::other(
            "controlled directory durability failure",
        ))
    }));
    assert_eq!(
        store.compare_and_set_prepared(OWNER, &7, || Ok(9)),
        Err(AuthorityTrustError::Unavailable)
    );
    // Rename visibility is not a durability acknowledgement. The same
    // original load must refuse it while the durability boundary still fails.
    let visible: Record<u64> =
        serde_json::from_slice(&std::fs::read(directory.path().join(&store.name)).unwrap())
            .unwrap();
    assert_eq!(visible.frontier, 9);
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Unavailable));
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(store.load(OWNER), Ok(9));
}

#[cfg(target_os = "linux")]
#[test]
fn prepared_clock_still_rejects_real_post_write_one_second_overrun() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        // This is after actual file fsync and rename, not a fake clock value.
        // The original post-I/O clock observation must refuse this window.
        std::thread::sleep(Duration::from_millis(1_100));
        Ok(())
    }));
    let result = crate::HostAuthorityClock::initialize(root.clone(), "prepared-late-clock".into());
    assert!(matches!(result, Err(AuthorityTrustError::Unavailable)));
    *root.before_directory_sync.lock().unwrap() = None;
    let retained = HostAuthorityFrontierStore::<serde_json::Value>::open(
        root.clone(),
        "prepared-late-clock".into(),
    )
    .unwrap();
    let record = retained.load("prepared-late-clock").unwrap();
    assert_eq!(
        record["ceiling_ns"].as_u64().unwrap() - record["unix_ns"].as_u64().unwrap(),
        1_000_000_000
    );
    // Failed post-I/O publication leaves original durable evidence intact.
    // Neither the clock API nor generated initializer may reset it to genesis.
    assert!(matches!(
        crate::HostAuthorityClock::initialize(root, "prepared-late-clock".into()),
        Err(AuthorityTrustError::Conflict)
    ));
    assert_eq!(retained.load("prepared-late-clock"), Ok(record));
}

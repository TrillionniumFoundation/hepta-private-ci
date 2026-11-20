use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Barrier;

fn store(root: &tempfile::TempDir) -> DeploymentFrontierStore<u64> {
    DeploymentFrontierStore::create(&root.path().join("external-frontier")).unwrap()
}

#[test]
fn restart_retains_cas_and_rejects_an_old_local_snapshot() {
    let root = tempfile::tempdir().unwrap();
    let store = store(&root);
    store.provision("owner", &1).unwrap();
    store.compare_and_set("owner", &1, &2).unwrap();
    drop(store);
    let reopened =
        DeploymentFrontierStore::<u64>::open(&root.path().join("external-frontier")).unwrap();
    assert_eq!(reopened.load("owner"), Ok(2));
    assert_eq!(
        reopened.compare_and_set("owner", &1, &3),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(reopened.load("owner"), Ok(2));
    assert!(reopened.provision("owner", &1).is_err());
}

#[test]
fn independent_handles_have_exactly_one_cas_winner() {
    let root = tempfile::tempdir().unwrap();
    let store = store(&root);
    store.provision("owner", &1).unwrap();
    let barrier = Arc::new(Barrier::new(9));
    let handles: Vec<_> = (2..10)
        .map(|value| {
            let path = root.path().join("external-frontier");
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                let store = DeploymentFrontierStore::<u64>::open(&path).unwrap();
                barrier.wait();
                store.compare_and_set("owner", &1, &value)
            })
        })
        .collect();
    barrier.wait();
    let outcomes: Vec<_> = handles.into_iter().map(|h| h.join().unwrap()).collect();
    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|result| **result == Err(AuthorityTrustError::Conflict))
            .count(),
        7
    );
}

#[test]
fn missing_corrupt_wrong_owner_and_symlink_never_reinitialize() {
    let root = tempfile::tempdir().unwrap();
    let store = store(&root);
    assert_eq!(store.load("missing"), Err(AuthorityTrustError::Unavailable));
    store.provision("owner", &1).unwrap();
    let path = store.record_path("owner").unwrap();
    std::fs::write(&path, b"broken").unwrap();
    assert_eq!(store.load("owner"), Err(AuthorityTrustError::Unavailable));
    assert_eq!(std::fs::read(&path).unwrap(), b"broken");
    std::fs::write(
        &path,
        br#"{"schema_version":1,"owner_id":"wrong","frontier":1}"#,
    )
    .unwrap();
    assert_eq!(store.load("owner"), Err(AuthorityTrustError::Unavailable));
    std::fs::remove_file(&path).unwrap();
    let outside = root.path().join("outside");
    std::fs::write(&outside, b"outside remains unchanged").unwrap();
    std::os::unix::fs::symlink(&outside, &path).unwrap();
    assert_eq!(store.load("owner"), Err(AuthorityTrustError::Unavailable));
    assert_eq!(
        std::fs::read(&outside).unwrap(),
        b"outside remains unchanged"
    );
}

#[test]
fn unsafe_permissions_and_hardlinks_are_refused() {
    let root = tempfile::tempdir().unwrap();
    let store = store(&root);
    store.provision("owner", &1).unwrap();
    let path = store.record_path("owner").unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(store.load("owner"), Err(AuthorityTrustError::Unavailable));
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::fs::hard_link(&path, root.path().join("alias")).unwrap();
    assert_eq!(store.load("owner"), Err(AuthorityTrustError::Unavailable));
    std::fs::set_permissions(&store.directory, std::fs::Permissions::from_mode(0o755)).unwrap();
    assert!(DeploymentFrontierStore::<u64>::open(&store.directory).is_err());
}

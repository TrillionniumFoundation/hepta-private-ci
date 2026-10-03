use super::*;

use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;

#[test]
fn second_writer_is_rejected_by_the_existing_owner_lock() {
    let directory = tempfile::tempdir().expect("directory");
    let (_store, _state) = ExactDeliveryStore::open(directory.path()).expect("first owner");
    assert!(matches!(
        ExactDeliveryStore::open(directory.path()),
        Err(ExactContextDeliveryError::StateLocked)
    ));
}

#[test]
fn state_and_next_symlinks_fail_closed_without_poisoning_unrelated_capacity() {
    let parent = tempfile::tempdir().expect("parent");
    let state_root = parent.path().join("state-root");
    std::fs::create_dir(&state_root).expect("state root");
    std::fs::set_permissions(&state_root, std::fs::Permissions::from_mode(0o700))
        .expect("state root mode");
    let outside = parent.path().join("outside");
    std::fs::write(&outside, b"outside").expect("outside");
    symlink(&outside, state_root.join(STATE_FILE)).expect("state symlink");
    assert!(matches!(
        ExactDeliveryStore::open(&state_root),
        Err(ExactContextDeliveryError::Unavailable)
    ));

    let next_root = parent.path().join("next-root");
    let (store, state) = ExactDeliveryStore::open(&next_root).expect("store");
    symlink(&outside, next_root.join(NEXT_FILE)).expect("next symlink");
    assert_eq!(
        store.persist(&state),
        Err(ExactContextDeliveryError::Unavailable)
    );
    assert_eq!(
        std::fs::read(&outside).expect("outside remains intact"),
        b"outside"
    );
    std::fs::remove_file(next_root.join(NEXT_FILE)).expect("remove next symlink");
    store
        .persist(&state)
        .expect("ordinary path remains usable after a deterministic rejection");
}

#[test]
fn permissive_or_hard_linked_state_files_are_rejected() {
    let parent = tempfile::tempdir().expect("parent");
    let mode_root = parent.path().join("mode-root");
    let (store, state) = ExactDeliveryStore::open(&mode_root).expect("store");
    store.persist(&state).expect("persist");
    drop(store);
    std::fs::set_permissions(
        mode_root.join(STATE_FILE),
        std::fs::Permissions::from_mode(0o644),
    )
    .expect("permissive mode");
    assert!(matches!(
        ExactDeliveryStore::open(&mode_root),
        Err(ExactContextDeliveryError::Unavailable)
    ));

    let link_root = parent.path().join("link-root");
    let (store, state) = ExactDeliveryStore::open(&link_root).expect("store");
    store.persist(&state).expect("persist");
    drop(store);
    std::fs::hard_link(
        link_root.join(STATE_FILE),
        parent.path().join("state-hard-link"),
    )
    .expect("hard link");
    assert!(matches!(
        ExactDeliveryStore::open(&link_root),
        Err(ExactContextDeliveryError::Unavailable)
    ));
}

#[test]
fn root_replacement_fences_the_owner_even_after_path_restoration() {
    let parent = tempfile::tempdir().expect("parent");
    let root = parent.path().join("state");
    let backup = parent.path().join("state-backup");
    let (store, state) = ExactDeliveryStore::open(&root).expect("store");

    std::fs::rename(&root, &backup).expect("detach owned root");
    std::fs::create_dir(&root).expect("replacement root");
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
        .expect("replacement mode");
    assert_eq!(
        store.persist(&state),
        Err(ExactContextDeliveryError::ReopenRequired)
    );
    assert!(!root.join(STATE_FILE).exists());

    std::fs::remove_dir(&root).expect("remove replacement");
    std::fs::rename(&backup, &root).expect("restore original root");
    assert_eq!(
        store.persist(&state),
        Err(ExactContextDeliveryError::ReopenRequired)
    );
    drop(store);

    let (reopened, reopened_state) = ExactDeliveryStore::open(&root).expect("reopen owner");
    reopened
        .persist(&reopened_state)
        .expect("reopened owner can persist");
}

#[test]
fn lock_links_and_symlink_ancestors_cannot_redirect_the_owner() {
    let parent = tempfile::tempdir().expect("parent");
    let outside = parent.path().join("outside");
    std::fs::write(&outside, b"outside").expect("outside");
    std::fs::set_permissions(&outside, std::fs::Permissions::from_mode(0o600)).expect("mode");
    for linked in [false, true] {
        let root = parent
            .path()
            .join(if linked { "hard-root" } else { "sym-root" });
        std::fs::create_dir(&root).expect("root");
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).expect("root mode");
        if linked {
            std::fs::hard_link(&outside, root.join(LOCK_FILE)).expect("hardlink");
        } else {
            symlink(&outside, root.join(LOCK_FILE)).expect("symlink");
        }
        assert!(matches!(
            ExactDeliveryStore::open(&root),
            Err(ExactContextDeliveryError::Unavailable)
        ));
        assert_eq!(std::fs::read(&outside).expect("outside"), b"outside");
    }
    let real = parent.path().join("real");
    std::fs::create_dir(&real).expect("real");
    let alias = parent.path().join("alias");
    symlink(&real, &alias).expect("ancestor symlink");
    assert!(matches!(
        ExactDeliveryStore::open(&alias.join("child")),
        Err(ExactContextDeliveryError::Unavailable)
    ));
    assert!(!real.join("child").exists());
}

#[test]
fn replacing_the_lock_fences_the_pinned_owner() {
    let directory = tempfile::tempdir().expect("directory");
    let (store, state) = ExactDeliveryStore::open(directory.path()).expect("owner");
    std::fs::rename(
        directory.path().join(LOCK_FILE),
        directory.path().join("old-lock"),
    )
    .expect("detach lock");
    std::fs::write(directory.path().join(LOCK_FILE), b"").expect("replacement lock");
    std::fs::set_permissions(
        directory.path().join(LOCK_FILE),
        std::fs::Permissions::from_mode(0o600),
    )
    .expect("mode");
    assert_eq!(
        store.persist(&state),
        Err(ExactContextDeliveryError::ReopenRequired)
    );
    assert!(!directory.path().join(STATE_FILE).exists());
}

use super::*;
use crate::error::ShellError;
use crate::journal_storage::FileAccess;
use crate::journal_storage::open_private_file_in;
use crate::private_state::PrivateStateRoot;
use crate::update_storage::lock_update_root;
use crate::update_storage::lock_update_runner;

type Acquire = fn(&PrivateStateRoot) -> Result<UpdateLock, ShellError>;

fn owners() -> [(&'static str, Acquire); 2] {
    [
        ("update-owner.lock", lock_update_root),
        ("update-runner.lock", lock_update_runner),
    ]
}

fn assert_independent_owner_is_blocked(root: &PrivateStateRoot, name: &str) {
    let contender = open_private_file_in(
        root,
        &root.path().join(name),
        FileAccess::Lock,
        /*preexisting*/ true,
    )
    .unwrap();
    assert!(matches!(
        contender.try_lock(),
        Err(std::fs::TryLockError::WouldBlock)
    ));
}

#[test]
fn owner_and_runner_guards_hold_ownership_across_failed_acquisition() {
    for (name, acquire) in owners() {
        let directory = crate::private_state_test_support::private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let owner = acquire(&root).unwrap();
        assert_independent_owner_is_blocked(&root, name);
        assert!(matches!(acquire(&root), Err(ShellError::Update(_))));
        assert_independent_owner_is_blocked(&root, name);
        drop(owner);
        let successor = acquire(&root).unwrap();
        assert_independent_owner_is_blocked(&root, name);
        drop(successor);
        let released = acquire(&root).unwrap();
        drop(released);
    }
}

#[cfg(unix)]
#[test]
fn drop_releases_fork_equivalent_description_without_unlocking_successor() {
    for (name, acquire) in owners() {
        let directory = crate::private_state_test_support::private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let owner = acquire(&root).unwrap();
        // dup and fork retain the same open file description. Only this
        // private test can duplicate the production guard's descriptor.
        let inherited = owner.file.try_clone().unwrap();
        assert_independent_owner_is_blocked(&root, name);
        drop(owner);
        let successor = acquire(&root).unwrap();
        assert_independent_owner_is_blocked(&root, name);
        drop(inherited);
        assert_independent_owner_is_blocked(&root, name);
        drop(successor);
        let released = acquire(&root).unwrap();
        drop(released);
    }
}

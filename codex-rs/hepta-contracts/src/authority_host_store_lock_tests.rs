use super::*;

#[test]
fn a_live_guard_excludes_an_independently_opened_lock() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let guard = root.lock("publication.lock").unwrap();

    assert!(matches!(
        root.lock("publication.lock"),
        Err(AuthorityTrustError::Conflict)
    ));
    drop(guard);
    let reacquired = root.lock("publication.lock").unwrap();
    drop(reacquired);
}

#[test]
fn releasing_the_guard_unlocks_even_with_a_retained_open_description() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let guard = root.lock("publication.lock").unwrap();
    let retained = guard.file.try_clone().unwrap();

    assert!(matches!(
        root.lock("publication.lock"),
        Err(AuthorityTrustError::Conflict)
    ));
    drop(guard);
    let reacquired = root.lock("publication.lock").unwrap();
    // The old open description remains live across the single reacquisition.
    assert!(retained.metadata().unwrap().is_file());
    drop(retained);
    assert!(matches!(
        root.lock("publication.lock"),
        Err(AuthorityTrustError::Conflict)
    ));
    drop(reacquired);
}

#[test]
fn a_guard_with_a_different_owner_pid_does_not_unlock_the_retained_description() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let mut guard = root.lock("publication.lock").unwrap();
    let retained = guard.file.try_clone().unwrap();
    // Exercise the foreign-process destructor branch without unsafe fork code.
    // This simulates only the recorded PID mismatch, not an actual child process.
    guard.owner_pid = std::process::id().wrapping_add(1);
    drop(guard);

    assert!(matches!(
        root.lock("publication.lock"),
        Err(AuthorityTrustError::Conflict)
    ));
    drop(retained);
    let reacquired = root.lock("publication.lock").unwrap();
    drop(reacquired);
}

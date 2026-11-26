use super::*;

// A real child changes an observable file and subsequently reports failure.
// Treating that exit as terminal Failed would manufacture a negative outcome.
#[test]
fn launcher_failure_after_side_effect_stays_indeterminate() {
    let root = tempfile::TempDir::new().unwrap();
    let effect = root.path().join("effect.txt");
    let mut command = Command::new("sh");
    command
        .arg("-c")
        .arg("printf applied > \"$1\"; exit 7")
        .arg("native-launcher-test")
        .arg(&effect);
    let active = Arc::new(AtomicUsize::new(0));
    let status =
        run_bounded_launcher(command, "test effect", &active, Duration::from_secs(1)).unwrap();
    assert!(!status.success());
    assert_eq!(std::fs::read_to_string(effect).unwrap(), "applied");
    let adapter =
        SystemPlatformAdapter::new(PlatformPolicy::new(Vec::new(), false, false).unwrap());
    assert_eq!(
        adapter.launcher_observation(PlatformAction::OpenPath, status),
        PlatformObservation::indeterminate()
    );
    assert_eq!(active.load(Ordering::Acquire), 0);
}

#[test]
fn launcher_success_without_queryable_receipt_stays_indeterminate() {
    let mut command = Command::new("sh");
    command.args(["-c", "exit 0"]);
    let active = Arc::new(AtomicUsize::new(0));
    let status =
        run_bounded_launcher(command, "test launch", &active, Duration::from_secs(1)).unwrap();
    assert!(status.success());
    let adapter =
        SystemPlatformAdapter::new(PlatformPolicy::new(Vec::new(), false, false).unwrap());
    assert_eq!(
        adapter.launcher_observation(PlatformAction::Notify, status),
        PlatformObservation::indeterminate()
    );
}

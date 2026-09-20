use hepta_native::journal::OperationJournal;
use tempfile::TempDir;

#[test]
fn second_operation_journal_owner_is_rejected() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("operations.json");
    let first = OperationJournal::open(&path).unwrap();
    let error = OperationJournal::open(&path).unwrap_err();
    assert!(error.to_string().contains("already owned"));
    drop(first);
    OperationJournal::open(path).unwrap();
}

#[test]
fn killed_operation_journal_owner_releases_lock() {
    const CHILD_PATH: &str = "HEPTA_NATIVE_JOURNAL_CHILD_PATH";
    if let Some(path) = std::env::var_os(CHILD_PATH) {
        let path = std::path::PathBuf::from(path);
        let _journal = OperationJournal::open(&path).unwrap();
        std::fs::write(path.with_extension("ready"), b"ready").unwrap();
        loop {
            std::thread::park();
        }
    }

    let temp = TempDir::new().unwrap();
    let path = temp.path().join("operations.json");
    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "killed_operation_journal_owner_releases_lock", "--nocapture"])
        .env(CHILD_PATH, &path)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .unwrap();
    let ready = path.with_extension("ready");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while !ready.exists() && std::time::Instant::now() < deadline {
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    assert!(ready.exists(), "child never acquired operation journal lock");
    assert!(OperationJournal::open(&path).is_err());

    child.kill().unwrap();
    child.wait().unwrap();
    OperationJournal::open(path).unwrap();
}

#[cfg(unix)]
#[test]
fn group_or_world_readable_operation_journal_fails_closed() {
    use std::os::unix::fs::PermissionsExt as _;

    let temp = TempDir::new().unwrap();
    let path = temp.path().join("operations.json");
    std::fs::write(&path, br#"{"schema":"hepta.native-operation-journal.v2","operations":[]}"#)
        .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();

    let error = OperationJournal::open(&path).unwrap_err();
    assert!(error.to_string().contains("group/world"));
}

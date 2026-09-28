use std::fs::Permissions;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use super::*;

fn private_home() -> tempfile::TempDir {
    let home = tempfile::TempDir::new().expect("home");
    std::fs::set_permissions(home.path(), Permissions::from_mode(0o700)).expect("private home");
    home
}

#[test]
fn separate_opens_cannot_share_a_publisher_even_with_the_same_logical_owner() {
    let home = private_home();
    let first = PublicationProcessGuard::acquire(home.path()).expect("first publisher");
    let error = PublicationProcessGuard::acquire(home.path())
        .err()
        .expect("competing publisher must fail");
    assert_eq!(error.kind(), io::ErrorKind::WouldBlock);
    first.validate().expect("owner remains valid");
    drop(first);
    PublicationProcessGuard::acquire(home.path()).expect("successor after release");
}

#[test]
fn replacement_and_symlink_homes_do_not_preserve_the_fence() {
    let parent = private_home();
    let home = parent.path().join("home");
    std::fs::create_dir(&home).expect("home directory");
    std::fs::set_permissions(&home, Permissions::from_mode(0o700)).expect("private home");
    let guard = PublicationProcessGuard::acquire(&home).expect("publisher");
    let moved = parent.path().join("moved");
    std::fs::rename(&home, &moved).expect("replace home");
    std::os::unix::fs::symlink(&moved, &home).expect("symlink replacement");
    assert!(guard.validate().is_err());
    assert!(PublicationProcessGuard::acquire(&home).is_err());
}

#[test]
fn private_mode_is_rechecked_while_owned() {
    let home = private_home();
    let guard = PublicationProcessGuard::acquire(home.path()).expect("publisher");
    std::fs::set_permissions(home.path(), Permissions::from_mode(0o755)).expect("mode drift");
    assert!(guard.validate().is_err());
    assert!(PublicationProcessGuard::acquire(home.path()).is_err());
}

#[test]
fn publication_process_lock_child() {
    let Some(home) = std::env::var_os("HEPTA_EVIDENCE_LOCK_TEST_HOME") else {
        return;
    };
    let result_path = std::env::var_os("HEPTA_EVIDENCE_LOCK_TEST_RESULT")
        .expect("child result path");
    let expected = std::env::var("HEPTA_EVIDENCE_LOCK_TEST_EXPECTED")
        .expect("child expected disposition");
    let actual = match PublicationProcessGuard::acquire(Path::new(&home)) {
        Ok(guard) => {
            guard.validate().expect("child lock identity");
            "acquired"
        }
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => "blocked",
        Err(error) => panic!("unexpected child lock error: {error}"),
    };
    assert_eq!(actual, expected);
    std::fs::write(result_path, actual).expect("child observed disposition");
}

fn assert_child_disposition(home: &Path, expected: &str) {
    let result_path = home.join(format!("child-{expected}.txt"));
    let mut child = Command::new(std::env::current_exe().expect("test binary"))
        .arg("publication_process_lock_child")
        .arg("--nocapture")
        .env("HEPTA_EVIDENCE_LOCK_TEST_HOME", home)
        .env("HEPTA_EVIDENCE_LOCK_TEST_RESULT", &result_path)
        .env("HEPTA_EVIDENCE_LOCK_TEST_EXPECTED", expected)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("spawn independent publication process");
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        if let Some(status) = child.try_wait().expect("observe child") {
            assert!(status.success(), "child failed: {status}");
            break;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("publication lock child exceeded its deadline");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    // A zero-test subprocess must not look like a successful contention test.
    assert_eq!(std::fs::read_to_string(result_path).expect("child evidence"), expected);
}

#[test]
fn competing_process_is_blocked_and_successor_observes_os_lock_release() {
    let home = private_home();
    let owner = PublicationProcessGuard::acquire(home.path()).expect("parent publisher");
    assert_child_disposition(home.path(), "blocked");
    owner.validate().expect("parent still owns the fence");
    drop(owner);
    assert_child_disposition(home.path(), "acquired");
}

use super::*;
use std::io::Write;

const TEST_LIMIT: u64 = 4096;
const LABEL: &str = "effect operator file";

fn write_file(path: &Path, bytes: &[u8]) {
    fs::write(path, bytes).expect("operator file");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        fs::set_permissions(path, fs::Permissions::from_mode(0o600))
            .expect("private operator file");
    }
}

#[test]
fn valid_private_operator_file_at_exact_limit_is_read() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp
        .path()
        .canonicalize()
        .expect("canonical temp")
        .join("effect.json");
    let expected = vec![b' '; TEST_LIMIT as usize];
    write_file(&path, &expected);
    assert_eq!(
        read_protected_file(&path, TEST_LIMIT, LABEL).expect("read file"),
        expected
    );
}

#[test]
fn growth_after_open_is_bounded_and_rejected() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp
        .path()
        .canonicalize()
        .expect("canonical temp")
        .join("effect.json");
    write_file(&path, b"trusted");
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL).expect("validated file");
    fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .expect("append file")
        .write_all(&vec![b' '; TEST_LIMIT as usize])
        .expect("grow file");
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
}

#[cfg(unix)]
#[test]
fn writable_parent_is_rejected_even_for_a_private_regular_file() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp
        .path()
        .canonicalize()
        .expect("canonical temp")
        .join("effect.json");
    write_file(&path, b"trusted");
    for mode in [0o720, 0o702, 0o1777] {
        fs::set_permissions(temp.path(), fs::Permissions::from_mode(mode))
            .expect("writable parent");
        assert!(read_protected_file(&path, TEST_LIMIT, LABEL).is_err());
    }
}

#[cfg(unix)]
#[test]
fn writable_ancestor_is_rejected_above_a_private_parent() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical temp");
    let private = root.join("private");
    fs::create_dir(&private).expect("private parent");
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700)).expect("private parent");
    let path = private.join("effect.json");
    write_file(&path, b"trusted");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o777)).expect("writable ancestor");
    assert!(read_protected_file(&path, TEST_LIMIT, LABEL).is_err());
}

#[cfg(unix)]
#[test]
fn trusted_sticky_ancestor_accepts_a_private_parent() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical temp");
    let private = root.join("private");
    fs::create_dir(&private).expect("private parent");
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700)).expect("private parent");
    let path = private.join("effect.json");
    write_file(&path, b"trusted");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o1777)).expect("sticky ancestor");
    assert_eq!(
        read_protected_file(&path, TEST_LIMIT, LABEL).expect("read file"),
        b"trusted"
    );
}

#[cfg(unix)]
#[test]
fn namespace_permission_drift_is_rejected_after_open() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical temp");
    let path = root.join("effect.json");
    write_file(&path, b"trusted");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).expect("private parent");
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL).expect("validated file");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o755)).expect("change parent mode");
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
}

#[cfg(unix)]
#[test]
fn same_file_in_replaced_parent_is_rejected_after_open() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical temp");
    let parent = root.join("parent");
    let alternate = root.join("alternate");
    fs::create_dir(&parent).expect("parent");
    fs::create_dir(&alternate).expect("alternate");
    let path = parent.join("effect.json");
    write_file(&path, b"trusted");
    fs::hard_link(&path, alternate.join("effect.json")).expect("same file before read");
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL).expect("validated file");
    fs::rename(&parent, root.join("old")).expect("move parent");
    fs::rename(&alternate, &parent).expect("replace parent");
    assert!(same_file_version(
        &reader.metadata,
        &fs::metadata(&path).expect("same file")
    ));
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
}

#[cfg(unix)]
#[test]
fn final_component_symlink_is_rejected_before_and_after_open() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical temp");
    let path = root.join("effect.json");
    let retained = root.join("retained.json");
    write_file(&path, b"trusted");
    let reader = ProtectedEffectFile::open(&path, TEST_LIMIT, LABEL).expect("validated file");
    fs::rename(&path, &retained).expect("retain file");
    std::os::unix::fs::symlink(&retained, &path).expect("substitute symlink");
    assert!(reader.read(TEST_LIMIT, LABEL).is_err());
    assert!(read_protected_file(&path, TEST_LIMIT, LABEL).is_err());
}

#[cfg(unix)]
#[test]
fn inspected_effect_fifo_replacement_does_not_wait_for_a_writer() {
    use std::os::unix::fs::OpenOptionsExt;
    use std::process::Command;
    use std::sync::mpsc;
    use std::time::Duration;

    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp
        .path()
        .canonicalize()
        .expect("canonical temp")
        .join("effect.json");
    write_file(&path, b"trusted");
    let inspected =
        EffectFilePreflight::inspect(&path, TEST_LIMIT, LABEL).expect("regular preflight");
    fs::remove_file(&path).expect("replace inspected file");
    assert!(
        Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(&path)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
    let (done, received) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let _ = done.send(inspected.open(TEST_LIMIT, LABEL).is_err());
    });
    let first = received.recv_timeout(Duration::from_secs(/*secs*/ 1));
    let timely = first.is_ok();
    // Release a regressed blocking open before joining or asserting failure.
    let _cleanup = (!timely).then(|| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW)
            .open(&path)
            .expect("FIFO cleanup keeper")
    });
    let rejected = first.unwrap_or_else(|_| {
        received
            .recv_timeout(Duration::from_secs(/*secs*/ 1))
            .expect("FIFO cleanup releases worker")
    });
    worker.join().expect("open worker");
    assert!(timely, "replacement FIFO waited for a writer");
    assert!(rejected, "replacement FIFO was admitted as an effect file");
}

#[cfg(unix)]
#[test]
fn inspected_effect_symlink_replacement_is_rejected_by_the_open() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical temp");
    let path = root.join("effect.json");
    let retained = root.join("retained.json");
    write_file(&path, b"trusted");
    let inspected =
        EffectFilePreflight::inspect(&path, TEST_LIMIT, LABEL).expect("regular preflight");
    fs::rename(&path, &retained).expect("retain original inode");
    std::os::unix::fs::symlink(&retained, &path).expect("replacement final symlink");
    match inspected
        .open(TEST_LIMIT, LABEL)
        .err()
        .expect("reject replacement symlink")
    {
        AgentdError::Io(error) => assert_eq!(error.raw_os_error(), Some(libc::ELOOP)),
        error => panic!("expected the real no-follow open to reject the symlink: {error}"),
    }
}

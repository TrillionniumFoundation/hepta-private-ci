#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test fixtures fail immediately on invalid setup; production lints remain enforced"
)]

use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

fn fixture(bytes: &[u8]) -> (tempfile::TempDir, std::path::PathBuf) {
    let root = tempfile::tempdir().unwrap();
    let path = root
        .path()
        .canonicalize()
        .unwrap()
        .join("authority-input.json");
    fs::write(&path, bytes).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    (root, path)
}

#[test]
fn accepts_exact_bound_and_owner_atomic_replacement_between_reads() {
    let (_root, path) = fixture(b"first");
    assert_eq!(read_protected_file(&path, 5, "test").unwrap(), b"first");
    let next = path.with_extension("next");
    fs::write(&next, b"later").unwrap();
    fs::set_permissions(&next, fs::Permissions::from_mode(0o600)).unwrap();
    fs::rename(next, &path).unwrap();
    assert_eq!(read_protected_file(&path, 5, "test").unwrap(), b"later");
}

#[test]
fn rejects_empty_oversized_or_nonprivate_inputs() {
    for bytes in [b"".as_slice(), b"toolarge"] {
        let (_root, path) = fixture(bytes);
        assert!(read_protected_file(&path, 5, "test").is_err());
    }
    let (_root, path) = fixture(b"valid");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(read_protected_file(&path, 5, "test").is_err());
}

#[test]
fn rejects_symlink_and_hardlink_inputs() {
    let (_root, path) = fixture(b"valid");
    let alias = path.with_extension("alias");
    std::os::unix::fs::symlink(&path, &alias).unwrap();
    assert!(read_protected_file(&alias, 5, "test").is_err());
    fs::remove_file(&alias).unwrap();
    fs::hard_link(&path, &alias).unwrap();
    assert!(read_protected_file(&path, 5, "test").is_err());
}

#[test]
fn rejects_replacement_between_metadata_and_descriptor_open() {
    let (_root, path) = fixture(b"first");
    let before = fs::symlink_metadata(&path).unwrap();
    fs::remove_file(&path).unwrap();
    fs::write(&path, b"later").unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    assert!(read_opened_file(File::open(&path).unwrap(), &path, &before, 5, "test").is_err());
}

#[test]
fn rejects_path_replacement_after_descriptor_open() {
    let (_root, path) = fixture(b"first");
    let before = fs::symlink_metadata(&path).unwrap();
    let file = File::open(&path).unwrap();
    fs::remove_file(&path).unwrap();
    fs::write(&path, b"later").unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    assert!(read_opened_file(file, &path, &before, 5, "test").is_err());
}

#[test]
fn rejects_growth_and_same_length_rewrite_after_metadata_observation() {
    for next in [b"too long".as_slice(), b"later"] {
        let (_root, path) = fixture(b"first");
        let before = fs::symlink_metadata(&path).unwrap();
        let file = File::open(&path).unwrap();
        // Avoid depending on timestamp precision for the same-length case.
        std::thread::sleep(Duration::from_millis(10));
        fs::write(&path, next).unwrap();
        assert!(read_opened_file(file, &path, &before, 5, "test").is_err());
    }
}

#[test]
fn fifo_input_is_rejected_without_waiting_for_a_writer() {
    let root = tempfile::tempdir().unwrap();
    let path = root
        .path()
        .canonicalize()
        .unwrap()
        .join("authority-input.json");
    let directory = File::open(root.path()).unwrap();
    rustix::fs::mknodat(
        &directory,
        "authority-input.json",
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        sender
            .send(read_protected_file(&path, 5, "test").is_err())
            .unwrap();
        drop(root);
    });
    assert!(
        receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("FIFO open blocked")
    );
    worker.join().unwrap();
}

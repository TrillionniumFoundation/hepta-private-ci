use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::sync::mpsc;
use std::time::Duration;

use pretty_assertions::assert_eq;

use super::*;

fn fixture() -> (tempfile::TempDir, ControlRoot, PathBuf) {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp.path().canonicalize().expect("canonical root");
    let path = root.join("control.json");
    fs::write(&path, b"trusted").expect("control bytes");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("normal control mode");
    let control = ControlRoot::capture(&root).expect("trusted control root");
    (temp, control, path)
}

#[test]
fn readonly_and_hardlinked_control_files_preserve_native_publication_recovery() {
    let (_temp, control, path) = fixture();
    fs::hard_link(&path, path.with_extension("tmp")).expect("retained publication link");
    assert_eq!(control.read(&path, 7).expect("exact cap"), b"trusted");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o444)).expect("immutable control mode");
    assert_eq!(control.read(&path, 7).expect("immutable bytes"), b"trusted");
}

#[test]
fn control_file_rejects_unsafe_writes_and_growth_after_inspection() {
    let (_temp, control, path) = fixture();
    for mode in [0o620, 0o602, 0o666] {
        fs::set_permissions(&path, fs::Permissions::from_mode(mode)).expect("unsafe writes");
        assert!(control.read(&path, 7).is_err());
    }
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("restore control mode");
    let inspected = ControlFile::inspect(&control, &path, 7).expect("inspected control file");
    fs::write(&path, b"trusted-growth").expect("growth after inspection");
    assert!(inspected.read().is_err());
    assert!(control.read(&path, 7).is_err());
}

#[test]
fn final_symlink_replacement_is_rejected_by_the_native_open() {
    let (_temp, control, path) = fixture();
    let inspected = ControlFile::inspect(&control, &path, 7).expect("inspected control file");
    let retained = path.with_extension("retained");
    fs::rename(&path, &retained).expect("retain original inode");
    std::os::unix::fs::symlink(&retained, &path).expect("replace with symlink to same inode");
    assert!(inspected.read().is_err());
}

#[test]
fn final_fifo_replacement_never_waits_for_a_writer() {
    let (_temp, control, path) = fixture();
    let inspected = ControlFile::inspect(&control, &path, 7).expect("inspected control file");
    fs::remove_file(&path).expect("replace control file");
    assert!(
        Command::new("mkfifo")
            .arg(&path)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        sender
            .send(inspected.read())
            .expect("send guarded open result");
    });
    assert!(
        receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("FIFO open must not wait")
            .is_err()
    );
}

#[test]
fn file_replacement_with_equal_contents_and_parent_permission_drift_are_rejected() {
    let (_temp, control, path) = fixture();
    let inspected = ControlFile::inspect(&control, &path, 7).expect("inspected control file");
    let replacement = path.with_extension("replacement");
    fs::write(&replacement, b"trusted").expect("same-size replacement");
    fs::rename(replacement, &path).expect("different inode");
    assert!(inspected.read().is_err());
    let inspected = ControlFile::inspect(&control, &path, 7).expect("inspect replacement");
    fs::set_permissions(
        path.parent().expect("parent"),
        fs::Permissions::from_mode(0o777),
    )
    .expect("namespace drift");
    assert!(inspected.read().is_err());
}

#[test]
fn directory_entry_changes_preserve_the_namespace_identity() {
    let (_temp, control, path) = fixture();
    let guard = control
        .directory(path.parent().expect("parent"))
        .expect("directory guard");
    fs::create_dir(path.with_extension("subdirectory")).expect("new subdirectory changes nlink");
    guard
        .verify()
        .expect("directory content is allowed to evolve");
    assert_eq!(
        control.read(&path, 7).expect("existing control bytes"),
        b"trusted"
    );
}

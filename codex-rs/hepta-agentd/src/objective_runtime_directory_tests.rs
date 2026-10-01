use std::fs;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::Command;
use std::sync::mpsc;
use std::time::Duration;

use super::*;

fn fixture() -> (tempfile::TempDir, PathBuf, PathBuf, fs::Metadata) {
    let temp = tempfile::tempdir().expect("private owner fixture");
    let parent = temp.path().canonicalize().expect("canonical owner root");
    let path = parent.join("objective-directory");
    fs::create_dir(&path).expect("real objective directory");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).expect("original permissions");
    fs::write(path.join("retained-marker"), b"original directory contents")
        .expect("original marker");
    let metadata = fs::symlink_metadata(&path).expect("inspected real directory");
    assert!(metadata.is_dir() && !metadata.file_type().is_symlink());
    (temp, parent, path, metadata)
}

fn snapshot(path: &Path) -> (u64, u64, u32, u32, Vec<u8>) {
    let metadata = fs::symlink_metadata(path).expect("retained directory metadata");
    (
        metadata.dev(),
        metadata.ino(),
        metadata.uid(),
        metadata.mode(),
        fs::read(path.join("retained-marker")).expect("retained marker contents"),
    )
}

fn replace_with_fifo(path: &Path, retained: &Path) {
    fs::rename(path, retained).expect("retain inspected original directory");
    assert!(
        Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(path)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
}

fn rejects_fifo_without_waiting(
    fifo: &Path,
    operation: impl FnOnce() -> Result<(), AgentdError> + Send + 'static,
) {
    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        sender
            .send(operation().is_err())
            .expect("send bounded directory result");
    });
    let observed = receiver.recv_timeout(Duration::from_secs(/*secs*/ 2));
    if observed.is_err() {
        // Unblock a regressed ordinary read-open before retaining the original
        // timeout as failure. Cleanup must not turn that timeout into success.
        let keeper = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(fifo)
            .expect("release regressed FIFO reader");
        receiver
            .recv_timeout(Duration::from_secs(/*secs*/ 2))
            .expect("regressed directory worker exits after cleanup keeper");
        drop(keeper);
    }
    worker.join().expect("directory worker exits");
    assert!(observed.expect("directory open must not wait for a FIFO writer"));
}

#[test]
fn inspected_private_directory_fifo_replacement_is_rejected_before_chmod() {
    let (_temp, parent, path, metadata) = fixture();
    let before = snapshot(&path);
    let retained = parent.join("retained-directory");
    replace_with_fifo(&path, &retained);
    let fifo = path.clone();
    rejects_fifo_without_waiting(&fifo, move || {
        prepare_inspected_directory(&path, &parent, &metadata)
    });
    assert_eq!(snapshot(&retained), before);
}

#[test]
fn inspected_private_directory_symlink_replacement_is_rejected_before_chmod() {
    let (_temp, parent, path, metadata) = fixture();
    let before = snapshot(&path);
    let retained = parent.join("retained-directory");
    fs::rename(&path, &retained).expect("retain original inspected directory");
    std::os::unix::fs::symlink(&retained, &path)
        .expect("replace inspected leaf with same-inode link");
    assert!(prepare_inspected_directory(&path, &parent, &metadata).is_err());
    assert_eq!(snapshot(&retained), before);
    assert_eq!(
        fs::read_link(&path).expect("retained replacement link"),
        retained
    );
}

#[test]
fn run_start_directory_sync_rejects_fifo_without_waiting_for_a_writer() {
    let (_temp, parent, path, _metadata) = fixture();
    let before = snapshot(&path);
    let retained = parent.join("retained-directory");
    replace_with_fifo(&path, &retained);
    let fifo = path.clone();
    rejects_fifo_without_waiting(&fifo, move || sync_run_start_directory(&path));
    assert_eq!(snapshot(&retained), before);
}

#[test]
fn run_start_directory_sync_rejects_a_leaf_symlink_without_touching_its_target() {
    let (_temp, parent, path, _metadata) = fixture();
    let before = snapshot(&path);
    let retained = parent.join("retained-directory");
    fs::rename(&path, &retained).expect("retain original inspected directory");
    std::os::unix::fs::symlink(&retained, &path).expect("replace sync leaf with a symlink");
    assert!(sync_run_start_directory(&path).is_err());
    assert_eq!(snapshot(&retained), before);
    assert_eq!(
        fs::read_link(&path).expect("retained replacement link"),
        retained
    );
}

#[test]
fn real_private_directory_preparation_and_sync_preserve_owner_contents() {
    let (_temp, _parent, path, metadata) = fixture();
    prepare_private_directory(&path).expect("prepare actual directory");
    sync_run_start_directory(&path).expect("sync actual private directory");
    assert_eq!(
        snapshot(&path),
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            (metadata.mode() & !0o777) | 0o700,
            b"original directory contents".to_vec()
        )
    );
}

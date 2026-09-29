use super::Boundary;
use super::append_wal_frame;
use super::read_wal_frames;
use super::truncate_wal;
use super::wal_path;
use super::write;
use super::write_at_boundaries;
use crate::error::ShellError;

#[test]
fn every_snapshot_failure_boundary_leaves_an_entire_old_or_new_file() {
    let boundaries = [
        Boundary::Opened,
        Boundary::Written,
        Boundary::FileSynced,
        Boundary::Replaced,
        Boundary::DirectorySynced,
    ];
    for injected in boundaries {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("snapshot.json");
        write(&path, b"old committed snapshot").unwrap();
        let result = write_at_boundaries(&path, b"new committed snapshot", |boundary| {
            if boundary == injected {
                return Err(ShellError::Io(std::io::Error::other(
                    "injected persistence boundary failure",
                )));
            }
            Ok(())
        });
        assert!(result.is_err());
        let expected = match injected {
            Boundary::Opened | Boundary::Written | Boundary::FileSynced => {
                b"old committed snapshot"
            }
            Boundary::Replaced | Boundary::DirectorySynced => b"new committed snapshot",
        };
        assert_eq!(std::fs::read(&path).unwrap(), expected);
    }
}

#[test]
fn first_snapshot_failure_never_exposes_partially_written_bytes() {
    for injected in [Boundary::Opened, Boundary::Written, Boundary::FileSynced] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("snapshot.json");
        assert!(
            write_at_boundaries(&path, b"first snapshot", |boundary| {
                if boundary == injected {
                    return Err(ShellError::Io(std::io::Error::other("injected failure")));
                }
                Ok(())
            })
            .is_err()
        );
        assert!(!path.exists());
    }
}

#[test]
fn wal_discards_only_an_incomplete_final_frame() {
    let directory = tempfile::tempdir().unwrap();
    let snapshot = directory.path().join("journal.json");
    append_wal_frame(&snapshot, b"first", 4096, 1024).unwrap();
    append_wal_frame(&snapshot, b"second", 4096, 1024).unwrap();
    let valid = std::fs::metadata(wal_path(&snapshot)).unwrap().len();
    use std::io::Write as _;
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .open(wal_path(&snapshot))
        .unwrap();
    file.write_all(b"HPTNWAL1\0\0").unwrap();
    file.sync_all().unwrap();
    let frames = read_wal_frames(&snapshot, 4096, 1024).unwrap();
    assert_eq!(frames.frames, [b"first".to_vec(), b"second".to_vec()]);
    assert!(frames.partial_tail);
    assert_eq!(frames.valid_bytes, valid);
    assert!(frames.total_bytes > frames.valid_bytes);
    truncate_wal(&snapshot, frames.valid_bytes).unwrap();
    assert!(!read_wal_frames(&snapshot, 4096, 1024).unwrap().partial_tail);
}

#[test]
fn wal_rejects_a_complete_corrupt_frame() {
    let directory = tempfile::tempdir().unwrap();
    let snapshot = directory.path().join("journal.json");
    append_wal_frame(&snapshot, b"first", 4096, 1024).unwrap();
    let path = wal_path(&snapshot);
    let mut bytes = std::fs::read(&path).unwrap();
    *bytes.last_mut().unwrap() ^= 1;
    std::fs::write(&path, bytes).unwrap();
    assert!(read_wal_frames(&snapshot, 4096, 1024).is_err());
}

#[cfg(unix)]
#[test]
fn snapshot_and_wal_are_private_before_publication() {
    use std::os::unix::fs::PermissionsExt as _;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("snapshot.json");
    write(&path, b"private snapshot").unwrap();
    append_wal_frame(&path, b"private wal", 4096, 1024).unwrap();
    assert_eq!(
        std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o600
    );
    assert_eq!(
        std::fs::metadata(wal_path(&path))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}

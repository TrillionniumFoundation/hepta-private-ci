use super::Boundary;
use super::wal_path;
use crate::error::ShellError;
use crate::private_state::PrivateStateRoot;

use crate::private_state_test_support::private_tempdir;

fn write(path: &std::path::Path, bytes: &[u8]) -> Result<(), ShellError> {
    let root = PrivateStateRoot::open_existing(path.parent().unwrap())?;
    super::write_private(&root, path, bytes)
}

fn write_at_boundaries(
    path: &std::path::Path,
    bytes: &[u8],
    observe: impl FnMut(Boundary) -> Result<(), ShellError>,
) -> Result<(), ShellError> {
    let root = PrivateStateRoot::open_existing(path.parent().unwrap())?;
    super::write_at_boundaries(&root, path, bytes, observe)
}

fn append_wal_frame(
    snapshot: &std::path::Path,
    payload: &[u8],
    maximum_total: u64,
    maximum_frame: u64,
) -> Result<u64, ShellError> {
    let root = PrivateStateRoot::open_existing(snapshot.parent().unwrap())?;
    super::append_wal_frame(&root, snapshot, payload, maximum_total, maximum_frame)
}

fn read_wal_frames(
    snapshot: &std::path::Path,
    maximum_total: u64,
    maximum_frame: u64,
) -> Result<super::WalFrames, ShellError> {
    let root = PrivateStateRoot::open_existing(snapshot.parent().unwrap())?;
    super::read_wal_frames(&root, snapshot, maximum_total, maximum_frame)
}

fn truncate_wal(snapshot: &std::path::Path, length: u64) -> Result<(), ShellError> {
    let root = PrivateStateRoot::open_existing(snapshot.parent().unwrap())?;
    super::truncate_wal(&root, snapshot, length)
}

#[test]
fn every_snapshot_failure_boundary_leaves_an_entire_old_or_new_file() {
    let boundaries = [
        Boundary::ParentVerified,
        Boundary::Opened,
        Boundary::Written,
        Boundary::FileSynced,
        Boundary::Replaced,
        Boundary::DirectorySynced,
    ];
    for injected in boundaries {
        let directory = private_tempdir();
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
            Boundary::ParentVerified
            | Boundary::Opened
            | Boundary::Written
            | Boundary::FileSynced => b"old committed snapshot",
            Boundary::Replaced | Boundary::DirectorySynced => b"new committed snapshot",
        };
        assert_eq!(std::fs::read(&path).unwrap(), expected);
    }
}

#[test]
fn first_snapshot_failure_never_exposes_partially_written_bytes() {
    for injected in [
        Boundary::ParentVerified,
        Boundary::Opened,
        Boundary::Written,
        Boundary::FileSynced,
    ] {
        let directory = private_tempdir();
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
    let directory = private_tempdir();
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
    let directory = private_tempdir();
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
    let directory = private_tempdir();
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

#[cfg(unix)]
#[test]
fn wal_rejects_dangling_links_without_creating_their_targets() {
    let directory = private_tempdir();
    let snapshot = directory.path().join("snapshot.json");
    let target = directory.path().join("unrelated-state");
    std::os::unix::fs::symlink(&target, wal_path(&snapshot)).unwrap();

    assert!(append_wal_frame(&snapshot, b"private wal", 4096, 1024).is_err());
    assert!(read_wal_frames(&snapshot, 4096, 1024).is_err());
    assert!(truncate_wal(&snapshot, 0).is_err());
    assert!(!target.exists());
}

#[cfg(unix)]
#[test]
fn wal_rejects_links_without_mutating_their_targets() {
    use std::os::unix::fs::PermissionsExt as _;
    let directory = private_tempdir();
    let snapshot = directory.path().join("snapshot.json");
    let target = directory.path().join("unrelated-state");
    std::fs::write(&target, b"unrelated committed state").unwrap();
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::os::unix::fs::symlink(&target, wal_path(&snapshot)).unwrap();

    assert!(append_wal_frame(&snapshot, b"private wal", 4096, 1024).is_err());
    assert!(read_wal_frames(&snapshot, 4096, 1024).is_err());
    assert!(truncate_wal(&snapshot, 0).is_err());
    assert_eq!(
        std::fs::read(&target).unwrap(),
        b"unrelated committed state"
    );
}

#[cfg(unix)]
#[test]
fn snapshot_parent_replacement_cannot_redirect_committed_bytes() {
    for replacement_boundary in [Boundary::ParentVerified, Boundary::FileSynced] {
        let directory = private_tempdir();
        let path = directory.path().join("state");
        let root = PrivateStateRoot::open(&path).unwrap();
        let snapshot = path.join("snapshot.json");
        super::write_private(&root, &snapshot, b"old committed snapshot").unwrap();
        let original = directory.path().join("original-state");
        let result =
            super::write_at_boundaries(&root, &snapshot, b"new committed snapshot", |boundary| {
                if boundary == replacement_boundary {
                    std::fs::rename(&path, &original)?;
                    let _replacement = PrivateStateRoot::open(&path)?;
                    std::fs::write(&snapshot, b"unrelated replacement state")?;
                }
                Ok(())
            });

        assert!(result.is_err());
        assert_eq!(
            std::fs::read(&snapshot).unwrap(),
            b"unrelated replacement state"
        );
        let expected = match replacement_boundary {
            Boundary::ParentVerified => b"old committed snapshot",
            Boundary::FileSynced => b"new committed snapshot",
            Boundary::Opened
            | Boundary::Written
            | Boundary::Replaced
            | Boundary::DirectorySynced => unreachable!(),
        };
        assert_eq!(
            std::fs::read(original.join("snapshot.json")).unwrap(),
            expected
        );
    }
}

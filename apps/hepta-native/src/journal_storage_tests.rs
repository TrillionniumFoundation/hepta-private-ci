use super::Boundary;
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
            Boundary::Opened | Boundary::Written | Boundary::FileSynced => b"old committed snapshot",
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

#[cfg(unix)]
#[test]
fn snapshot_is_private_before_publication() {
    use std::os::unix::fs::PermissionsExt as _;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("snapshot.json");
    write(&path, b"private snapshot").unwrap();
    assert_eq!(
        std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

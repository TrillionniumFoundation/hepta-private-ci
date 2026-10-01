use std::io::Read;

use super::*;

fn fixture() -> (tempfile::TempDir, PathBuf) {
    let root = tempfile::tempdir().expect("private Browser artifact fixture");
    let path = root.path().join("worker");
    fs::write(&path, b"selected Browser artifact").expect("write artifact");
    (root, path)
}

#[test]
fn endlessly_growing_artifact_reader_stops_at_the_overflow_sentinel() {
    struct EndlessReader {
        consumed: usize,
    }
    impl Read for EndlessReader {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            buffer.fill(7);
            self.consumed += buffer.len();
            Ok(buffer.len())
        }
    }
    let mut reader = EndlessReader { consumed: 0 };
    let (_, count) = bounded_digest(&mut reader, /*maximum*/ 20_000).expect("bounded stream");
    assert_eq!((count, reader.consumed), (20_001, 20_001));
}

#[test]
fn exact_cap_artifact_returns_the_verified_canonical_path() {
    let (_root, path) = fixture();
    let bytes = fs::read(&path).expect("fixture bytes");
    let expected = Sha256::digest(&bytes).into();
    assert_eq!(
        verify_file_digest(&path, expected, bytes.len()).expect("selected artifact"),
        path.canonicalize().expect("canonical fixture")
    );
}

#[test]
fn artifact_growth_after_open_is_rejected() {
    let (_root, path) = fixture();
    let before = fs::read(&path).expect("fixture bytes");
    let snapshot = ArtifactSnapshot::open(&path, before.len()).expect("open snapshot");
    fs::write(&path, vec![3; before.len() * 100]).expect("grow artifact");
    assert!(
        snapshot
            .verify(Sha256::digest(&before).into(), before.len())
            .is_err()
    );
}

#[cfg(unix)]
#[test]
fn replacing_an_artifact_with_the_same_bytes_and_mtime_is_rejected() {
    let (root, path) = fixture();
    let bytes = fs::read(&path).expect("fixture bytes");
    let snapshot = ArtifactSnapshot::open(&path, bytes.len()).expect("open snapshot");
    let replacement = root.path().join("replacement");
    fs::write(&replacement, &bytes).expect("replacement bytes");
    File::open(&replacement)
        .expect("replacement handle")
        .set_times(fs::FileTimes::new().set_modified(snapshot.before.modified().expect("mtime")))
        .expect("matching mtime");
    fs::rename(replacement, &path).expect("replace selected path");
    assert!(
        snapshot
            .verify(Sha256::digest(&bytes).into(), bytes.len())
            .is_err()
    );
}

#[cfg(unix)]
#[test]
fn artifact_permission_drift_after_open_is_rejected() {
    use std::os::unix::fs::PermissionsExt;

    let (_root, path) = fixture();
    let bytes = fs::read(&path).expect("fixture bytes");
    let snapshot = ArtifactSnapshot::open(&path, bytes.len()).expect("open snapshot");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o666)).expect("permission drift");
    assert!(
        snapshot
            .verify(Sha256::digest(&bytes).into(), bytes.len())
            .is_err()
    );
}

#[cfg(unix)]
#[test]
fn writable_artifact_parent_is_rejected_before_open() {
    use std::os::unix::fs::PermissionsExt;

    let (root, path) = fixture();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o777)).expect("unsafe parent");
    assert!(ArtifactSnapshot::open(&path, /*maximum*/ 4096).is_err());
}

#[cfg(unix)]
#[test]
fn private_artifact_parent_under_a_writable_nonsticky_ancestor_is_rejected() {
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("ancestor fixture");
    let private = root.path().join("private");
    fs::create_dir(&private).expect("private artifact parent");
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700)).expect("private mode");
    let path = private.join("worker");
    fs::write(&path, b"selected Browser artifact").expect("artifact");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(ArtifactSnapshot::open(&path, /*maximum*/ 4096).is_err());
}

#[cfg(unix)]
#[test]
fn replacing_the_parent_while_preserving_the_artifact_inode_is_rejected() {
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("parent replacement fixture");
    let private = root.path().join("private");
    fs::create_dir(&private).expect("artifact parent");
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700)).expect("private mode");
    let path = private.join("worker");
    let bytes = b"selected Browser artifact";
    fs::write(&path, bytes).expect("artifact");
    let snapshot = ArtifactSnapshot::open(&path, bytes.len()).expect("open snapshot");
    let parked = root.path().join("parked");
    fs::rename(&private, &parked).expect("park parent");
    fs::create_dir(&private).expect("new parent inode");
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700)).expect("new private mode");
    fs::rename(parked.join("worker"), &path).expect("preserve file inode");
    assert!(
        snapshot
            .verify(Sha256::digest(bytes).into(), bytes.len())
            .is_err()
    );
}

#[cfg(unix)]
#[test]
fn stable_directory_alias_returns_the_physical_execution_path() {
    use std::os::unix::fs::symlink;

    let (root, path) = fixture();
    let alias_root = tempfile::tempdir().expect("alias fixture");
    let alias = alias_root.path().join("artifacts");
    symlink(root.path(), &alias).expect("stable directory alias");
    let bytes = fs::read(&path).expect("fixture bytes");
    assert_eq!(
        verify_file_digest(
            &alias.join("worker"),
            Sha256::digest(&bytes).into(),
            bytes.len()
        )
        .expect("verify stable alias"),
        path.canonicalize().expect("physical artifact")
    );
}

#[cfg(unix)]
#[test]
fn a_final_component_symlink_remains_rejected() {
    use std::os::unix::fs::symlink;

    let (root, path) = fixture();
    let alias = root.path().join("worker-alias");
    symlink(&path, &alias).expect("artifact symlink");
    assert!(ArtifactSnapshot::open(&alias, /*maximum*/ 4096).is_err());
}

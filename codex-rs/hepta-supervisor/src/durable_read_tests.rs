use super::*;
use pretty_assertions::assert_eq;

fn write_fixture(path: &Path, bytes: &[u8]) {
    std::fs::write(path, bytes).expect("state");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).expect("mode");
    }
}

#[test]
fn bounded_reader_accepts_stable_bytes_and_rejects_invalid_bounds() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("state");
    assert_eq!(read_regular_bounded(&path, 3).expect("missing"), None);
    write_fixture(&path, b"abc");
    assert_eq!(
        read_regular_bounded(&path, 3).expect("read"),
        Some(b"abc".to_vec())
    );
    assert_eq!(
        read_regular_bounded(&path, 2)
            .expect_err("oversized")
            .kind(),
        io::ErrorKind::InvalidData
    );
    assert_eq!(
        read_regular_bounded(&path, usize::MAX)
            .expect_err("overflow")
            .kind(),
        io::ErrorKind::InvalidInput
    );
}

#[cfg(unix)]
#[test]
fn equal_byte_inode_substitution_is_rejected_at_each_boundary() {
    for point in [
        ReadBoundary::BeforeOpen,
        ReadBoundary::BeforeRead,
        ReadBoundary::AfterRead,
    ] {
        let dir = tempfile::tempdir().expect("directory");
        let path = dir.path().join("state");
        let replacement = dir.path().join("replacement");
        write_fixture(&path, b"same");
        write_fixture(&replacement, b"same");
        let mut injected = false;
        let result = read_regular_bounded_at(&path, 4, |stage, path| {
            if stage == point {
                injected = true;
                std::fs::rename(&replacement, path).expect("substitute identity");
            }
        });
        assert!(injected, "reader reached the substitution boundary");
        assert_eq!(
            result.expect_err("different identity").kind(),
            io::ErrorKind::InvalidData
        );
    }
}

#[cfg(unix)]
#[test]
fn symlink_substitution_does_not_follow_the_external_target() {
    use std::os::unix::fs::symlink;

    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("state");
    let outside = tempfile::NamedTempFile::new().expect("outside");
    write_fixture(&path, b"old");
    std::fs::write(outside.path(), b"outside").expect("target");
    let mut injected = false;
    let result = read_regular_bounded_at(&path, 3, |stage, path| {
        if stage == ReadBoundary::BeforeOpen {
            injected = true;
            std::fs::remove_file(path).expect("unlink");
            symlink(outside.path(), path).expect("symlink");
        }
    });
    assert!(injected, "reader reached the symlink substitution boundary");
    assert_eq!(
        result.expect_err("nofollow").kind(),
        io::ErrorKind::InvalidData
    );
    assert_eq!(
        std::fs::read(outside.path()).expect("target unchanged"),
        b"outside"
    );
}

#[cfg(unix)]
#[test]
fn fifo_substitution_is_rejected_without_a_writer_or_read() {
    use std::os::unix::ffi::OsStrExt;

    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("state");
    write_fixture(&path, b"old");
    let mut injected = false;
    let result = read_regular_bounded_at(&path, 3, |stage, path| {
        if stage == ReadBoundary::BeforeOpen {
            injected = true;
            std::fs::remove_file(path).expect("unlink");
            let name = std::ffi::CString::new(path.as_os_str().as_bytes()).expect("path");
            // SAFETY: name is a valid NUL-terminated path and remains alive for the call.
            assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
        }
    });
    assert!(injected, "reader reached the FIFO substitution boundary");
    assert_eq!(
        result.expect_err("regular-file check").kind(),
        io::ErrorKind::InvalidData
    );
}

#[test]
fn growth_and_post_read_content_changes_are_rejected() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("state");
    for point in [ReadBoundary::BeforeRead, ReadBoundary::AfterRead] {
        write_fixture(&path, b"old");
        let mut injected = false;
        let result = read_regular_bounded_at(&path, 3, |stage, path| {
            if stage == point {
                injected = true;
                std::fs::write(path, b"changed-and-too-large").expect("change state");
            }
        });
        assert!(injected, "reader reached the content change boundary");
        assert_eq!(
            result.expect_err("changing file").kind(),
            io::ErrorKind::InvalidData
        );
    }
}

#[cfg(unix)]
#[test]
fn same_length_post_read_replacement_and_permission_changes_are_rejected() {
    use std::os::unix::fs::PermissionsExt;

    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("state");
    write_fixture(&path, b"old");
    let mut injected = false;
    let result = read_regular_bounded_at(&path, 3, |stage, path| {
        if stage == ReadBoundary::AfterRead {
            injected = true;
            std::fs::write(path, b"new").expect("same-length change");
        }
    });
    assert!(injected, "reader reached the same-length change boundary");
    assert_eq!(
        result.expect_err("changed content").kind(),
        io::ErrorKind::InvalidData
    );
    let mut injected = false;
    let result = read_regular_bounded_at(&path, 3, |stage, path| {
        if stage == ReadBoundary::AfterRead {
            injected = true;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o666)).expect("mode");
        }
    });
    assert!(injected, "reader reached the permission change boundary");
    assert_eq!(
        result.expect_err("changed mode").kind(),
        io::ErrorKind::InvalidData
    );
}

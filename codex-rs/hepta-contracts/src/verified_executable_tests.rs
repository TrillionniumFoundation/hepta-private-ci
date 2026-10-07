use super::*;
use std::time::Duration;

#[cfg(target_os = "linux")]
#[test]
fn sealed_image_survives_atomic_path_replacement_and_same_inode_mutation() {
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let path = root.join("program");
    let original = b"#!/bin/sh\nprintf original\n";
    fs::write(&path, original).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
    let expected = Sha256Digest::for_bytes(original);
    let image = VerifiedExecutableImage::open(
        &path, &expected, 1024, Instant::now() + Duration::from_secs(2),
    ).unwrap();
    fs::write(&path, b"#!/bin/sh\nprintf mutated\n").unwrap();
    let moved = root.join("old");
    fs::rename(&path, moved).unwrap();
    fs::write(&path, b"#!/bin/sh\nprintf replaced\n").unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
    let result = image.command().output().unwrap();
    assert!(result.status.success());
    assert_eq!(result.stdout, b"original");
    assert!(VerifiedExecutableImage::open(
        &path, &expected, 1024, Instant::now() + Duration::from_secs(2),
    ).is_err());
    let writable = fs::OpenOptions::new().write(true)
        .open(format!("/proc/{}/fd/{}", std::process::id(), {
            use std::os::fd::AsRawFd;
            image.file.as_raw_fd()
        })).unwrap();
    use std::os::unix::fs::FileExt;
    assert!(writable.write_at(b"x", 0).is_err());
    assert!(writable.set_len(1).is_err());
}

#[cfg(target_os = "linux")]
#[test]
fn image_rejects_symlink_size_digest_deadline_and_nonregular_input() {
    use std::fs;
    use std::os::unix::fs::{PermissionsExt, symlink};
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let path = root.join("program");
    fs::write(&path, b"#!/bin/sh\nexit 0\n").unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
    let digest = Sha256Digest::for_bytes(&fs::read(&path).unwrap());
    for (input, expected, limit, deadline) in [
        (path.clone(), digest.clone(), 1, Instant::now() + Duration::from_secs(2)),
        (path.clone(), Sha256Digest::for_bytes(b"other"), 1024, Instant::now() + Duration::from_secs(2)),
        (path.clone(), digest.clone(), 1024, Instant::now()),
        (root.clone(), digest.clone(), 1024, Instant::now() + Duration::from_secs(2)),
    ] {
        assert!(VerifiedExecutableImage::open(&input, &expected, limit, deadline).is_err());
    }
    let alias = root.join("alias");
    symlink(&path, &alias).unwrap();
    assert!(VerifiedExecutableImage::open(
        &alias, &digest, 1024, Instant::now() + Duration::from_secs(2),
    ).is_err());
    let fifo = root.join("fifo");
    rustix::fs::mknodat(rustix::fs::CWD, &fifo, rustix::fs::FileType::Fifo,
                       rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR, 0).unwrap();
    assert!(VerifiedExecutableImage::open(
        &fifo, &digest, 1024, Instant::now() + Duration::from_secs(2),
    ).is_err());
}

#[cfg(not(target_os = "linux"))]
#[test]
fn unsupported_platform_has_no_mutable_executable_fallback() {
    let result = VerifiedExecutableImage::open(
        Path::new("/unsupported"), &Sha256Digest::for_bytes(b"x"), 1024,
        Instant::now() + Duration::from_secs(1),
    );
    assert_eq!(result.unwrap_err().kind(), io::ErrorKind::Unsupported);
}

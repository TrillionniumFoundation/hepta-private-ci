use std::fs::File;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::load_public_key;

#[test]
fn public_key_accepts_raw_and_bounded_hex_without_rewriting_the_file() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("authority.pub");
    for bytes in [
        vec![0xab; 32],
        format!("{}\n", "ab".repeat(32)).into_bytes(),
    ] {
        std::fs::write(&path, &bytes).expect("key");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).expect("mode");
        assert_eq!(
            load_public_key(path.clone(), "test key").expect("key"),
            [0xab; 32]
        );
        assert_eq!(std::fs::read(&path).expect("unchanged bytes"), bytes);
        assert_eq!(
            std::fs::metadata(&path)
                .expect("metadata")
                .permissions()
                .mode()
                & 0o777,
            0o644
        );
    }
}

#[test]
fn public_key_rejects_relative_path_before_filesystem_access() {
    assert!(load_public_key("authority.pub".into(), "test key").is_err());
}

#[test]
fn public_key_rejects_sparse_oversize_without_unbounded_allocation() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("oversize.pub");
    File::create(&path)
        .expect("sparse key")
        .set_len(64 * 1024 * 1024)
        .expect("sparse size");
    let error = load_public_key(path, "test key").expect_err("reject oversized key");
    assert!(error.to_string().contains("exceeds key byte limit"));
}

#[test]
fn public_key_rejects_links_and_writable_authority_material() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("authority.pub");
    let link = temp.path().join("symlink.pub");
    let hardlink = temp.path().join("hardlink.pub");
    std::fs::write(&path, [0xab; 32]).expect("key");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666)).expect("mode");
    assert!(load_public_key(path.clone(), "test key").is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).expect("mode");
    std::os::unix::fs::symlink(&path, &link).expect("symlink");
    assert!(load_public_key(link, "test key").is_err());
    std::fs::hard_link(&path, &hardlink).expect("hardlink");
    assert!(load_public_key(hardlink, "test key").is_err());
    assert_eq!(std::fs::read(path).expect("original key"), [0xab; 32]);
}

#[test]
fn public_key_rejects_fifo_without_waiting_for_a_writer() {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("key.fifo");
    let c_path = CString::new(path.as_os_str().as_bytes()).expect("path");
    // SAFETY: c_path is a live, NUL-terminated pathname; mode is a fixed constant.
    assert_eq!(unsafe { libc::mkfifo(c_path.as_ptr(), 0o600) }, 0);
    assert!(load_public_key(path, "test key").is_err());
}

#[test]
fn public_key_rejects_malformed_hex_and_wrong_lengths() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("authority.pub");
    for bytes in [vec![0xab; 31], vec![0xff; 64], vec![b'g'; 64], Vec::new()] {
        std::fs::write(&path, bytes).expect("invalid key");
        assert!(load_public_key(path.clone(), "test key").is_err());
    }
}

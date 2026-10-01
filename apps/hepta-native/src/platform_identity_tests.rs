use super::registered_notification_identity;

#[test]
fn notification_marker_requires_a_bounded_valid_identity() {
    let directory = tempfile::tempdir().unwrap();
    let marker = directory.path().join("aumid.txt");
    for bytes in [
        b"Trillionnium.Hepta.Native\n".as_slice(),
        b"Trillionnium.Hepta.Native\r\n".as_slice(),
    ] {
        std::fs::write(&marker, bytes).unwrap();
        assert!(registered_notification_identity(&marker));
    }
    for bytes in [
        b"another.identity".as_slice(),
        b"Trillionnium.Hepta.Native\nextra".as_slice(),
        &[255],
        &vec![b' '; 129],
    ] {
        std::fs::write(&marker, bytes).unwrap();
        assert!(!registered_notification_identity(&marker));
    }
    assert!(!registered_notification_identity(directory.path()));
    assert!(!registered_notification_identity(
        &directory.path().join("missing")
    ));
}

#[cfg(unix)]
#[test]
fn notification_marker_rejects_a_final_symlink() {
    let directory = tempfile::tempdir().unwrap();
    let target = directory.path().join("target.txt");
    let marker = directory.path().join("aumid.txt");
    std::fs::write(&target, b"Trillionnium.Hepta.Native\n").unwrap();
    std::os::unix::fs::symlink(&target, &marker).unwrap();
    assert!(!registered_notification_identity(&marker));
}

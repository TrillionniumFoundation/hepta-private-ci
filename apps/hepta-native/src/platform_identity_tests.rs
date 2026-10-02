use super::WINDOWS_AUMID;
use super::register_notification_identity_at;
use super::registered_notification_identity;
use crate::error::ShellError;

#[test]
fn registration_removes_stale_marker_before_native_call_and_keeps_failure_unregistered() {
    let directory = tempfile::tempdir().unwrap();
    let marker = directory.path().join("aumid.txt");
    std::fs::write(&marker, WINDOWS_AUMID).unwrap();

    let result = register_notification_identity_at(&marker, || {
        assert!(!marker.exists());
        Err(ShellError::Platform("persisted shortcut mismatch".into()))
    });

    assert!(
        matches!(result, Err(ShellError::Platform(message)) if message == "persisted shortcut mismatch")
    );
    assert!(!marker.exists());
}

#[test]
fn registration_publishes_exact_marker_only_after_native_readback_success() {
    let directory = tempfile::tempdir().unwrap();
    let marker = directory.path().join("identity/aumid.txt");
    let shortcut = directory.path().join("Hepta Native.lnk");
    let observed = register_notification_identity_at(&marker, || {
        assert!(!marker.exists());
        Ok(shortcut.clone())
    })
    .unwrap();

    assert_eq!(
        (observed, std::fs::read(&marker).unwrap()),
        (shortcut, format!("{WINDOWS_AUMID}\n").into_bytes())
    );
    assert!(registered_notification_identity(&marker));
}

#[test]
fn registration_does_not_invoke_native_adapter_when_stale_marker_cannot_be_removed() {
    let directory = tempfile::tempdir().unwrap();
    let marker = directory.path().join("aumid.txt");
    std::fs::create_dir(&marker).unwrap();
    std::fs::write(marker.join("owned.txt"), b"preserve").unwrap();

    assert!(
        register_notification_identity_at(&marker, || {
            panic!("registration must stop before changing the native shortcut")
        })
        .is_err()
    );
    assert_eq!(
        std::fs::read(marker.join("owned.txt")).unwrap(),
        b"preserve"
    );
}

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
        &[b' '; 129],
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

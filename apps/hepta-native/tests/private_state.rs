mod common;

use common::private_tempdir;
use hepta_native::private_state::PrivateStateRoot;

#[test]
fn private_state_root_requires_an_absolute_path() {
    let error = PrivateStateRoot::open("relative-native-state").unwrap_err();
    assert!(error.to_string().contains("must be absolute"));
}

#[test]
fn private_state_root_rejects_missing_existing_state() {
    let root = private_tempdir();
    let error = PrivateStateRoot::open_existing(root.path().join("missing")).unwrap_err();
    assert!(error.to_string().contains("private-state root"));
}

#[cfg(unix)]
#[test]
fn private_state_root_is_mode_0700_and_rejects_permission_drift() {
    use std::os::unix::fs::PermissionsExt as _;

    let root = private_tempdir();
    let path = root.path().join("native-state");
    let state = PrivateStateRoot::open(&path).unwrap();
    assert_eq!(
        std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o700
    );
    state.verify().unwrap();

    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
    assert!(state.verify().is_err());
}

#[cfg(unix)]
#[test]
fn private_state_root_rejects_a_symlink() {
    use std::os::unix::fs::PermissionsExt as _;
    use std::os::unix::fs::symlink;

    let root = private_tempdir();
    let target = root.path().join("target");
    std::fs::create_dir(&target).unwrap();
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o700)).unwrap();
    let redirected = root.path().join("redirected");
    symlink(&target, &redirected).unwrap();
    assert!(PrivateStateRoot::open_existing(redirected).is_err());
}

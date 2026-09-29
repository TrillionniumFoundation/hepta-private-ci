use super::*;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;

#[test]
fn vault_uid_socket_and_parent_permissions_fail_closed() {
    let paths = tempfile::tempdir().unwrap();
    std::fs::set_permissions(paths.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let socket = paths.path().join("vault.sock");
    let _listener = UnixListener::bind(&socket).unwrap();
    let uid = rustix::process::geteuid().as_raw();
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600)).unwrap();
    validate_vault_socket(&socket, uid).unwrap();
    validate_vault_peer_uid(uid, uid).unwrap();
    assert!(validate_vault_peer_uid(uid, uid.wrapping_add(1)).is_err());
    assert!(validate_vault_socket(&socket, uid.wrapping_add(1)).is_err());
    let alias = paths.path().join("alias.sock");
    std::os::unix::fs::symlink(&socket, &alias).unwrap();
    assert!(validate_vault_socket(&alias, uid).is_err());
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o606)).unwrap();
    assert!(validate_vault_socket(&socket, uid).is_err());
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::fs::set_permissions(paths.path(), std::fs::Permissions::from_mode(0o777)).unwrap();
    assert!(validate_vault_socket(&socket, uid).is_err());
    std::fs::set_permissions(paths.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
}

#[test]
fn vault_config_rejects_symlinks_hardlinks_and_oversize_files() {
    let paths = tempfile::tempdir().unwrap();
    let config = paths.path().join("config.json");
    std::fs::write(&config, b"{}").unwrap();
    std::fs::set_permissions(&config, std::fs::Permissions::from_mode(0o600)).unwrap();
    assert_eq!(read_private_config(&config).unwrap(), b"{}");
    let alias = paths.path().join("alias.json");
    std::os::unix::fs::symlink(&config, &alias).unwrap();
    assert!(read_private_config(&alias).is_err());
    let hardlink = paths.path().join("hardlink.json");
    std::fs::hard_link(&config, &hardlink).unwrap();
    assert!(read_private_config(&config).is_err());
    std::fs::remove_file(hardlink).unwrap();
    std::fs::write(&config, vec![0u8; MAX_CONFIG_BYTES + 1]).unwrap();
    assert!(read_private_config(&config).is_err());
}

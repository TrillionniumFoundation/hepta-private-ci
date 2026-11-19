use super::*;
use pretty_assertions::assert_eq;

#[test]
fn actual_login_retry_preserves_existing_versioned_users_and_marker() {
    let home = tempfile::tempdir().unwrap();
    let marker = setup_marker_path(home.path());
    let users = sandbox_users_path(home.path());
    for path in [&marker, &users] {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, b"existing-valid-or-uncertain-history").unwrap();
    }
    let before = (fs::read(&marker).unwrap(), fs::read(&users).unwrap());
    let permissions = ResolvedWindowsSandboxPermissions::try_from_permission_profile(
        &codex_protocol::models::PermissionProfile::read_only(),
    )
    .unwrap();
    assert!(
        refresh_logon_sandbox_creds(
            &permissions,
            home.path(),
            &HashMap::new(),
            home.path(),
            /*read_roots_override*/ None,
            /*read_roots_include_platform_defaults*/ false,
            /*write_roots_override*/ None,
            &[],
            &[],
            /*proxy_enforced*/ false,
            crate::WindowsSandboxProxySettingsMode::Preserve
        )
        .is_err()
    );
    assert_eq!(
        (fs::read(marker).unwrap(), fs::read(users).unwrap()),
        before
    );
}

#[test]
fn early_identity_readers_reject_excess_state_without_replacement() {
    let home = tempfile::tempdir().unwrap();
    let bytes = vec![b' '; 4 * 1024 * 1024 + 1];
    for path in [
        setup_marker_path(home.path()),
        sandbox_users_path(home.path()),
    ] {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, &bytes).unwrap();
        assert!(read_state_record(&path).is_err());
        if path == setup_marker_path(home.path()) {
            assert!(load_marker(home.path()).is_err());
        } else {
            assert!(load_users(home.path()).is_err());
        }
        assert!(!sandbox_setup_is_complete(home.path()));
        assert_eq!(fs::read(path).unwrap(), bytes);
    }
}

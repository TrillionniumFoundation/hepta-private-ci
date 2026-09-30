use std::ffi::OsString;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_supervisor::ProductionAuthorityBundle;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::parse_options_from;

fn absolute_fleet(temp: &tempfile::TempDir) -> OsString {
    temp.path().join("fleet").into_os_string()
}

#[expect(
    clippy::expect_used,
    reason = "A valid deterministic authority bundle must be created before CLI admission is tested."
)]
fn authority_bundle(temp: &tempfile::TempDir) -> (OsString, OsString, Vec<u8>) {
    let grant = SigningKey::from_bytes(&[3; 32]);
    let h7 = SigningKey::from_bytes(&[7; 32]);
    let bundle = ProductionAuthorityBundle::new(
        "release-policy",
        4,
        grant.verifying_key(),
        "h7-policy",
        9,
        h7.verifying_key(),
    )
    .expect("bundle");
    let bytes = bundle.to_json_bytes().expect("bundle JSON");
    let path = temp.path().join("authority-bundle.json");
    std::fs::write(&path, &bytes).expect("write bundle");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("bundle mode");
    (
        path.into_os_string(),
        OsString::from(bundle.bundle_sha256.as_str()),
        bytes,
    )
}

#[test]
fn lifecycle_only_options_require_exact_absolute_fleet_root() {
    let temp = tempfile::tempdir().expect("directory");
    let options = parse_options_from([OsString::from("--fleet-root"), absolute_fleet(&temp)])
        .expect("lifecycle-only options");
    assert_eq!(options.fleet_root.as_path(), temp.path().join("fleet"));
    assert!(options.grant_verifier.is_none());
}

#[test]
fn pinned_bundle_options_load_verifier_without_mutating_material() {
    let temp = tempfile::tempdir().expect("directory");
    let (path, digest, bytes) = authority_bundle(&temp);
    let options = parse_options_from([
        OsString::from("--fleet-root"),
        absolute_fleet(&temp),
        OsString::from("--authority-bundle"),
        path.clone(),
        OsString::from("--authority-bundle-sha256"),
        digest,
    ])
    .expect("pinned verifier options");
    assert!(options.grant_verifier.is_some());
    assert_eq!(std::fs::read(path).expect("unchanged bundle"), bytes);
}

#[test]
fn legacy_six_field_verifier_tuple_is_rejected() {
    let temp = tempfile::tempdir().expect("directory");
    let error = parse_options_from([
        OsString::from("--fleet-root"),
        absolute_fleet(&temp),
        OsString::from("--grant-verifier-key"),
        temp.path().join("legacy.pub").into_os_string(),
    ])
    .err()
    .expect("legacy flag rejected");
    assert!(error.to_string().contains("usage: hepta-supervisord"));
    assert!(!temp.path().join("legacy.pub").exists());
}

#[test]
fn authority_bundle_and_digest_are_an_atomic_pair() {
    let temp = tempfile::tempdir().expect("directory");
    let (path, digest, _) = authority_bundle(&temp);
    for arguments in [
        vec![
            OsString::from("--fleet-root"),
            absolute_fleet(&temp),
            OsString::from("--authority-bundle"),
            path,
        ],
        vec![
            OsString::from("--fleet-root"),
            absolute_fleet(&temp),
            OsString::from("--authority-bundle-sha256"),
            digest,
        ],
    ] {
        let error = parse_options_from(arguments)
            .err()
            .expect("incomplete bundle pair rejected");
        assert!(error.to_string().contains("must be supplied together"));
    }
}

#[test]
fn duplicate_and_unknown_flags_are_rejected() {
    let temp = tempfile::tempdir().expect("directory");
    for arguments in [
        vec![
            OsString::from("--fleet-root"),
            absolute_fleet(&temp),
            OsString::from("--fleet-root"),
            absolute_fleet(&temp),
        ],
        vec![
            OsString::from("--fleet-root"),
            absolute_fleet(&temp),
            OsString::from("--program"),
            OsString::from("/tmp/agentd"),
        ],
    ] {
        assert!(parse_options_from(arguments).is_err());
    }
}

#[test]
fn relative_fleet_root_is_rejected_before_daemon_start() {
    let error = parse_options_from([
        OsString::from("--fleet-root"),
        OsString::from("relative/fleet"),
    ])
    .err()
    .expect("relative fleet rejected");
    assert!(error.to_string().contains("absolute"));
}

mod common;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use common::private_tempdir;
use ed25519_dalek::{Signer as _, SigningKey};
use hepta_native::model::sha256_hex;
use hepta_native::security::{TrustedKeySet, now_unix_ms};
use hepta_native::updater::{
    PendingUpdateStatus, SignedUpdateManifestV1, UpdateManager, activate_staged_update, digest_file,
};
use sha2::Digest as _;
use std::path::Path;
fn test_material(label: &str) -> [u8; 32] {
    sha2::Sha256::digest(label.as_bytes()).into()
}

fn test_signing_key(label: &str) -> SigningKey {
    SigningKey::from_bytes(&test_material(label))
}

fn key_fixture(root: &Path) -> (SigningKey, TrustedKeySet, std::path::PathBuf) {
    let signing = test_signing_key("release-key-fixture");
    let public = STANDARD.encode(signing.verifying_key().to_bytes());
    let path = root.join("trusted-keys.json");
    std::fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"release.key": public}
        }))
        .unwrap(),
    )
    .unwrap();
    let keys = TrustedKeySet::from_path(&path).unwrap();
    (signing, keys, path)
}

fn signed_update_manifest(
    signing: &SigningKey,
    package: &Path,
    target: &Path,
    evidence_label: &[u8],
) -> SignedUpdateManifestV1 {
    let now = now_unix_ms().unwrap();
    let mut manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(package).unwrap(),
        predecessor_digest: digest_file(target).unwrap(),
        evidence_digest: sha256_hex(evidence_label),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "stable".to_owned(),
        selected_by: "release.reviewer".to_owned(),
        generator_principal: "release.builder".to_owned(),
        issued_unix_ms: now.saturating_sub(1_000),
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        signature_base64: String::new(),
    };
    manifest.signature_base64 = STANDARD.encode(
        signing
            .sign(manifest.signing_message().as_bytes())
            .to_bytes(),
    );
    manifest
}

#[cfg(unix)]
#[test]
fn updater_does_not_accept_exit_zero_as_product_startup() {
    use std::os::unix::fs::PermissionsExt as _;
    let root = private_tempdir();
    let (signing, keys, keys_path) = key_fixture(root.path());
    let candidate = root.path().join("candidate");
    let target = root.path().join("installed");
    std::fs::copy("/bin/true", &candidate).unwrap();
    std::fs::write(&target, b"#!/bin/sh\nexit 0\n").unwrap();
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o751)).unwrap();
    let before = digest_file(&target).unwrap();
    let manifest = signed_update_manifest(&signing, &candidate, &target, b"test-only-evidence");
    let manager = UpdateManager::new(keys, root.path().join("updates")).unwrap();
    manager.verify_and_stage(manifest, &candidate, 1).unwrap();
    let result = std::process::Command::new(env!("CARGO_BIN_EXE_hepta-native-updater"))
        .arg(manager.pending_path())
        .arg(keys_path)
        .arg(&target)
        .arg("1")
        .arg("--")
        .args([
            "--endpoint-manifest",
            "/absent",
            "--trusted-keys",
            "/absent",
            "--state-dir",
            "/absent",
        ])
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert_eq!(digest_file(&target).unwrap(), before);
    assert_eq!(
        manager.load_pending().unwrap().unwrap().status,
        PendingUpdateStatus::RolledBack
    );
    assert_eq!(
        std::fs::metadata(&target).unwrap().permissions().mode() & 0o777,
        0o751
    );
}

#[test]
fn pending_read_is_bounded_and_unreadable_backup_is_not_success() {
    let root = private_tempdir();
    let (signing, keys, _) = key_fixture(root.path());
    let candidate = root.path().join("candidate");
    let target = root.path().join("target");
    std::fs::write(&candidate, b"candidate").unwrap();
    std::fs::write(&target, b"predecessor").unwrap();
    let manifest = signed_update_manifest(&signing, &candidate, &target, b"test-evidence");
    let manager = UpdateManager::new(keys.clone(), root.path().join("updates")).unwrap();
    manager.verify_and_stage(manifest, &candidate, 1).unwrap();
    activate_staged_update(&manager.pending_path(), &keys, &target, 1).unwrap();
    let pending = manager.load_pending().unwrap().unwrap();
    std::fs::remove_file(pending.backup_path.as_ref().unwrap()).unwrap();
    std::fs::create_dir(pending.backup_path.as_ref().unwrap()).unwrap();
    assert!(manager.rollback_unconfirmed().is_err());
    assert_eq!(
        manager.load_pending().unwrap().unwrap().status,
        PendingUpdateStatus::RecoveryRequired
    );
    std::fs::write(manager.pending_path(), vec![b' '; 65 * 1024]).unwrap();
    assert!(manager.load_pending().is_err());
}

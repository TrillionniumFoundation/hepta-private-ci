use std::path::Path;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use hepta_native::model::PlatformAction;
use hepta_native::model::SignedPlatformGrantV1;
use hepta_native::model::sha256_hex;
use hepta_native::security::GrantVerifier;
use hepta_native::security::ReloadingGrantVerifier;
use hepta_native::security::PlatformGrantContext;
use hepta_native::security::SignedEndpointManifestV1;
use hepta_native::security::TrustedKeySet;
use hepta_native::security::now_unix_ms;
use hepta_native::updater::SignedUpdateManifestV1;
use hepta_native::updater::UpdateManager;
use hepta_native::updater::activate_staged_update;
use hepta_native::updater::digest_file;
use tempfile::TempDir;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";

fn key_fixture(root: &Path) -> (SigningKey, TrustedKeySet, std::path::PathBuf) {
    let signing = SigningKey::from_bytes(&[7_u8; 32]);
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

#[test]
fn platform_grant_signature_binds_session_operation_and_payload() {
    let temp = TempDir::new().unwrap();
    let (signing, keys, _) = key_fixture(temp.path());
    let now = now_unix_ms().unwrap();
    let mut grant = SignedPlatformGrantV1 {
        key_id: "release.key".to_owned(),
        session_id: "session.1".to_owned(),
        session_generation: 9,
        operation_id: "operation.1".to_owned(),
        action: PlatformAction::CopyText,
        payload_digest: D1.to_owned(),
        expires_unix_ms: now + 60_000,
        signature_base64: String::new(),
    };
    grant.signature_base64 =
        STANDARD.encode(signing.sign(grant.signing_message().as_bytes()).to_bytes());
    keys.verify_platform_grant(
        &grant,
        PlatformGrantContext {
            session_id: "session.1",
            session_generation: 9,
            operation_id: "operation.1",
            action: PlatformAction::CopyText,
            payload_digest: D1,
            now_unix_ms: now,
        },
    )
    .unwrap();

    let error = keys
        .verify_platform_grant(
            &grant,
            PlatformGrantContext {
                session_id: "session.2",
                session_generation: 9,
                operation_id: "operation.1",
                action: PlatformAction::CopyText,
                payload_digest: D1,
                now_unix_ms: now,
            },
        )
        .unwrap_err();
    assert!(error.to_string().contains("not bound"));
}

#[test]
fn revoked_signing_key_is_rejected_on_next_grant_verification() {
    let temp = TempDir::new().unwrap();
    let (signing, _keys, key_path) = key_fixture(temp.path());
    let now = now_unix_ms().unwrap();
    let mut grant = SignedPlatformGrantV1 {
        key_id: "release.key".to_owned(),
        session_id: "session.1".to_owned(),
        session_generation: 9,
        operation_id: "operation.revoked".to_owned(),
        action: PlatformAction::CopyText,
        payload_digest: D1.to_owned(),
        expires_unix_ms: now + 60_000,
        signature_base64: String::new(),
    };
    grant.signature_base64 = STANDARD.encode(
        signing
            .sign(grant.signing_message().as_bytes())
            .to_bytes(),
    );
    let public = STANDARD.encode(signing.verifying_key().to_bytes());
    std::fs::write(
        &key_path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"release.key": public},
            "revoked_key_ids": ["release.key"]
        }))
        .unwrap(),
    )
    .unwrap();
    let verifier = ReloadingGrantVerifier::new(key_path.clone()).unwrap();
    let error = verifier
        .verify_platform_grant(
            &grant,
            PlatformGrantContext {
                session_id: "session.1",
                session_generation: 9,
                operation_id: "operation.revoked",
                action: PlatformAction::CopyText,
                payload_digest: D1,
                now_unix_ms: now,
            },
        )
        .unwrap_err();
    assert!(error.to_string().contains("revoked"));
}

#[test]
fn signed_update_stages_activates_and_confirms_with_predecessor_backup() {
    let temp = TempDir::new().unwrap();
    let (signing, keys, key_path) = key_fixture(temp.path());
    let package = temp.path().join("next.bin");
    let target = temp.path().join("hepta-native.bin");
    std::fs::write(&package, b"new native binary").unwrap();
    std::fs::write(&target, b"old native binary").unwrap();
    let now = now_unix_ms().unwrap();
    let package_digest = digest_file(&package).unwrap();
    let predecessor_digest = digest_file(&target).unwrap();
    let mut manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: package_digest.clone(),
        predecessor_digest,
        evidence_digest: sha256_hex(b"qualification-evidence"),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "stable".to_owned(),
        selected_by: "release.reviewer".to_owned(),
        generator_principal: "release.builder".to_owned(),
        issued_unix_ms: now.saturating_sub(1000),
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        signature_base64: String::new(),
    };
    manifest.signature_base64 = STANDARD.encode(
        signing
            .sign(manifest.signing_message().as_bytes())
            .to_bytes(),
    );

    let update_root = temp.path().join("updates");
    let manager = UpdateManager::new(keys, update_root).unwrap();
    let pending = manager.verify_and_stage(manifest, &package, 1).unwrap();
    assert_eq!(
        digest_file(&pending.staged_package).unwrap(),
        package_digest
    );

    let keys = TrustedKeySet::from_path(&key_path).unwrap();
    activate_staged_update(&manager.pending_path(), &keys, &target, 1).unwrap();
    assert_eq!(digest_file(&target).unwrap(), package_digest);
    assert!(manager.confirm_current_digest(&target).unwrap());
    assert!(!manager.pending_path().exists());
}

#[test]
fn update_rejects_self_selection_before_activation() {
    let temp = TempDir::new().unwrap();
    let (_signing, keys, _) = key_fixture(temp.path());
    let package = temp.path().join("next.bin");
    std::fs::write(&package, b"new native binary").unwrap();
    let now = now_unix_ms().unwrap();
    let manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(&package).unwrap(),
        predecessor_digest: sha256_hex(b"old"),
        evidence_digest: sha256_hex(b"evidence"),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "stable".to_owned(),
        selected_by: "same.principal".to_owned(),
        generator_principal: "same.principal".to_owned(),
        issued_unix_ms: now,
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        signature_base64: "invalid".to_owned(),
    };
    let manager = UpdateManager::new(keys, temp.path().join("updates")).unwrap();
    let error = manager.verify_and_stage(manifest, &package, 1).unwrap_err();
    assert!(error.to_string().contains("selected by its generator"));
}

#[test]
fn update_rejects_unadmitted_channel() {
    let temp = TempDir::new().unwrap();
    let (signing, keys, _) = key_fixture(temp.path());
    let package = temp.path().join("next.bin");
    std::fs::write(&package, b"new native binary").unwrap();
    let now = now_unix_ms().unwrap();
    let mut manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(&package).unwrap(),
        predecessor_digest: sha256_hex(b"old"),
        evidence_digest: sha256_hex(b"evidence"),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "beta".to_owned(),
        selected_by: "release.reviewer".to_owned(),
        generator_principal: "release.builder".to_owned(),
        issued_unix_ms: now,
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        signature_base64: String::new(),
    };
    manifest.signature_base64 = STANDARD.encode(
        signing
            .sign(manifest.signing_message().as_bytes())
            .to_bytes(),
    );
    let manager = UpdateManager::new(keys, temp.path().join("updates")).unwrap();
    let error = manager.verify_and_stage(manifest, &package, 1).unwrap_err();
    assert!(error.to_string().contains("channel"));
    assert!(!manager.pending_path().exists());
}

#[test]
fn activation_rejects_wrong_installed_predecessor() {
    let temp = TempDir::new().unwrap();
    let (signing, keys, key_path) = key_fixture(temp.path());
    let package = temp.path().join("next.bin");
    let target = temp.path().join("hepta-native.bin");
    std::fs::write(&package, b"new native binary").unwrap();
    std::fs::write(&target, b"expected predecessor").unwrap();
    let expected_predecessor = digest_file(&target).unwrap();
    let now = now_unix_ms().unwrap();
    let mut manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(&package).unwrap(),
        predecessor_digest: expected_predecessor,
        evidence_digest: sha256_hex(b"evidence"),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "stable".to_owned(),
        selected_by: "release.reviewer".to_owned(),
        generator_principal: "release.builder".to_owned(),
        issued_unix_ms: now,
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        signature_base64: String::new(),
    };
    manifest.signature_base64 = STANDARD.encode(
        signing
            .sign(manifest.signing_message().as_bytes())
            .to_bytes(),
    );
    let manager = UpdateManager::new(keys, temp.path().join("updates")).unwrap();
    manager.verify_and_stage(manifest, &package, 1).unwrap();
    std::fs::write(&target, b"unexpected predecessor").unwrap();
    let keys = TrustedKeySet::from_path(&key_path).unwrap();
    let error = activate_staged_update(&manager.pending_path(), &keys, &target, 1).unwrap_err();
    assert!(error.to_string().contains("predecessor digest mismatch"));
}

#[test]
fn unsigned_update_is_rejected_before_staging() {
    let temp = TempDir::new().unwrap();
    let (_signing, keys, _) = key_fixture(temp.path());
    let package = temp.path().join("unsigned.bin");
    std::fs::write(&package, b"unsigned native binary").unwrap();
    let now = now_unix_ms().unwrap();
    let manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(&package).unwrap(),
        predecessor_digest: sha256_hex(b"old"),
        evidence_digest: sha256_hex(b"evidence"),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "stable".to_owned(),
        selected_by: "release.reviewer".to_owned(),
        generator_principal: "release.builder".to_owned(),
        issued_unix_ms: now,
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        signature_base64: STANDARD.encode([0_u8; 64]),
    };
    let manager = UpdateManager::new(keys, temp.path().join("updates")).unwrap();
    let error = manager.verify_and_stage(manifest, &package, 1).unwrap_err();
    assert!(error.to_string().contains("security verification failed"));
    assert!(!manager.pending_path().exists());
}

#[test]
fn unconfirmed_activation_rolls_back_to_predecessor() {
    let temp = TempDir::new().unwrap();
    let (signing, keys, key_path) = key_fixture(temp.path());
    let package = temp.path().join("next.bin");
    let target = temp.path().join("hepta-native.bin");
    std::fs::write(&package, b"next native binary").unwrap();
    std::fs::write(&target, b"predecessor native binary").unwrap();
    let predecessor_digest = digest_file(&target).unwrap();
    let now = now_unix_ms().unwrap();
    let mut manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(&package).unwrap(),
        predecessor_digest: predecessor_digest.clone(),
        evidence_digest: sha256_hex(b"qualification-evidence"),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "stable".to_owned(),
        selected_by: "release.reviewer".to_owned(),
        generator_principal: "release.builder".to_owned(),
        issued_unix_ms: now.saturating_sub(1000),
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        signature_base64: String::new(),
    };
    manifest.signature_base64 = STANDARD.encode(
        signing
            .sign(manifest.signing_message().as_bytes())
            .to_bytes(),
    );
    let manager = UpdateManager::new(keys, temp.path().join("updates")).unwrap();
    manager.verify_and_stage(manifest, &package, 1).unwrap();
    let keys = TrustedKeySet::from_path(&key_path).unwrap();
    activate_staged_update(&manager.pending_path(), &keys, &target, 1).unwrap();
    assert!(manager.rollback_unconfirmed().unwrap());
    assert_eq!(digest_file(&target).unwrap(), predecessor_digest);
    assert!(!manager.pending_path().exists());
}

#[test]
fn signed_endpoint_manifest_binds_gateway_address_and_keyring_account() {
    let temp = TempDir::new().unwrap();
    let (signing, keys, _) = key_fixture(temp.path());
    let now = now_unix_ms().unwrap();
    let mut endpoint = SignedEndpointManifestV1 {
        schema: "hepta.endpoint-manifest.v1".to_owned(),
        endpoint_id: "runtime.local".to_owned(),
        address: "127.0.0.1:7373".to_owned(),
        protocol_version: 1,
        gateway_credential_account: "gateway.local".to_owned(),
        issued_unix_ms: now.saturating_sub(1000),
        expires_unix_ms: now + 60_000,
        key_id: "release.key".to_owned(),
        manifest_digest: String::new(),
        signature_base64: String::new(),
    };
    endpoint.manifest_digest = endpoint.computed_manifest_digest();
    endpoint.signature_base64 = STANDARD.encode(
        signing
            .sign(endpoint.signing_message().as_bytes())
            .to_bytes(),
    );
    let verified = endpoint.verify(&keys).unwrap();
    assert_eq!(verified.manifest.address, "127.0.0.1:7373");
    assert_eq!(verified.gateway_credential_account, "gateway.local");

    let mut tampered = endpoint.clone();
    tampered.address = "127.0.0.1:7374".to_owned();
    let error = tampered.verify(&keys).unwrap_err();
    assert!(error.to_string().contains("digest mismatch"));
}

use std::path::Path;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use hepta_native::model::PlatformPayload;
use hepta_native::model::SessionIncarnation;
use hepta_native::model::sha256_hex;
use hepta_native::security::KernelFinalUseGate;
use hepta_native::security::SignedEndpointManifestV1;
use hepta_native::security::TrustedKeySet;
use hepta_native::security::now_unix_ms;
use hepta_native::security::platform_final_use_binding;
use hepta_native::updater::PendingUpdateStatus;
use hepta_native::updater::SignedUpdateManifestV1;
use hepta_native::updater::UpdateManager;
use hepta_native::updater::activate_staged_update;
use hepta_native::updater::digest_file;
use tempfile::TempDir;

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

fn write_kernel_authority_config(
    root: &Path,
    signing: &SigningKey,
    head: &FinalUseRevocations,
) -> std::path::PathBuf {
    let path = root.join("final-use-authority.json");
    let state_dir = root.join("final-use-state");
    std::fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-final-use-authority.v1",
            "signer_id": "authority.native",
            "verifying_key_base64": STANDARD.encode(signing.verifying_key().to_bytes()),
            "state_dir": state_dir,
            "head": head,
        }))
        .unwrap(),
    )
    .unwrap();
    path
}

fn signed_final_use_grant(
    signing: &SigningKey,
    grant_id: &str,
    nonce: [u8; 32],
    binding: codex_hepta_contracts::FinalUseBinding,
) -> SignedFinalUseGrant {
    let now = now_unix_ms().unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority.native".to_owned(),
        authority_epoch: 1,
        grant_id: grant_id.to_owned(),
        nonce,
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

#[test]
fn kernel_final_use_binding_rejects_session_drift() {
    let temp = TempDir::new().unwrap();
    let signing = SigningKey::from_bytes(&[9_u8; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let config = write_kernel_authority_config(temp.path(), &signing, &head);
    let gate = KernelFinalUseGate::open(config).unwrap();
    let payload = PlatformPayload::CopyText {
        text: "bound payload".to_owned(),
    };
    let session1 = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 9,
    };
    let session2 = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.2".to_owned(),
        generation: 9,
    };
    let binding1 =
        platform_final_use_binding("principal.1", &session1, "operation.1", 11, &payload).unwrap();
    let signed = signed_final_use_grant(&signing, "grant.binding", [1_u8; 32], binding1.clone());
    let _permit = gate.claim_platform(&signed, binding1).unwrap();

    let binding2 =
        platform_final_use_binding("principal.1", &session2, "operation.1", 11, &payload).unwrap();
    let error = gate.claim_platform(&signed, binding2).unwrap_err();
    assert!(error.to_string().contains("BindingMismatch"));
}

#[test]
fn kernel_final_use_reloads_revocation_before_os_entry() {
    let temp = TempDir::new().unwrap();
    let signing = SigningKey::from_bytes(&[10_u8; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let config = write_kernel_authority_config(temp.path(), &signing, &head);
    let gate = KernelFinalUseGate::open(config.clone()).unwrap();
    let payload = PlatformPayload::CopyText {
        text: "revoked payload".to_owned(),
    };
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 9,
    };
    let binding =
        platform_final_use_binding("principal.1", &session, "operation.revoked", 11, &payload)
            .unwrap();
    let signed = signed_final_use_grant(&signing, "grant.revoked", [2_u8; 32], binding.clone());
    let permit = gate.claim_platform(&signed, binding).unwrap();

    let mut revoked = std::collections::BTreeSet::new();
    revoked.insert("grant.revoked".to_owned());
    let newer = FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: revoked,
    };
    write_kernel_authority_config(temp.path(), &signing, &newer);
    let error = gate.with_platform_use(permit, || true).unwrap_err();
    assert!(error.to_string().contains("Revoked"));
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
    let terminal = manager.load_pending().unwrap().unwrap();
    assert_eq!(terminal.status, PendingUpdateStatus::RolledBack);
    assert!(manager.pending_path().exists());
}

#[test]
fn interrupted_activation_is_reconciled_to_predecessor_before_restart() {
    let (temp, keys, signing) = key_fixture();
    let root = temp.path().join("updates");
    let manager = UpdateManager::new(keys.clone(), root.clone()).unwrap();
    let predecessor = temp.path().join("hepta-native");
    let package = temp.path().join("candidate");
    std::fs::write(&predecessor, b"predecessor").unwrap();
    std::fs::write(&package, b"candidate").unwrap();

    let manifest = signed_update_manifest(
        &signing,
        hepta_native::updater::digest_file(&package).unwrap(),
        hepta_native::updater::digest_file(&predecessor).unwrap(),
        "selector.1",
        "generator.1",
    );
    manager.verify_and_stage(manifest, &package, 1).unwrap();
    activate_staged_update(&manager.pending_path(), &keys, &predecessor, 1).unwrap();
    assert_eq!(std::fs::read(&predecessor).unwrap(), b"candidate");

    let reopened = UpdateManager::new(keys, root).unwrap();
    assert!(reopened.recover_interrupted_activation().unwrap());
    assert_eq!(std::fs::read(&predecessor).unwrap(), b"predecessor");
    let pending = reopened.load_pending().unwrap().unwrap();
    assert_eq!(pending.status, PendingUpdateStatus::RolledBack);
}

#[test]
fn failed_rollback_is_durable_recovery_required() {
    let temp = TempDir::new().unwrap();
    let (signing, keys, key_path) = key_fixture(temp.path());
    let package = temp.path().join("next-recovery.bin");
    let target = temp.path().join("hepta-native-recovery.bin");
    std::fs::write(&package, b"next recovery binary").unwrap();
    std::fs::write(&target, b"recovery predecessor").unwrap();
    let predecessor_digest = digest_file(&target).unwrap();
    let now = now_unix_ms().unwrap();
    let mut manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(&package).unwrap(),
        predecessor_digest,
        evidence_digest: sha256_hex(b"recovery-evidence"),
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
    let pending = manager.load_pending().unwrap().unwrap();
    std::fs::remove_file(pending.backup_path.unwrap()).unwrap();

    let error = manager.rollback_unconfirmed().unwrap_err();
    assert!(error.to_string().contains("recovery_required"));
    let recovery = manager.load_pending().unwrap().unwrap();
    assert_eq!(recovery.status, PendingUpdateStatus::RecoveryRequired);
    assert!(recovery.recovery_reason.is_some());
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

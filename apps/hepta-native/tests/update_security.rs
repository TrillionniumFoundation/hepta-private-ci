use base64::Engine as _;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use hepta_native::now_unix_ms;
use hepta_native::types::SignedUpdateManifest;
use hepta_native::types::UpdateManifest;
use hepta_native::update::UpdateError;
use hepta_native::update::UpdateManager;
use hepta_native::update::UpdateVerifier;
use hepta_native::update::sha256_file;
use hepta_native::update::update_signing_bytes;

fn root(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "hepta-native-update-{name}-{}-{}",
        std::process::id(),
        now_unix_ms().unwrap()
    ))
}

fn sign(manifest: UpdateManifest, key: &SigningKey) -> SignedUpdateManifest {
    let signature = key.sign(&update_signing_bytes(&manifest).unwrap());
    SignedUpdateManifest {
        manifest,
        signature_b64: base64::engine::general_purpose::STANDARD.encode(signature.to_bytes()),
    }
}

#[test]
fn signed_update_binds_package_predecessor_and_selector() {
    let root = root("stage");
    std::fs::create_dir_all(&root).unwrap();
    let current = root.join(if cfg!(windows) {
        "hepta-native.exe"
    } else {
        "hepta-native"
    });
    let package = root.join(if cfg!(windows) {
        "candidate.exe"
    } else {
        "candidate"
    });
    std::fs::write(&current, b"old application bytes").unwrap();
    std::fs::write(&package, b"new independently selected application bytes").unwrap();

    let key = SigningKey::from_bytes(&[11_u8; 32]);
    let verifier =
        UpdateVerifier::new("update.test".to_string(), key.verifying_key().to_bytes()).unwrap();
    let now = now_unix_ms().unwrap();
    let manifest = UpdateManifest {
        schema_version: 1,
        key_id: "update.test".to_string(),
        version: "1.0.1".to_string(),
        channel: "stable".to_string(),
        platform: std::env::consts::OS.to_string(),
        architecture: std::env::consts::ARCH.to_string(),
        package_sha256: sha256_file(&package).unwrap(),
        predecessor_sha256: sha256_file(&current).unwrap(),
        backend_protocol_version: 1,
        selected_by: "release.review".to_string(),
        generator_principal: "build.generator".to_string(),
        issued_at_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 60_000,
    };
    let signed = sign(manifest.clone(), &key);
    let manager = UpdateManager::new(root.clone(), Some(verifier.clone()));
    let staged = manager.stage(signed, &package, &current).unwrap();
    assert_eq!(staged.staged_sha256, manifest.package_sha256);
    assert!(staged.staged_path.is_file());

    let self_selected = sign(
        UpdateManifest {
            selected_by: "same.principal".to_string(),
            generator_principal: "same.principal".to_string(),
            ..manifest
        },
        &key,
    );
    assert!(matches!(
        verifier.verify(&self_selected),
        Err(UpdateError::SelfSelected)
    ));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn unsigned_or_tampered_update_is_rejected() {
    let key = SigningKey::from_bytes(&[12_u8; 32]);
    let verifier =
        UpdateVerifier::new("update.test".to_string(), key.verifying_key().to_bytes()).unwrap();
    let now = now_unix_ms().unwrap();
    let manifest = UpdateManifest {
        schema_version: 1,
        key_id: "update.test".to_string(),
        version: "2.0.0".to_string(),
        channel: "stable".to_string(),
        platform: std::env::consts::OS.to_string(),
        architecture: std::env::consts::ARCH.to_string(),
        package_sha256: "3".repeat(64),
        predecessor_sha256: "4".repeat(64),
        backend_protocol_version: 1,
        selected_by: "release.review".to_string(),
        generator_principal: "build.generator".to_string(),
        issued_at_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 60_000,
    };
    let mut signed = sign(manifest, &key);
    signed.signature_b64 = base64::engine::general_purpose::STANDARD.encode([0_u8; 64]);
    assert!(matches!(
        verifier.verify(&signed),
        Err(UpdateError::InvalidSignature)
    ));
}

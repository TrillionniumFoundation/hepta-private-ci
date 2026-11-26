#![cfg(unix)]

use super::*;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

fn manager(temp: &Path) -> (UpdateManager, SigningKey) {
    let signing = SigningKey::from_bytes(&crate::model::sha256_bytes(b"pinned update regression"));
    let key_path = temp.join("keys.json");
    std::fs::write(
        &key_path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": { "release.test": STANDARD.encode(signing.verifying_key().to_bytes()) }
        }))
        .unwrap(),
    )
    .unwrap();
    (
        UpdateManager::new(
            TrustedKeySet::from_path(&key_path).unwrap(),
            temp.join("updates"),
        )
        .unwrap(),
        signing,
    )
}

fn manifest(
    signing: &SigningKey,
    package_digest: String,
    predecessor_digest: String,
) -> SignedUpdateManifestV1 {
    let now = now_unix_ms().unwrap();
    let mut manifest = SignedUpdateManifestV1 {
        schema: UPDATE_SCHEMA.into(),
        package_digest,
        predecessor_digest,
        evidence_digest: crate::model::sha256_hex(b"rooted test evidence"),
        platform: std::env::consts::OS.into(),
        architecture: std::env::consts::ARCH.into(),
        backend_protocol_version: 1,
        channel: "stable".into(),
        selected_by: "release.reviewer".into(),
        generator_principal: "release.builder".into(),
        issued_unix_ms: now.saturating_sub(1),
        expires_unix_ms: now + 60_000,
        key_id: "release.test".into(),
        signature_base64: String::new(),
    };
    manifest.signature_base64 = STANDARD.encode(
        signing
            .sign(manifest.signing_message().as_bytes())
            .to_bytes(),
    );
    manifest
}

#[test]
fn cancellation_and_ack_cannot_commit_after_the_pending_root_is_replaced() {
    let running_digest = crate::update_storage::running_binary_digest().unwrap();
    for acknowledge in [false, true] {
        let temp = tempfile::tempdir().unwrap();
        let (manager, signing) = manager(temp.path());
        let arguments = [
            "--endpoint-manifest",
            "/manifest",
            "--trusted-keys",
            "/keys",
            "--state-dir",
            "/state",
        ]
        .map(String::from);
        let handoff = UpdateHandoff::issue(&arguments).unwrap();
        let pending = PendingUpdateV1 {
            schema: PENDING_SCHEMA.into(),
            manifest: manifest(
                &signing,
                running_digest.clone(),
                crate::model::sha256_hex(b"predecessor"),
            ),
            staged_package: manager
                .root
                .join("staged")
                .join(format!("{running_digest}.package")),
            target_path: Some(std::env::current_exe().unwrap()),
            backup_path: Some(temp.path().join("predecessor")),
            status: PendingUpdateStatus::ActivatedUnconfirmed,
            transition_unix_ms: now_unix_ms().unwrap(),
            recovery_reason: None,
            handoff: Some(handoff.clone()),
            readiness: Some(UpdateReadiness {
                process_id: std::process::id(),
                session: crate::model::SessionIncarnation {
                    endpoint_id: "runtime.test".into(),
                    session_id: "session.test".into(),
                    generation: 1,
                },
                view_digest: crate::model::sha256_hex(b"rendered view"),
                view_revision: 1,
                binary_digest: running_digest.clone(),
            }),
        };
        persist_json_atomic(&manager.private_root, &manager.pending_path(), &pending).unwrap();
        let old_bytes = std::fs::read(manager.pending_path()).unwrap();
        let original = temp.path().join("original-updates");
        let cut = || {
            std::fs::rename(&manager.root, &original)?;
            let replacement = PrivateStateRoot::open(manager.root.clone())?;
            persist_json_atomic(
                &replacement,
                &manager.pending_path(),
                &"replacement sentinel",
            )
        };
        let result = if acknowledge {
            manager.acknowledge_at_boundary(&handoff, cut)
        } else {
            manager.cancel_at_boundary(&handoff, cut).map(|_| ())
        };
        assert!(
            result.is_err(),
            "root loss cannot become cancellation or confirmation success"
        );
        assert_eq!(
            std::fs::read(original.join("pending-update.json")).unwrap(),
            old_bytes
        );
        assert_eq!(
            std::fs::read(manager.pending_path()).unwrap(),
            b"\"replacement sentinel\""
        );
        let original_pending: PendingUpdateV1 = serde_json::from_slice(&old_bytes).unwrap();
        assert_eq!(
            original_pending.status,
            PendingUpdateStatus::ActivatedUnconfirmed
        );
        assert!(original_pending.readiness.is_some());
    }
}

#[test]
fn staging_migrates_owned_legacy_modes_and_activation_requires_the_owned_package() {
    use std::os::unix::fs::PermissionsExt as _;
    let temp = tempfile::tempdir().unwrap();
    let (manager, signing) = manager(temp.path());
    let package = temp.path().join("download");
    let target = temp.path().join("installed");
    std::fs::write(&package, b"signed candidate").unwrap();
    std::fs::write(&target, b"installed predecessor").unwrap();
    let manifest = manifest(
        &signing,
        digest_file(&package).unwrap(),
        digest_file(&target).unwrap(),
    );
    let legacy_stage = manager.root.join("staged");
    std::fs::create_dir(&legacy_stage).unwrap();
    std::fs::set_permissions(&legacy_stage, std::fs::Permissions::from_mode(0o755)).unwrap();
    let owned_package = legacy_stage.join(format!("{}.package", manifest.package_digest));
    std::fs::write(&owned_package, b"signed candidate").unwrap();
    std::fs::set_permissions(&owned_package, std::fs::Permissions::from_mode(0o644)).unwrap();
    let mut pending = manager.verify_and_stage(manifest, &package, 1).unwrap();
    assert_eq!(
        std::fs::metadata(&legacy_stage)
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
    assert_eq!(
        std::fs::metadata(&owned_package)
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    // A signed package digest does not authorize an unsigned pending-path field
    // to select another filesystem namespace, even when the bytes are equal.
    pending.staged_package = package.clone();
    persist_json_atomic(&manager.private_root, &manager.pending_path(), &pending).unwrap();
    assert!(
        activate_staged_update(&manager.pending_path(), &manager.trusted_keys, &target, 1).is_err()
    );
    assert_eq!(std::fs::read(&target).unwrap(), b"installed predecessor");
    assert_eq!(
        manager.load_pending().unwrap().unwrap().status,
        PendingUpdateStatus::Staged
    );
    assert_eq!(std::fs::read(&package).unwrap(), b"signed candidate");
}

#[test]
fn a_failed_pending_publication_bounds_orphans_and_allows_only_the_exact_retry() {
    let temp = tempfile::tempdir().unwrap();
    let (manager, signing) = manager(temp.path());
    let first = temp.path().join("download-first");
    let second = temp.path().join("download-second");
    std::fs::write(&first, b"first signed candidate").unwrap();
    std::fs::write(&second, b"second signed candidate").unwrap();
    let predecessor = crate::model::sha256_hex(b"installed predecessor");
    let first_manifest = manifest(&signing, digest_file(&first).unwrap(), predecessor.clone());
    let second_manifest = manifest(&signing, digest_file(&second).unwrap(), predecessor);
    let stage = manager.root.join("staged");
    let orphan = stage.join(format!("{}.package", first_manifest.package_digest));
    let denied = stage.join(format!("{}.package", second_manifest.package_digest));
    assert!(
        manager
            .verify_and_stage_at_boundary(first_manifest.clone(), &first, 1, || Err(
                ShellError::Io(std::io::Error::other("injected pre-publication failure"))
            ))
            .is_err()
    );
    assert!(manager.load_pending().unwrap().is_none());
    assert_eq!(std::fs::read(&orphan).unwrap(), b"first signed candidate");
    assert!(
        manager
            .verify_and_stage(second_manifest.clone(), &second, 1)
            .is_err()
    );
    assert!(!denied.exists());
    assert_eq!(std::fs::read_dir(&stage).unwrap().count(), 1);
    assert_eq!(std::fs::read(&orphan).unwrap(), b"first signed candidate");
    manager.verify_and_stage(first_manifest, &first, 1).unwrap();
    assert_eq!(std::fs::read_dir(&stage).unwrap().count(), 1);
    manager.clear_pending().unwrap();
    assert!(!orphan.exists());
    manager
        .verify_and_stage(second_manifest, &second, 1)
        .unwrap();
    assert_eq!(std::fs::read_dir(&stage).unwrap().count(), 1);
    assert_eq!(std::fs::read(&denied).unwrap(), b"second signed candidate");
}

#[test]
fn unknown_and_crash_remnant_staging_entries_are_preserved_and_block_admission() {
    use std::os::unix::fs::PermissionsExt as _;
    for name in [
        "operator-note",
        ".atomic-write-crash-remnant",
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff.package",
    ] {
        let temp = tempfile::tempdir().unwrap();
        let (manager, signing) = manager(temp.path());
        let package = temp.path().join("download");
        std::fs::write(&package, b"signed candidate").unwrap();
        let manifest = manifest(
            &signing,
            digest_file(&package).unwrap(),
            crate::model::sha256_hex(b"predecessor"),
        );
        let stage = manager.private_root.child_create("staged").unwrap();
        let unknown = stage.path().join(name);
        std::fs::write(&unknown, b"preserved unknown evidence").unwrap();
        std::fs::set_permissions(&unknown, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(manager.verify_and_stage(manifest, &package, 1).is_err());
        assert!(manager.load_pending().unwrap().is_none());
        assert_eq!(std::fs::read_dir(stage.path()).unwrap().count(), 1);
        assert_eq!(
            std::fs::read(&unknown).unwrap(),
            b"preserved unknown evidence"
        );
        assert_eq!(
            std::fs::metadata(&unknown).unwrap().permissions().mode() & 0o777,
            0o644
        );
    }
}

#[test]
fn a_helper_manager_cannot_activate_a_new_namespace_while_owning_the_original_runner() {
    let temp = tempfile::tempdir().unwrap();
    let (manager, signing) = manager(temp.path());
    let target = temp.path().join("installed");
    std::fs::write(&target, b"installed predecessor").unwrap();
    let predecessor = digest_file(&target).unwrap();
    let first = temp.path().join("download-first");
    let second = temp.path().join("download-second");
    std::fs::write(&first, b"first signed candidate").unwrap();
    std::fs::write(&second, b"second signed candidate").unwrap();
    manager
        .verify_and_stage(
            manifest(&signing, digest_file(&first).unwrap(), predecessor.clone()),
            &first,
            1,
        )
        .unwrap();
    let original_bytes = std::fs::read(manager.pending_path()).unwrap();
    let _runner = manager.lock_runner().unwrap();
    let original = temp.path().join("original-updates");
    std::fs::rename(&manager.root, &original).unwrap();
    let replacement =
        UpdateManager::new(manager.trusted_keys.clone(), manager.root.clone()).unwrap();
    replacement
        .verify_and_stage(
            manifest(&signing, digest_file(&second).unwrap(), predecessor.clone()),
            &second,
            1,
        )
        .unwrap();
    let replacement_bytes = std::fs::read(replacement.pending_path()).unwrap();
    assert!(manager.activate_staged_update(&target, 1).is_err());
    assert_eq!(std::fs::read(&target).unwrap(), b"installed predecessor");
    assert!(
        !target
            .with_extension(format!("{predecessor}.predecessor"))
            .exists()
    );
    assert_eq!(
        std::fs::read(original.join("pending-update.json")).unwrap(),
        original_bytes
    );
    assert_eq!(
        std::fs::read(replacement.pending_path()).unwrap(),
        replacement_bytes
    );
    assert_eq!(
        replacement.load_pending().unwrap().unwrap().status,
        PendingUpdateStatus::Staged
    );
}

use super::*;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use std::io::Write as _;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

const CHILD_ROOT: &str = "HEPTA_NATIVE_ACK_CHILD_ROOT";
const CHILD_NONCE: &str = "HEPTA_NATIVE_ACK_CHILD_NONCE";

fn restart_arguments() -> Vec<String> {
    [
        "--endpoint-manifest",
        "/manifest",
        "--trusted-keys",
        "/keys",
        "--state-dir",
        "/state",
    ]
    .map(String::from)
    .to_vec()
}

#[test]
fn helper_acknowledgement_is_durable_before_success() {
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let root = PathBuf::from(root);
        let keys = TrustedKeySet::from_path(&root.join("keys.json")).unwrap();
        let manager = UpdateManager::new(keys, root.join("updates")).unwrap();
        let handoff = UpdateHandoff::from_invocation(
            std::env::var(CHILD_NONCE).unwrap(),
            &restart_arguments(),
        )
        .unwrap();
        manager.validate_running_handoff(&handoff).unwrap();
        crate::update_handoff::watch_helper_lifetime(manager.clone(), handoff.clone()).unwrap();
        let session = crate::model::SessionIncarnation {
            endpoint_id: "runtime.test".into(),
            session_id: "session.test".into(),
            generation: 1,
        };
        let view = crate::model::RuntimeView {
            session_id: session.session_id.clone(),
            session_generation: session.generation,
            generation: 1,
            revision: 1,
            digest: crate::model::sha256_hex(b"rendered view"),
            modules: vec!["ui.native".into()],
        };
        manager
            .confirm_running_process(&handoff, &session, &view)
            .unwrap();
        assert_eq!(
            manager.load_pending().unwrap().unwrap().status,
            PendingUpdateStatus::Confirmed
        );
        // The durable commit is the scheduling barrier: no local notification
        // has arrived at this observer when its deadline fires immediately.
        // It must preserve the already confirmed process through the owner fence.
        let (_delayed_notification, receiver) = std::sync::mpsc::sync_channel(1);
        crate::update_handoff::observe_helper_lifetime(
            &manager,
            &handoff,
            receiver,
            Duration::ZERO,
        )
        .unwrap();
        assert_eq!(
            manager.load_pending().unwrap().unwrap().status,
            PendingUpdateStatus::Confirmed
        );
        return;
    }

    for scenario in ["helper_lost", "acknowledged", "late_ack_after_cancellation"] {
        let send_ack = scenario != "helper_lost";
        let cancelled = scenario == "late_ack_after_cancellation";
        let root = tempfile::tempdir().unwrap();
        let signing = SigningKey::from_bytes(&crate::model::sha256_bytes(b"native ack regression"));
        let keys_path = root.path().join("keys.json");
        std::fs::write(
            &keys_path,
            serde_json::to_vec(&serde_json::json!({
                "schema": "hepta.native-trusted-keys.v1",
                "keys": {"release.test": STANDARD.encode(signing.verifying_key().to_bytes())}
            }))
            .unwrap(),
        )
        .unwrap();
        let keys = TrustedKeySet::from_path(&keys_path).unwrap();
        let manager = UpdateManager::new(keys, root.path().join("updates")).unwrap();
        let target = root.path().join(if cfg!(windows) {
            "installed.exe"
        } else {
            "installed"
        });
        std::fs::copy(std::env::current_exe().unwrap(), &target).unwrap();
        let backup = root.path().join("predecessor");
        std::fs::write(&backup, b"admitted predecessor").unwrap();
        let now = now_unix_ms().unwrap();
        let mut manifest = SignedUpdateManifestV1 {
            schema: UPDATE_SCHEMA.into(),
            package_digest: digest_file(&target).unwrap(),
            predecessor_digest: digest_file(&backup).unwrap(),
            evidence_digest: crate::model::sha256_hex(b"test only"),
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
        let handoff = UpdateHandoff::issue(&restart_arguments()).unwrap();
        let pending = PendingUpdateV1 {
            schema: PENDING_SCHEMA.into(),
            manifest,
            staged_package: target.clone(),
            target_path: Some(target.clone()),
            backup_path: Some(backup),
            status: PendingUpdateStatus::ActivatedUnconfirmed,
            transition_unix_ms: now,
            recovery_reason: None,
            handoff: Some(handoff.clone()),
            readiness: None,
        };
        persist_json_atomic(&manager.pending_path(), &pending).unwrap();
        let mut child = Command::new(target)
            .args([
                "--exact",
                "updater::tests::helper_acknowledgement_is_durable_before_success",
                "--nocapture",
            ])
            .env(CHILD_ROOT, root.path())
            .env(CHILD_NONCE, handoff.nonce())
            .stdin(Stdio::piped())
            .spawn()
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(20);
        loop {
            let current = manager.load_pending().unwrap().unwrap();
            if let Some(readiness) = current.readiness {
                assert_eq!(current.status, PendingUpdateStatus::ActivatedUnconfirmed);
                assert_eq!(readiness.process_id, child.id());
                break;
            }
            if child.try_wait().unwrap().is_some() || Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("candidate did not publish readiness");
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        let mut pipe = child.stdin.take().unwrap();
        if cancelled {
            assert!(manager.cancel_unconfirmed_restart(&handoff).unwrap());
            assert!(manager.cancel_unconfirmed_restart(&handoff).unwrap());
        }
        if send_ack {
            pipe.write_all(b"C").unwrap();
        }
        drop(pipe);
        let status = loop {
            if let Some(status) = child.try_wait().unwrap() {
                break status;
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("candidate did not terminate after helper result");
            }
            std::thread::sleep(Duration::from_millis(10));
        };
        assert_eq!(status.success(), send_ack && !cancelled);
        let current = manager.load_pending().unwrap().unwrap();
        if send_ack && !cancelled {
            assert_eq!(current.status, PendingUpdateStatus::Confirmed);
            assert!(!manager.cancel_unconfirmed_restart(&handoff).unwrap());
        } else {
            assert_eq!(current.status, PendingUpdateStatus::RollbackStarted);
            assert!(manager.recover_interrupted_activation().unwrap());
            assert_eq!(
                manager.load_pending().unwrap().unwrap().status,
                PendingUpdateStatus::RolledBack
            );
            assert_eq!(
                std::fs::read(current.target_path.unwrap()).unwrap(),
                b"admitted predecessor"
            );
        }
    }
}

#[test]
fn failed_candidate_copy_cannot_rollback_over_an_unrelated_newer_binary() {
    let root = tempfile::tempdir().unwrap();
    let state = root.path().join("updates");
    let _private = PrivateStateRoot::open(state.clone()).unwrap();
    let pending_path = state.join("pending-update.json");
    let target = root.path().join("installed");
    let backup = root.path().join("predecessor");
    let staged = state.join("staged.package");
    std::fs::write(&target, b"admitted predecessor").unwrap();
    std::fs::write(&backup, b"admitted predecessor").unwrap();
    std::fs::write(&staged, b"admitted candidate").unwrap();
    let now = now_unix_ms().unwrap();
    let mut pending = PendingUpdateV1 {
        schema: PENDING_SCHEMA.into(),
        manifest: SignedUpdateManifestV1 {
            schema: UPDATE_SCHEMA.into(),
            package_digest: digest_file(&staged).unwrap(),
            predecessor_digest: digest_file(&backup).unwrap(),
            evidence_digest: crate::model::sha256_hex(b"test-only failure cut"),
            platform: std::env::consts::OS.into(),
            architecture: std::env::consts::ARCH.into(),
            backend_protocol_version: 1,
            channel: "stable".into(),
            selected_by: "release.reviewer".into(),
            generator_principal: "release.builder".into(),
            issued_unix_ms: now.saturating_sub(1),
            expires_unix_ms: now + 60_000,
            key_id: "release.test".into(),
            signature_base64: "unused by the admitted failure transition".into(),
        },
        staged_package: staged.clone(),
        target_path: Some(target.clone()),
        backup_path: Some(backup.clone()),
        status: PendingUpdateStatus::ActivationStarted,
        transition_unix_ms: now,
        recovery_reason: None,
        handoff: None,
        readiness: None,
    };
    persist_json_atomic(&pending_path, &pending).unwrap();
    // Both substitutions happen after admission. Candidate drift fails before
    // replacement; that failure must not authorize restoring over foreign data.
    std::fs::write(&target, b"independently installed newer binary").unwrap();
    std::fs::write(&staged, b"substituted candidate").unwrap();
    let copy_error = copy_and_sync(&staged, &target, &pending.manifest.package_digest).unwrap_err();
    assert!(copy_error.to_string().contains("before atomic replacement"));
    let error = rollback_after_activation_failure(
        &pending_path,
        &mut pending,
        &target,
        &backup,
        &copy_error.to_string(),
    )
    .unwrap_err();
    assert!(error.to_string().contains("recovery_required"));
    assert_eq!(
        std::fs::read(&target).unwrap(),
        b"independently installed newer binary"
    );
    let durable: PendingUpdateV1 =
        crate::file_input::read_json_file(&pending_path, 64 * 1024).unwrap();
    assert_eq!(durable.status, PendingUpdateStatus::RecoveryRequired);
    assert!(
        durable
            .recovery_reason
            .unwrap()
            .contains("neither candidate nor predecessor")
    );
    assert_eq!(std::fs::read(&backup).unwrap(), b"admitted predecessor");
}

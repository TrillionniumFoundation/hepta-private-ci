use std::collections::BTreeSet;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::*;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn intent(operation: &str) -> DurableOperationIntent {
    DurableOperationIntent {
        scope_id: stable_id("scope:fault"),
        operation_id: stable_id(operation),
        scope_digest: Digest32::of_bytes(b"scope:fault"),
        request_digest: Digest32::of_bytes(format!("request:{operation}").as_bytes()),
        payload_digest: Digest32::of_bytes(b"payload"),
        destination_id: stable_id("destination:fault"),
        expected_predecessor: None,
        writer_generation: generation(3),
        authority_epoch: generation(9),
    }
}

#[tokio::test]
async fn simulated_outbox_write_failure_rolls_back_operation_and_intent() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    let admin = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("open fault injector");
    sqlx::query(
        "CREATE TRIGGER fixture_outbox_disk_full BEFORE INSERT ON cross_owner_outbox
         BEGIN SELECT RAISE(ABORT, 'fixture disk full'); END",
    )
    .execute(&admin)
    .await
    .expect("install fault trigger");
    let value = intent("operation:disk-full");
    assert!(store.prepare_intent(value.clone()).await.is_err());
    assert!(
        store
            .operation(&value.scope_id, &value.operation_id)
            .await
            .expect("read rolled-back operation")
            .is_none()
    );
    assert!(
        store
            .outbox(
                &value.scope_id,
                &value.operation_id,
                &value.destination_id,
            )
            .await
            .expect("read rolled-back outbox")
            .is_none()
    );
    sqlx::query("DROP TRIGGER fixture_outbox_disk_full")
        .execute(&admin)
        .await
        .expect("remove fault trigger");
    admin.close().await;
    store
        .prepare_intent(value)
        .await
        .expect("store remains recoverable");
}

#[tokio::test]
async fn migration_checksum_drift_fails_closed_on_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    let path = store.path().to_path_buf();
    drop(store);
    let admin = sqlite
        .open_durable_evidence_pool(&path)
        .await
        .expect("open migration injector");
    sqlx::query("UPDATE _sqlx_migrations SET checksum = X'00' WHERE version = 1")
        .execute(&admin)
        .await
        .expect("tamper migration checksum");
    admin.close().await;
    assert!(DurableOperationStore::open(&sqlite).await.is_err());
}

#[cfg(unix)]
#[tokio::test]
async fn final_use_binding_drift_rejects_before_adapter_entry() {
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::Ordering;

    struct CountingAdapter(Arc<AtomicBool>);
    impl EffectAdapter for CountingAdapter {
        fn dispatch(&mut self, _dispatch: &ArmedDispatch) -> DispatchObservation {
            self.0.store(true, Ordering::SeqCst);
            DispatchObservation::Indeterminate {
                reason_digest: Digest32::of_bytes(b"must-not-run"),
            }
        }
    }

    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    let value = intent("operation:authority-drift");
    store
        .prepare_intent(value.clone())
        .await
        .expect("prepare intent");
    let claim = store
        .claim_outbox(
            &value.scope_id,
            &value.operation_id,
            &value.destination_id,
            stable_id("worker:fault"),
            value.writer_generation,
            5_000,
        )
        .await
        .expect("claim");

    let issuer = SigningKey::from_bytes(&[89; 32]);
    let signed_binding = FinalUseBinding {
        subject_id: "agent-fault".into(),
        destination_id: value.destination_id.as_str().into(),
        request_sha256: *value.request_digest.as_array(),
        scope_sha256: *value.scope_digest.as_array(),
        payload_sha256: *value.payload_digest.as_array(),
    };
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "authority-drift".into(),
        nonce: [17; 32],
        binding: signed_binding.clone(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: issuer
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    let authority_dir = TempDir::new().expect("authority dir");
    std::fs::set_permissions(
        authority_dir.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("private authority dir");
    let authority = FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("open authority");
    let mut drifted = signed_binding;
    drifted.payload_sha256 = Digest32::of_bytes(b"changed-payload").into_array();
    let entered = Arc::new(AtomicBool::new(false));
    let mut adapter = CountingAdapter(Arc::clone(&entered));
    assert_eq!(
        store
            .dispatch_with_final_use(
                claim,
                &authority,
                &signed,
                &drifted,
                Digest32::of_bytes(b"dispatch"),
                &mut adapter,
            )
            .await,
        Err(OperationError::AuthorityRejected)
    );
    assert!(!entered.load(Ordering::SeqCst));
    let outbox = store
        .outbox(&value.scope_id, &value.operation_id, &value.destination_id)
        .await
        .expect("read outbox")
        .expect("outbox exists");
    assert_eq!(outbox.state, DurableOutboxState::Leased);
}

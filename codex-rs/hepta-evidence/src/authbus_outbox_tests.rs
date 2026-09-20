use std::time::Duration;

use codex_hepta_authbus::Error;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::authbus_outbox::maintain;
use crate::store::now_millis;
use crate::*;

fn fixture(sequence: u64, expiry: u64) -> (IssuerRegistration, SignedMessage) {
    let key = SigningKey::from_bytes(&[37; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:queue").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!("message:{sequence}")).unwrap(),
        subject_id: StableId::new("subject:queue").unwrap(),
        scope_digest: Digest32::of_bytes(b"route"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence,
        expires_at_ms: expiry,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (issuer, SignedMessage { claims, signature })
}

fn config(path: &std::path::Path) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(path.to_path_buf()).unwrap())
}

async fn enqueue(store: &HeptaEvidenceStore, sequence: u64) -> AuthBusDeliveryStatus {
    let (issuer, message) = fixture(sequence, u64::MAX);
    store
        .enqueue_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"payload",
        )
        .await
        .unwrap()
}

async fn claim(
    store: &HeptaEvidenceStore,
    id: Digest32,
    lease_ms: i64,
) -> Result<AuthBusDelivery, AuthBusOutboxError> {
    let (issuer, message) = fixture(1, u64::MAX);
    let worker = StableId::new("worker:queue").unwrap();
    store
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: id,
                subject_id: &message.claims.subject_id,
                scope_digest: message.claims.scope_digest,
                worker_id: &worker,
                lease_ms,
            },
        )
        .await
}

#[tokio::test]
async fn enqueue_commit_response_loss_is_idempotent_across_reopen() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let status = enqueue(&first, u64::MAX).await;
    first.pool.close().await;
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    assert_eq!(enqueue(&second, u64::MAX).await, status);
    let (issuer, message) = fixture(u64::MAX, u64::MAX);
    assert_eq!(
        second
            .pending_authbus_deliveries(&message.claims.subject_id, message.claims.scope_digest, 10)
            .await
            .unwrap(),
        vec![status.clone()]
    );
    let delivery = claim(&second, status.delivery_id, 60_000).await.unwrap();
    assert_eq!(delivery.message.claims, message.claims);
    assert_eq!(delivery.payload, b"payload");
    let ack = Digest32::of_bytes(b"consumer receipt");
    second
        .ack_authbus_delivery(&issuer, &delivery.lease, ack)
        .await
        .unwrap();
    assert!(matches!(
        second
            .ack_authbus_delivery(&issuer, &delivery.lease, ack)
            .await,
        Err(AuthBusOutboxError::Unavailable)
    ));
    second.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let status = reopened
        .authbus_delivery_status(status.delivery_id)
        .await
        .unwrap();
    assert_eq!(
        (status.state, status.acknowledgement),
        (AuthBusDeliveryState::Acked, Some(ack))
    );
    assert!(matches!(
        claim(&reopened, status.delivery_id, 60_000).await,
        Err(AuthBusOutboxError::Unavailable)
    ));
}

#[tokio::test]
async fn failed_insert_rolls_back_replay_and_direct_admission_cannot_be_upgraded() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    sqlx::query(
        "CREATE TRIGGER fixture_insert_failure BEFORE INSERT ON authbus_outbox
        BEGIN SELECT RAISE(ABORT, 'fixture disk failure'); END",
    )
    .execute(&store.pool)
    .await
    .unwrap();
    let (issuer, message) = fixture(1, u64::MAX);
    assert!(
        store
            .enqueue_authbus_message(
                &issuer,
                &message,
                &message.claims.subject_id,
                message.claims.scope_digest,
                b"payload"
            )
            .await
            .is_err()
    );
    sqlx::query("DROP TRIGGER fixture_insert_failure")
        .execute(&store.pool)
        .await
        .unwrap();
    enqueue(&store, 1).await;
    let (issuer, message) = fixture(2, u64::MAX);
    store
        .admit_authbus_message(
            &issuer,
            &message,
            message.claims.scope_digest,
            message.claims.payload_digest,
        )
        .await
        .unwrap();
    assert!(matches!(
        store
            .enqueue_authbus_message(
                &issuer,
                &message,
                &message.claims.subject_id,
                message.claims.scope_digest,
                b"payload"
            )
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::Replay)
        ))
    ));
}

#[tokio::test]
async fn payload_route_and_retained_message_identity_cannot_be_substituted() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    let (issuer, message) = fixture(1, u64::MAX);
    for payload in [b"different".as_slice(), &[0; 16_385]] {
        assert!(
            store
                .enqueue_authbus_message(
                    &issuer,
                    &message,
                    &message.claims.subject_id,
                    message.claims.scope_digest,
                    payload
                )
                .await
                .is_err()
        );
    }
    let other_subject = StableId::new("subject:other").unwrap();
    assert!(
        store
            .enqueue_authbus_message(
                &issuer,
                &message,
                &other_subject,
                message.claims.scope_digest,
                b"payload"
            )
            .await
            .is_err()
    );
    enqueue(&store, 1).await;
    let (_, mut replacement) = fixture(2, u64::MAX);
    replacement.claims.message_id = message.claims.message_id;
    replacement.signature = SigningKey::from_bytes(&[37; 32])
        .sign(&replacement.claims.signing_bytes())
        .to_bytes();
    assert!(matches!(
        store
            .enqueue_authbus_message(
                &issuer,
                &replacement,
                &replacement.claims.subject_id,
                replacement.claims.scope_digest,
                b"payload"
            )
            .await,
        Err(AuthBusOutboxError::Storage(
            EvidenceError::IdempotencyConflict { .. }
        ))
    ));
    enqueue(&store, 2).await;
}

#[tokio::test]
async fn two_handles_serialize_claim_and_every_new_fence_rejects_old_worker() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let id = enqueue(&first, 1).await.delivery_id;
    let (left, right) = tokio::join!(claim(&first, id, 60_000), claim(&second, id, 60_000));
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let original = left.ok().or_else(|| right.ok()).unwrap().lease;
    let (issuer, _) = fixture(1, u64::MAX);
    let renewed = second
        .renew_authbus_delivery(&issuer, &original, 60_000)
        .await
        .unwrap();
    for stale in [&original, &renewed] {
        if stale.fence == renewed.fence {
            second
                .retry_authbus_delivery(&issuer, &renewed, 0)
                .await
                .unwrap();
        }
        assert!(matches!(
            first.renew_authbus_delivery(&issuer, stale, 60_000).await,
            Err(AuthBusOutboxError::StaleLease)
        ));
        assert!(matches!(
            first.retry_authbus_delivery(&issuer, stale, 0).await,
            Err(AuthBusOutboxError::StaleLease)
        ));
        assert!(matches!(
            first
                .ack_authbus_delivery(&issuer, stale, Digest32::of_bytes(b"ack"))
                .await,
            Err(AuthBusOutboxError::StaleLease)
        ));
    }
    let recovered = claim(&first, id, 60_000).await.unwrap();
    assert!(recovered.lease.fence > renewed.fence);
    second
        .ack_authbus_delivery(&issuer, &recovered.lease, Digest32::of_bytes(b"ack"))
        .await
        .unwrap();
}

#[tokio::test]
async fn expiry_and_current_revocation_are_terminal_and_never_acknowledged() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    let (mut issuer, message) = fixture(1, u64::MAX);
    let id = enqueue(&store, 1).await.delivery_id;
    let delivery = claim(&store, id, 60_000).await.unwrap();
    issuer.revoked = true;
    assert!(
        store
            .ack_authbus_delivery(&issuer, &delivery.lease, Digest32::of_bytes(b"ack"))
            .await
            .is_err()
    );
    assert_eq!(
        store.authbus_delivery_status(id).await.unwrap().state,
        AuthBusDeliveryState::Quarantined
    );
    let next = enqueue(&store, 2).await.delivery_id;
    assert_eq!(store.quarantine_authbus_issuer(&issuer).await.unwrap(), 1);
    assert_eq!(
        store.authbus_delivery_status(next).await.unwrap().state,
        AuthBusDeliveryState::Quarantined
    );
    let (issuer, expiring) = fixture(3, (now_millis().unwrap() + 1000) as u64);
    let id = store
        .enqueue_authbus_message(
            &issuer,
            &expiring,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"payload",
        )
        .await
        .unwrap()
        .delivery_id;
    let mut tx = store.pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
    maintain(&mut tx, expiring.claims.expires_at_ms as i64)
        .await
        .unwrap();
    tx.commit().await.unwrap();
    assert_eq!(
        store.authbus_delivery_status(id).await.unwrap().state,
        AuthBusDeliveryState::Expired
    );
    assert!(claim(&store, id, 60_000).await.is_err());
}

#[tokio::test]
async fn expired_lease_cannot_renew_retry_or_ack_before_or_after_reclaim() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    let (issuer, _) = fixture(1, u64::MAX);
    let id = enqueue(&store, 1).await.delivery_id;
    let original = claim(&store, id, 1).await.unwrap();
    tokio::time::sleep(Duration::from_millis(3)).await;
    assert!(matches!(
        store
            .renew_authbus_delivery(&issuer, &original.lease, 60_000)
            .await,
        Err(AuthBusOutboxError::StaleLease)
    ));
    assert!(matches!(
        store
            .retry_authbus_delivery(&issuer, &original.lease, 0)
            .await,
        Err(AuthBusOutboxError::StaleLease)
    ));
    assert!(matches!(
        store
            .ack_authbus_delivery(&issuer, &original.lease, Digest32::of_bytes(b"ack"))
            .await,
        Err(AuthBusOutboxError::StaleLease)
    ));
    let recovered = claim(&store, id, 60_000).await.unwrap();
    assert_eq!(recovered.lease.fence, original.lease.fence + 1);
    assert!(matches!(
        store
            .ack_authbus_delivery(&issuer, &original.lease, Digest32::of_bytes(b"ack"))
            .await,
        Err(AuthBusOutboxError::StaleLease)
    ));
    store
        .ack_authbus_delivery(&issuer, &recovered.lease, Digest32::of_bytes(b"ack"))
        .await
        .unwrap();
}

#[tokio::test]
async fn delivery_attempt_budget_quarantines_without_resending_forever() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    let (issuer, _) = fixture(1, u64::MAX);
    let id = enqueue(&store, 1).await.delivery_id;
    for _ in 0..AUTHBUS_OUTBOX_MAX_ATTEMPTS {
        let delivery = claim(&store, id, 60_000).await.unwrap();
        store
            .retry_authbus_delivery(&issuer, &delivery.lease, 0)
            .await
            .unwrap();
    }
    let status = store.authbus_delivery_status(id).await.unwrap();
    assert_eq!(
        (status.state, status.attempts),
        (AuthBusDeliveryState::Quarantined, 16)
    );
    assert!(claim(&store, id, 60_000).await.is_err());
}

#[tokio::test]
async fn bounded_capacity_prunes_only_terminal_history_and_keeps_replay_consumed() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    let id = enqueue(&store, 1).await.delivery_id;
    // Fill active capacity using copies with independent fixture identities;
    // admission hashing/signatures are exercised separately, not 4096 times.
    sqlx::query("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x < 4095)
        INSERT INTO authbus_outbox SELECT randomblob(32), issuer_id, key_epoch, 'fixture:' || x,
        subject_id, scope_digest, payload_digest, sequence, expires_at_ms, signature, payload,
        state, fence, attempts, worker_id, lease_until_ms, available_at_ms, created_at_ms,
        updated_at_ms, terminal_at_ms, acknowledgement FROM authbus_outbox, n WHERE delivery_id = ?")
        .bind(id.as_array().as_slice()).execute(&store.pool).await.unwrap();
    let (issuer, message) = fixture(2, u64::MAX);
    assert!(matches!(
        store
            .enqueue_authbus_message(
                &issuer,
                &message,
                &message.claims.subject_id,
                message.claims.scope_digest,
                b"payload"
            )
            .await,
        Err(AuthBusOutboxError::Capacity)
    ));
    assert!(
        sqlx::query("DELETE FROM authbus_outbox WHERE delivery_id = ?")
            .bind(id.as_array().as_slice())
            .execute(&store.pool)
            .await
            .is_err()
    );
    let delivery = claim(&store, id, 60_000).await.unwrap();
    store
        .ack_authbus_delivery(&issuer, &delivery.lease, Digest32::of_bytes(b"ack"))
        .await
        .unwrap();
    enqueue(&store, 2).await;
    assert!(matches!(
        store.authbus_delivery_status(id).await,
        Err(AuthBusOutboxError::NotFound)
    ));
    let (issuer, old) = fixture(1, u64::MAX);
    assert!(matches!(
        store
            .enqueue_authbus_message(
                &issuer,
                &old,
                &old.claims.subject_id,
                old.claims.scope_digest,
                b"payload"
            )
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::Replay)
        ))
    ));
    // Retire the fixture epoch, release only terminal capacity, and still reject
    // the consumed old sequence after all terminal rows are old enough to prune.
    let revoked = IssuerRegistration {
        revoked: true,
        ..issuer
    };
    store.quarantine_authbus_issuer(&revoked).await.unwrap();
    let mut tx = store.pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
    maintain(&mut tx, now_millis().unwrap() + 86_400_001)
        .await
        .unwrap();
    tx.commit().await.unwrap();
    let (issuer, old) = fixture(1, u64::MAX);
    assert!(matches!(
        store
            .enqueue_authbus_message(
                &issuer,
                &old,
                &old.claims.subject_id,
                old.claims.scope_digest,
                b"payload"
            )
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::Replay)
        ))
    ));
    enqueue(&store, 3).await;
}

#[tokio::test]
#[ignore = "subprocess crash fixture"]
async fn crash_delivery_child() {
    let home = std::path::PathBuf::from(std::env::var_os("HEPTA_AUTHBUS_CRASH_HOME").unwrap());
    let store = HeptaEvidenceStore::open(&config(&home)).await.unwrap();
    let id = enqueue(&store, 1).await.delivery_id;
    let delivery = claim(&store, id, 1).await.unwrap();
    std::fs::write(
        home.join("delivered-id"),
        delivery.lease.delivery_id().to_string(),
    )
    .unwrap();
    std::process::exit(73); // No pool close or transaction/session destructor.
}

#[tokio::test]
async fn actual_process_crash_after_send_before_ack_redelivers_same_id() {
    let temp = TempDir::new().unwrap();
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "authbus_outbox_tests::crash_delivery_child",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_AUTHBUS_CRASH_HOME", temp.path())
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(73));
    tokio::time::sleep(Duration::from_millis(3)).await;
    let id: Digest32 = std::fs::read_to_string(temp.path().join("delivered-id"))
        .unwrap()
        .parse()
        .unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    let delivery = claim(&store, id, 60_000).await.unwrap();
    assert_eq!(delivery.lease.delivery_id(), id);
    assert_eq!(delivery.lease.fence, 2);
    assert_eq!(store.authbus_delivery_status(id).await.unwrap().attempts, 2);
    let (issuer, _) = fixture(1, u64::MAX);
    store
        .ack_authbus_delivery(
            &issuer,
            &delivery.lease,
            Digest32::of_bytes(b"deduplicated receipt"),
        )
        .await
        .unwrap();
}

#[tokio::test]
async fn missing_outbox_guard_is_rejected_on_reopen() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    sqlx::query("DROP TRIGGER authbus_outbox_active_no_delete")
        .execute(&store.pool)
        .await
        .unwrap();
    store.pool.close().await;
    assert!(matches!(
        HeptaEvidenceStore::open(&sqlite).await,
        Err(EvidenceError::Corrupt(_))
    ));
}

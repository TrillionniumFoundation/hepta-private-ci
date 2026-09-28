use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_authbus_p1_3_qualification::persisted_message_issuer;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::AuthBusClaimRequest;
use crate::HeptaEvidenceStore;

fn fixture(sequence: u64) -> (IssuerRegistration, SignedMessage) {
    let key = SigningKey::from_bytes(&[73; 32]);
    let issuer = persisted_message_issuer(
        "issuer:operations",
        1,
        key.verifying_key().to_bytes(),
        false,
    )
    .expect("persisted issuer");
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!("message:operations:{sequence}"))
            .expect("message id"),
        subject_id: StableId::new("subject:operations").expect("subject id"),
        scope_digest: Digest32::of_bytes(b"operations-route"),
        payload_digest: Digest32::of_bytes(b"operations-payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (issuer, SignedMessage { claims, signature })
}

fn config(path: &std::path::Path) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(path.to_path_buf()).expect("absolute test path"),
    )
}

async fn enqueue(store: &HeptaEvidenceStore, sequence: u64) -> Digest32 {
    let (issuer, message) = fixture(sequence);
    store
        .enqueue_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"operations-payload",
        )
        .await
        .expect("enqueue")
        .delivery_id
}

#[tokio::test]
async fn snapshot_explains_backlog_retries_and_acknowledgement_latency() {
    let temp = TempDir::new().expect("temporary store");
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .expect("open evidence store");
    let first = enqueue(&store, 1).await;
    let (issuer, message) = fixture(1);
    let worker = StableId::new("worker:operations").expect("worker id");

    let first_claim = store
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: first,
                subject_id: &message.claims.subject_id,
                scope_digest: message.claims.scope_digest,
                worker_id: &worker,
                lease_ms: 60_000,
            },
        )
        .await
        .expect("first claim");
    store
        .retry_authbus_delivery(&issuer, &first_claim.lease, 0)
        .await
        .expect("release for retry");
    let second_claim = store
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: first,
                subject_id: &message.claims.subject_id,
                scope_digest: message.claims.scope_digest,
                worker_id: &worker,
                lease_ms: 60_000,
            },
        )
        .await
        .expect("second claim");
    store
        .ack_authbus_delivery(
            &issuer,
            &second_claim.lease,
            Digest32::of_bytes(b"operations-ack"),
        )
        .await
        .expect("acknowledge delivery");
    let _second = enqueue(&store, 2).await;

    let snapshot = store
        .authbus_outbox_operational_snapshot()
        .await
        .expect("operational snapshot");
    assert_eq!(snapshot.queued_deliveries, 1);
    assert_eq!(snapshot.leased_deliveries, 0);
    assert_eq!(snapshot.acknowledged_deliveries, 1);
    assert_eq!(snapshot.expired_deliveries, 0);
    assert_eq!(snapshot.quarantined_deliveries, 0);
    assert_eq!(snapshot.active_deliveries, 1);
    assert_eq!(snapshot.retained_claim_attempts, 2);
    assert_eq!(snapshot.retained_claim_retries, 1);
    assert_eq!(snapshot.exhausted_active_deliveries, 0);
    assert!(snapshot.oldest_unsettled_age_ms <= snapshot.observed_at_ms);
    assert_eq!(snapshot.acknowledgement_latency.count, 1);
    assert_eq!(
        snapshot.acknowledgement_latency.p50_ms,
        snapshot.acknowledgement_latency.max_ms
    );
    assert_eq!(
        snapshot.acknowledgement_latency.p95_ms,
        snapshot.acknowledgement_latency.max_ms
    );
    assert_eq!(
        snapshot.acknowledgement_latency.p99_ms,
        snapshot.acknowledgement_latency.max_ms
    );
}

#[tokio::test]
async fn empty_snapshot_is_zeroed_and_side_effect_free() {
    let temp = TempDir::new().expect("temporary store");
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .expect("open evidence store");
    let first = store
        .authbus_outbox_operational_snapshot()
        .await
        .expect("first snapshot");
    let second = store
        .authbus_outbox_operational_snapshot()
        .await
        .expect("second snapshot");
    assert_eq!(first.active_deliveries, 0);
    assert_eq!(first.retained_claim_attempts, 0);
    assert_eq!(first.acknowledgement_latency.count, 0);
    assert!(second.observed_at_ms >= first.observed_at_ms);
    assert_eq!(second.active_deliveries, 0);
}

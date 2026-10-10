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

use crate::*;

async fn enqueue(
    store: &HeptaEvidenceStore,
    issuer_name: &str,
    epoch: u64,
    sequence: u64,
) -> (IssuerRegistration, AuthBusDeliveryStatus) {
    let key = SigningKey::from_bytes(&[49; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new(issuer_name).unwrap(),
        key_epoch: Generation::new(epoch).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!("message:{sequence}")).unwrap(),
        subject_id: StableId::new("subject:rotating-issuer").unwrap(),
        scope_digest: Digest32::of_bytes(b"rotation route"),
        payload_digest: Digest32::of_bytes(b"rotation payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    let message = SignedMessage { claims, signature };
    let status = store
        .enqueue_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"rotation payload",
        )
        .await
        .unwrap();
    (issuer, status)
}

#[tokio::test]
async fn current_issuer_scan_cannot_be_starved_by_older_epochs_or_other_issuers() {
    let temp = TempDir::new().unwrap();
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
    );
    let store = HeptaEvidenceStore::open(&config).await.unwrap();
    let mut previous = Vec::new();
    for sequence in 1..=17 {
        previous.push(
            enqueue(&store, "issuer:rotation", /*epoch*/ 1, sequence)
                .await
                .1,
        );
    }
    let (foreign, mut foreign_status) = enqueue(
        &store,
        "issuer:other",
        /*epoch*/ 2,
        /*sequence*/ 1,
    )
    .await;
    // Make every pre-existing message sort before the new epoch, independent
    // of clock resolution or random envelope-digest ordering.
    sqlx::query("UPDATE authbus_outbox SET available_at_ms = 0, fence = fence + 1")
        .execute(&store.pool)
        .await
        .unwrap();
    for status in previous
        .iter_mut()
        .chain(std::iter::once(&mut foreign_status))
    {
        status.available_at_ms = 0;
        status.fence += 1;
    }
    let (current, current_status) = enqueue(
        &store,
        "issuer:rotation",
        /*epoch*/ 2,
        /*sequence*/ 1,
    )
    .await;
    let subject = &current_status.subject_id;
    let scope = current_status.scope_digest;
    let unfiltered = store
        .pending_authbus_deliveries(subject, scope, /*limit*/ 16)
        .await
        .unwrap();
    assert_eq!(unfiltered.len(), 16);
    assert!(
        unfiltered
            .iter()
            .all(|row| row.delivery_id != current_status.delivery_id)
    );
    assert_eq!(
        store
            .pending_authbus_deliveries_for_issuer(subject, scope, &current, /*limit*/ 1)
            .await
            .unwrap(),
        vec![current_status.clone()]
    );
    assert_eq!(
        store
            .pending_authbus_deliveries_for_issuer(subject, scope, &foreign, /*limit*/ 1)
            .await
            .unwrap(),
        vec![foreign_status]
    );
    // Selecting a newly installed epoch does not imply revoking the old one.
    let old = IssuerRegistration {
        key_epoch: Generation::new(1).unwrap(),
        ..current
    };
    let mut retained = store
        .pending_authbus_deliveries_for_issuer(subject, scope, &old, /*limit*/ 128)
        .await
        .unwrap();
    previous.sort_by_key(|row| row.delivery_id.to_string());
    retained.sort_by_key(|row| row.delivery_id.to_string());
    assert_eq!(retained, previous);
}

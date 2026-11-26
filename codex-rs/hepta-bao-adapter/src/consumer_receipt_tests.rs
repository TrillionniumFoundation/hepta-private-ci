//! Real FULL SQL original receipt/ACK and uncertainty qualification.
use super::ConsumerPortError;
use super::consumer_owner::CredentialConsumerOwner;
use super::consumer_receipt_wire::PreparedCredentialUse;
use super::consumer_receipt_wire::SignedPreparedCredentialUse;
use super::consumer_wire::ConsumerIntent;
use crate::BaoSecretReceipt;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::time::Duration;
type Result<T = ()> = std::result::Result<T, Box<dyn std::error::Error>>;
fn token(operation: &str, key: &SigningKey) -> Result<SignedPreparedCredentialUse> {
    let preparation = PreparedCredentialUse {
        intent: ConsumerIntent {
            schema_version: 1,
            consumer_id: "actual-receipt-consumer".into(),
            operation_id: operation.into(),
            semantic_sha256: [1; 32],
        },
        receipt: BaoSecretReceipt {
            request_sha256: [2; 32],
            response_sha256: [3; 32],
            secret_sha256: Digest32::of_bytes(b"actual-credential").into_array(),
            version: 1,
            secret_bytes: 17,
        },
        grant_sha256: [4; 32],
        approval_sha256: [5; 32],
        nonce: [6; 32],
        expires_at_ms: 50_000,
    };
    let signature = key.sign(&preparation.signing_bytes()?).to_bytes().to_vec();
    Ok(SignedPreparedCredentialUse {
        preparation,
        signature,
    })
}
fn time(wall: u64, revision: u64) -> Result<SignedTrustedTimeAttestation> {
    let claims = TrustedTimeAttestationClaims {
        issuer_id: StableId::new("independent-time")?,
        key_epoch: Generation::new(1)?,
        wall_time_ms: wall,
        source_revision: revision,
        source_digest: Digest32::from_array([7; 32]),
    };
    let signature = SigningKey::from_bytes(&[91; 32])
        .sign(&claims.signing_bytes())
        .to_bytes();
    Ok(SignedTrustedTimeAttestation { claims, signature })
}
#[tokio::test]
async fn original_receipt_ack_survives_restart_and_cannot_rebind() -> Result {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("consumer.sqlite");
    let key = SigningKey::from_bytes(&[83; 32]);
    let owner = CredentialConsumerOwner::open(&path, key.verifying_key().to_bytes()).await?;
    owner.enroll_receipt_profile([8; 32]).await?;
    let original = token("original-receipt", &key)?;
    assert_eq!(
        serde_json::to_value(
            owner
                .retain_preparation(&original, &time(1_000, 1)?)
                .await?
                .0
        )?,
        serde_json::to_value(&original)?
    );
    assert!(
        owner
            .receipt_status(&original.preparation.intent)
            .await?
            .is_none()
    );
    original.preparation.verify_proof(
        b"actual-credential",
        &original.preparation.proof(b"actual-credential")?,
    )?;
    let ack = owner
        .acknowledge(&original.preparation.intent, &key)
        .await?;
    owner.close().await;
    let owner = CredentialConsumerOwner::open(&path, key.verifying_key().to_bytes()).await?;
    owner.enroll_receipt_profile([8; 32]).await?;
    assert_eq!(
        serde_json::to_value(owner.receipt_preparation("original-receipt").await?)?,
        serde_json::to_value(Some(&original))?
    );
    assert_eq!(
        serde_json::to_value(owner.receipt_status(&original.preparation.intent).await?)?,
        serde_json::to_value(Some(&ack))?
    );
    let mut replacement = original.clone();
    replacement.preparation.receipt.response_sha256 = [19; 32];
    replacement.signature = key
        .sign(&replacement.preparation.signing_bytes()?)
        .to_bytes()
        .to_vec();
    assert!(matches!(
        owner
            .retain_preparation(&replacement, &time(1_001, 2)?)
            .await,
        Err(ConsumerPortError::Conflict)
    ));
    assert_eq!(
        serde_json::to_value(owner.receipt_status(&original.preparation.intent).await?)?,
        serde_json::to_value(Some(&ack))?
    );
    owner.close().await;
    Ok(())
}
#[tokio::test]
async fn retained_legacy_ack_cannot_gain_receipt_settlement_qualification() -> Result {
    let directory = tempfile::tempdir()?;
    let key = SigningKey::from_bytes(&[83; 32]);
    let owner = CredentialConsumerOwner::open(
        &directory.path().join("consumer.sqlite"),
        key.verifying_key().to_bytes(),
    )
    .await?;
    let original = token("legacy-original", &key)?;
    let intent = &original.preparation.intent;
    let ack = owner
        .authenticate(
            intent,
            b"actual-credential",
            &intent.proof(b"actual-credential")?,
            &key,
        )
        .await?;
    owner.enroll_receipt_profile([8; 32]).await?;
    assert!(matches!(
        owner.retain_preparation(&original, &time(1_000, 1)?).await,
        Err(ConsumerPortError::Conflict)
    ));
    assert!(owner.receipt_status(intent).await?.is_none());
    assert_eq!(
        serde_json::to_value(owner.status(intent).await?)?,
        serde_json::to_value(Some(&ack))?
    );
    owner.close().await;
    Ok(())
}
#[tokio::test]
async fn cancelled_receipt_transaction_fences_writes_but_retains_original_status() -> Result {
    let directory = tempfile::tempdir()?;
    let key = SigningKey::from_bytes(&[83; 32]);
    let owner = Arc::new(
        CredentialConsumerOwner::open(
            &directory.path().join("consumer.sqlite"),
            key.verifying_key().to_bytes(),
        )
        .await?,
    );
    owner.enroll_receipt_profile([8; 32]).await?;
    let original = token("retained-before-timeout", &key)?;
    owner
        .retain_preparation(&original, &time(1_000, 1)?)
        .await?;
    let ack = owner
        .acknowledge(&original.preparation.intent, &key)
        .await?;
    let mut lock = owner.pool.acquire().await?;
    sqlx::query("BEGIN IMMEDIATE").execute(&mut *lock).await?;
    let uncertain = token("uncertain-original", &key)?;
    assert!(
        tokio::time::timeout(
            Duration::from_millis(40),
            owner.retain_preparation(&uncertain, &time(1_001, 2)?)
        )
        .await
        .is_err()
    );
    sqlx::query("ROLLBACK").execute(&mut *lock).await?;
    drop(lock);
    assert!(matches!(
        owner.retain_preparation(&uncertain, &time(1_002, 3)?).await,
        Err(ConsumerPortError::Unavailable)
    ));
    assert_eq!(
        serde_json::to_value(owner.receipt_status(&original.preparation.intent).await?)?,
        serde_json::to_value(Some(&ack))?
    );
    owner.close().await;
    Ok(())
}
#[tokio::test]
async fn protected_source_rollback_fences_receipt_writer_without_deleting_ack() -> Result {
    let directory = tempfile::tempdir()?;
    let key = SigningKey::from_bytes(&[83; 32]);
    let owner = CredentialConsumerOwner::open(
        &directory.path().join("consumer.sqlite"),
        key.verifying_key().to_bytes(),
    )
    .await?;
    owner.enroll_receipt_profile([8; 32]).await?;
    let original = token("before-source-rollback", &key)?;
    owner
        .retain_preparation(&original, &time(1_000, 1)?)
        .await?;
    let ack = owner
        .acknowledge(&original.preparation.intent, &key)
        .await?;
    assert!(matches!(
        owner
            .retain_preparation(&token("after-rollback", &key)?, &time(999, 2)?)
            .await,
        Err(ConsumerPortError::Unavailable)
    ));
    assert_eq!(
        serde_json::to_value(owner.receipt_status(&original.preparation.intent).await?)?,
        serde_json::to_value(Some(&ack))?
    );
    owner.close().await;
    Ok(())
}

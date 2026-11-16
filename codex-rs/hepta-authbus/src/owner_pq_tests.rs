use super::*;
use crate::AuthBusAlgorithm;
use crate::AuthBusVerifyingKey;
use crate::TrustedTimeAttestationClaims;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[tokio::test]
async fn pq_owner_ports_keep_the_writer_lease_checkpoint_and_algorithm_profile()
-> Result<(), Box<dyn std::error::Error>> {
    let database_root = tempfile::tempdir()?;
    let checkpoint_root = tempfile::tempdir()?;
    for root in [&database_root, &checkpoint_root] {
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
    }
    let database = database_root
        .path()
        .canonicalize()?
        .join("authority.sqlite");
    let checkpoint = checkpoint_root
        .path()
        .canonicalize()?
        .join("authority-checkpoint.json");
    let owner =
        AuthBusAuthorityOwner::bootstrap_new_pq(&database, checkpoint.clone(), "pq-owner-test")
            .await?;
    assert!(matches!(
        AuthBusAuthorityOwner::open_pq(&database, checkpoint.clone(), "pq-owner-test").await,
        Err(AuthBusAuthorityError::WriterLeaseHeld)
    ));
    let spki = PqNativeSigningKey::public_spki_from_seed(&[79; 32].into());
    let key =
        PqNativeSigningKey::from_owned_seed([79; 32].into(), ml_dsa_65_key_id_from_spki(&spki)?)?;
    let issuer_id = StableId::new("issuer:pq-owner-time")?;
    let key_epoch = Generation::new(1)?;
    owner
        .admin()
        .enroll_issuer(
            IssuerPurpose::TrustedTime,
            IssuerSpec {
                issuer_id: issuer_id.clone(),
                key_epoch,
                verifying_key: AuthBusVerifyingKey::from_pq_spki(key.public_spki())?,
            },
        )
        .await?;
    let challenge = owner
        .effects()
        .trusted_time_challenge()
        .await?
        .ok_or("PQ owner must issue a freshness challenge")?;
    let claims = TrustedTimeAttestationClaims {
        issuer_id: issuer_id.clone(),
        key_epoch,
        wall_time_ms: u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?,
        source_revision: 1,
        source_digest: Digest32::of_bytes(b"independent-pq-owner-time"),
        challenge: Some(challenge),
    };
    let attestation = SignedTrustedTimeAttestation {
        signature: key
            .sign_exact_message(&claims.signing_bytes_for(AuthBusAlgorithm::MlDsa65V2))?
            .into(),
        claims,
    };
    let sample = owner
        .effects()
        .observe_trusted_time_attestation(&attestation)
        .await?;
    assert_eq!(sample.source_revision(), 1);
    assert!(matches!(
        owner
            .effects()
            .observe_trusted_time_attestation(&attestation)
            .await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness)
    ));
    drop(owner);
    assert!(matches!(
        AuthBusAuthorityOwner::open(&database, checkpoint.clone(), "pq-owner-test").await,
        Err(AuthBusAuthorityError::CryptoProfileMismatch)
    ));
    let reopened = AuthBusAuthorityOwner::open_pq(&database, checkpoint, "pq-owner-test").await?;
    let record = reopened
        .read()
        .issuer_record(IssuerPurpose::TrustedTime, &issuer_id, key_epoch)
        .await?;
    assert_eq!(record.state, crate::IssuerLifecycleState::Active);
    assert_eq!(
        record.verifying_key.algorithm(),
        AuthBusAlgorithm::MlDsa65V2
    );
    Ok(())
}

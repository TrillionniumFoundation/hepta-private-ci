use std::path::PathBuf;

use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::Error as AdmissionError;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::PolicySpec;
use codex_hepta_authbus::QuotaSpec;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::SettlementEvidenceClaims;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_authbus::SignedSettlementEvidence;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn legacy_cases() -> Vec<CaseEvidence> {
    [
        NegativeCase::Expired,
        NegativeCase::Revoked,
        NegativeCase::Replay,
        NegativeCase::PayloadDrift,
    ]
    .into_iter()
    .enumerate()
    .map(|(index, case)| CaseEvidence {
        case,
        case_id: id(&format!("case:{index}")),
        rejected: true,
        evidence_digest: Digest32::of_bytes(format!("evidence:{index}").as_bytes()),
    })
    .collect()
}

fn authority_evidence(case: AuthorityCase, label: &str) -> AuthorityCaseEvidence {
    AuthorityCaseEvidence {
        case,
        case_id: id(&format!("authority-case:{label}")),
        rejected_or_verified: true,
        evidence_digest: Digest32::of_bytes(format!("authority-evidence:{label}").as_bytes()),
    }
}

#[cfg(unix)]
fn private_paths() -> (TempDir, PathBuf, PathBuf) {
    use std::os::unix::fs::PermissionsExt;

    let root = TempDir::new().expect("temporary root");
    let database_root = root.path().join("database");
    let checkpoint_root = root.path().join("checkpoint");
    std::fs::create_dir_all(&database_root).expect("database root");
    std::fs::create_dir_all(&checkpoint_root).expect("checkpoint root");
    std::fs::set_permissions(&database_root, std::fs::Permissions::from_mode(0o700))
        .expect("database permissions");
    std::fs::set_permissions(&checkpoint_root, std::fs::Permissions::from_mode(0o700))
        .expect("checkpoint permissions");
    (
        root,
        database_root.join("authority.sqlite"),
        checkpoint_root.join("authority-checkpoint.json"),
    )
}

fn signed_time(
    key: &SigningKey,
    issuer_id: &StableId,
    revision: u64,
    wall_time_ms: u64,
) -> SignedTrustedTimeAttestation {
    let claims = TrustedTimeAttestationClaims {
        issuer_id: issuer_id.clone(),
        key_epoch: Generation::new(1).expect("trusted-time epoch"),
        wall_time_ms,
        source_revision: revision,
        source_digest: Digest32::of_bytes(
            format!("qualification-time:{revision}:{wall_time_ms}").as_bytes(),
        ),
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    SignedTrustedTimeAttestation { claims, signature }
}

async fn time_sample(
    host: &AuthBusAuthorityHost,
    key: &SigningKey,
    issuer_id: &StableId,
    revision: u64,
    wall_time_ms: u64,
) -> codex_hepta_authbus::TrustedTimeSample {
    host.observe_trusted_time_attestation(&signed_time(key, issuer_id, revision, wall_time_ms))
        .await
        .expect("observe trusted time")
}

#[test]
fn complete_negative_matrix_qualifies_without_authority() {
    let Ok(receipt) = qualify(legacy_cases()) else {
        panic!("complete matrix must qualify");
    };
    assert_eq!(receipt.case_count, 4);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn missing_case_is_rejected() {
    let mut value = legacy_cases();
    value.pop();
    assert_eq!(qualify(value), Err(Error::MissingRequiredCase));
}

#[test]
fn unexpected_success_fails_qualification() {
    let mut value = legacy_cases();
    value[0].rejected = false;
    assert_eq!(
        qualify(value),
        Err(Error::CaseDidNotReject("case:0".to_string()))
    );
}

#[test]
fn persisted_registration_rejects_forged_revoked_and_epoch_substitution() {
    let trusted_key = SigningKey::from_bytes(&[31; 32]);
    let forged_key = SigningKey::from_bytes(&[32; 32]);
    let trusted = persisted_message_issuer(
        "issuer:qualification-message",
        1,
        trusted_key.verifying_key().to_bytes(),
        false,
    )
    .expect("persisted trusted registration");
    let claims = SignedMessageClaims {
        issuer_id: trusted.issuer_id.clone(),
        key_epoch: trusted.key_epoch,
        message_id: id("message:qualification"),
        subject_id: id("subject:qualification"),
        scope_digest: Digest32::of_bytes(b"qualification-scope"),
        payload_digest: Digest32::of_bytes(b"qualification-payload"),
        sequence: 1,
        expires_at_ms: 5_000,
    };
    let legitimate = SignedMessage {
        signature: trusted_key.sign(&claims.signing_bytes()).to_bytes(),
        claims: claims.clone(),
    };
    legitimate
        .authenticate(&trusted, claims.scope_digest, claims.payload_digest, 1_000)
        .expect("trusted registration authenticates");

    let forged = SignedMessage {
        signature: forged_key.sign(&claims.signing_bytes()).to_bytes(),
        claims: claims.clone(),
    };
    assert!(matches!(
        forged.authenticate(&trusted, claims.scope_digest, claims.payload_digest, 1_000,),
        Err(AdmissionError::InvalidSignature)
    ));

    let revoked = persisted_message_issuer(
        "issuer:qualification-message",
        1,
        trusted_key.verifying_key().to_bytes(),
        true,
    )
    .expect("persisted revoked registration");
    assert!(matches!(
        legitimate.authenticate(&revoked, claims.scope_digest, claims.payload_digest, 1_000,),
        Err(AdmissionError::Revoked)
    ));

    let wrong_epoch = persisted_message_issuer(
        "issuer:qualification-message",
        2,
        trusted_key.verifying_key().to_bytes(),
        false,
    )
    .expect("persisted alternate epoch");
    assert!(matches!(
        legitimate.authenticate(
            &wrong_epoch,
            claims.scope_digest,
            claims.payload_digest,
            1_000,
        ),
        Err(AdmissionError::IssuerMismatch)
    ));
}

#[cfg(unix)]
#[tokio::test]
async fn authority_host_executes_modern_owner_purpose_sweep_and_settlement_matrix() {
    let (_root, database, checkpoint) = private_paths();
    let host =
        AuthBusAuthorityHost::bootstrap(&database, checkpoint.clone(), "qualification-owner")
            .await
            .expect("bootstrap authority host");
    assert!(matches!(
        AuthBusAuthorityHost::open(&database, checkpoint.clone(), "qualification-owner").await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));

    let message_key = SigningKey::from_bytes(&[41; 32]);
    let settlement_key = SigningKey::from_bytes(&[42; 32]);
    let time_key = SigningKey::from_bytes(&[43; 32]);
    let shared_issuer_id = id("issuer:qualification-shared");
    let time_issuer_id = id("issuer:qualification-time");
    host.enroll_issuer(
        IssuerPurpose::Message,
        IssuerSpec {
            issuer_id: shared_issuer_id.clone(),
            key_epoch: Generation::new(1).expect("message epoch"),
            verifying_key: message_key.verifying_key(),
        },
    )
    .await
    .expect("enroll message issuer");
    assert!(matches!(
        host.settlement_issuer(
            &shared_issuer_id,
            Generation::new(1).expect("message epoch"),
        )
        .await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
    host.enroll_issuer(
        IssuerPurpose::Settlement,
        IssuerSpec {
            issuer_id: shared_issuer_id.clone(),
            key_epoch: Generation::new(1).expect("settlement epoch"),
            verifying_key: settlement_key.verifying_key(),
        },
    )
    .await
    .expect("enroll settlement issuer");
    host.enroll_issuer(
        IssuerPurpose::TrustedTime,
        IssuerSpec {
            issuer_id: time_issuer_id.clone(),
            key_epoch: Generation::new(1).expect("time epoch"),
            verifying_key: time_key.verifying_key(),
        },
    )
    .await
    .expect("enroll trusted-time issuer");

    let scope = Digest32::of_bytes(b"qualification-provider-scope");
    let policy = host
        .create_policy(
            PolicySpec {
                policy_id: id("policy:qualification-provider"),
                principal: id("principal:qualification-agent"),
                action: id("action:qualification-provider-call"),
                scope_digest: scope,
                effect: PolicyEffect::Allow,
                not_before_ms: 1_000,
                expires_at_ms: 10_000,
            },
            time_sample(&host, &time_key, &time_issuer_id, 1, 1_100).await,
        )
        .await
        .expect("create policy");
    let decision = host
        .authorize(
            &policy.principal,
            &policy.action,
            scope,
            policy.revision,
            time_sample(&host, &time_key, &time_issuer_id, 2, 1_200).await,
        )
        .await
        .expect("authorize provider call");
    let quota = host
        .create_quota(
            QuotaSpec {
                quota_key: id("quota:qualification-provider"),
                principal: policy.principal.clone(),
                scope_digest: scope,
                unit: id("unit:qualification-request"),
                period_id: id("period:qualification"),
                limit: 10,
            },
            time_sample(&host, &time_key, &time_issuer_id, 3, 1_300).await,
        )
        .await
        .expect("create quota");

    let expiring = host
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: quota.quota_key.clone(),
                operation_id: id("operation:qualification-expiring"),
                amount: 2,
                effect_digest: Digest32::of_bytes(b"effect:qualification-expiring"),
                expected_quota_revision: quota.revision,
                expires_at_ms: 1_500,
            },
            time_sample(&host, &time_key, &time_issuer_id, 4, 1_400).await,
        )
        .await
        .expect("reserve expiring quota");
    let sweep = host
        .sweep_expired_reservations(
            time_sample(&host, &time_key, &time_issuer_id, 5, 1_600).await,
            1,
        )
        .await
        .expect("sweep expired reservation");
    assert_eq!(sweep.examined, 1);
    assert_eq!(sweep.expired_held, 1);
    assert_eq!(
        host.reservation(&expiring.reservation_id)
            .await
            .expect("expired reservation")
            .state,
        ReservationState::Expired
    );

    let quota_after_sweep = host
        .quota_snapshot(&quota.quota_key)
        .await
        .expect("quota after sweep");
    let reservation = host
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: quota.quota_key.clone(),
                operation_id: id("operation:qualification-settlement"),
                amount: 5,
                effect_digest: Digest32::of_bytes(b"effect:qualification-settlement"),
                expected_quota_revision: quota_after_sweep.revision,
                expires_at_ms: 8_000,
            },
            time_sample(&host, &time_key, &time_issuer_id, 6, 1_700).await,
        )
        .await
        .expect("reserve settlement quota");
    let dispatched = host
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            reservation.effect_digest,
            time_sample(&host, &time_key, &time_issuer_id, 7, 1_800).await,
        )
        .await
        .expect("persist dispatch fence");
    let settlement_issuer = host
        .settlement_issuer(
            &shared_issuer_id,
            Generation::new(1).expect("settlement epoch"),
        )
        .await
        .expect("resolve settlement issuer");
    let settlement_claims = SettlementEvidenceClaims {
        issuer_id: settlement_issuer.issuer_id.clone(),
        key_epoch: settlement_issuer.key_epoch,
        reservation_id: dispatched.reservation_id.clone(),
        operation_id: dispatched.operation_id.clone(),
        status: SettlementStatus::Completed,
        observed_cost: 4,
        terminal_evidence_digest: Digest32::of_bytes(b"qualification-terminal-evidence"),
        observed_at_ms: 1_900,
        expires_at_ms: 5_000,
    };
    let settlement_evidence = SignedSettlementEvidence {
        signature: settlement_key
            .sign(&settlement_claims.signing_bytes())
            .to_bytes(),
        claims: settlement_claims,
    };
    let settled = host
        .settle(
            &settlement_issuer,
            &settlement_evidence,
            time_sample(&host, &time_key, &time_issuer_id, 8, 1_900).await,
        )
        .await
        .expect("settle reservation");
    assert_eq!(settled.state, ReservationState::Settled);
    assert_eq!(settled.observed_cost, 4);

    let cases = vec![
        authority_evidence(AuthorityCase::ForgedKey, "forged-key"),
        authority_evidence(AuthorityCase::RevokedKey, "revoked-key"),
        authority_evidence(AuthorityCase::EpochSubstitution, "epoch-substitution"),
        authority_evidence(AuthorityCase::PurposeSubstitution, "purpose-substitution"),
        authority_evidence(AuthorityCase::FakeQuarantine, "fake-quarantine"),
        authority_evidence(AuthorityCase::OwnerCollision, "owner-collision"),
        authority_evidence(
            AuthorityCase::ExpiredReservationSweep,
            "expired-reservation-sweep",
        ),
        authority_evidence(AuthorityCase::ProductSettlement, "product-settlement"),
    ];
    let receipt = qualify_authority(cases).expect("modern authority matrix qualifies");
    assert_eq!(receipt.case_count, 8);
    assert!(!receipt.authority.grants_any());
}

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::PolicyDecision;
use crate::PolicySpec;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::SettlementEvidenceClaims;
use crate::SignedSettlementEvidence;
use codex_hepta_types::Generation;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identifier")
}

fn sample(revision: u64, wall_time_ms: u64) -> TrustedTimeSample {
    TrustedTimeSample::new(
        wall_time_ms,
        revision,
        Digest32::of_bytes(format!("trusted-time:{revision}:{wall_time_ms}").as_bytes()),
    )
    .expect("valid trusted time")
}

async fn configured() -> (
    TempDir,
    AuthBusAuthorityStore,
    PolicyDecision,
    QuotaReservation,
) {
    let root = TempDir::new().expect("temp dir");
    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    let scope = Digest32::of_bytes(b"provider-scope");
    let policy = store
        .create_policy(
            PolicySpec {
                policy_id: id("policy:provider"),
                principal: id("principal:agent"),
                action: id("action:provider.call"),
                scope_digest: scope,
                effect: PolicyEffect::Allow,
                not_before_ms: 1_000,
                expires_at_ms: 10_000,
            },
            sample(1, 1_100),
        )
        .await
        .expect("create policy");
    let decision = store
        .authorize(
            &policy.principal,
            &policy.action,
            scope,
            /*policy_revision*/ 1,
            sample(2, 1_200),
        )
        .await
        .expect("authorize");
    let quota = store
        .create_quota(
            QuotaSpec {
                quota_key: id("quota:provider"),
                principal: policy.principal,
                scope_digest: scope,
                unit: id("unit:request"),
                period_id: id("period:one"),
                limit: 10,
            },
            sample(3, 1_300),
        )
        .await
        .expect("create quota");
    let reservation = store
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: quota.quota_key,
                operation_id: id("operation:one"),
                amount: 7,
                expected_quota_revision: 1,
                expires_at_ms: 5_000,
            },
            sample(4, 1_400),
        )
        .await
        .expect("reserve");
    (root, store, decision, reservation)
}

fn issuer(key: &SigningKey) -> SettlementIssuerRegistration {
    SettlementIssuerRegistration {
        issuer_id: id("issuer:settlement"),
        key_epoch: Generation::new(1).expect("generation"),
        verifying_key: key.verifying_key(),
        revoked: false,
    }
}

fn evidence(
    key: &SigningKey,
    reservation: &QuotaReservation,
    status: SettlementStatus,
    observed_cost: u64,
    observed_at_ms: u64,
) -> SignedSettlementEvidence {
    let claims = SettlementEvidenceClaims {
        issuer_id: id("issuer:settlement"),
        key_epoch: Generation::new(1).expect("generation"),
        reservation_id: reservation.reservation_id.clone(),
        operation_id: reservation.operation_id.clone(),
        status,
        observed_cost,
        terminal_evidence_digest: Digest32::of_bytes(b"provider-terminal-evidence"),
        observed_at_ms,
        expires_at_ms: observed_at_ms + 2_000,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    SignedSettlementEvidence { claims, signature }
}

#[tokio::test]
async fn completed_settlement_is_conservative_and_idempotent() {
    let (_root, store, _decision, reservation) = configured().await;
    let dispatched = store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            /*expected_revision*/ 1,
            Digest32::of_bytes(b"dispatch"),
            sample(5, 1_500),
        )
        .await
        .expect("mark dispatch");
    let key = SigningKey::from_bytes(&[9; 32]);
    let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 1_600);
    let settled = store
        .settle(&issuer(&key), &signed, sample(6, 1_600))
        .await
        .expect("settle");
    assert_eq!(settled.state, ReservationState::Settled);
    assert_eq!(settled.observed_cost, 5);
    assert!(!settled.authority.grants_any());
    assert_eq!(
        store
            .quota_snapshot(&reservation.quota_key)
            .await
            .expect("quota snapshot"),
        QuotaSnapshot {
            quota_key: reservation.quota_key.clone(),
            principal: reservation.principal.clone(),
            scope_digest: Digest32::of_bytes(b"provider-scope"),
            unit: id("unit:request"),
            period_id: id("period:one"),
            limit: 10,
            available: 5,
            reserved: 0,
            consumed: 5,
            revision: 3,
        }
    );
    assert_eq!(
        store
            .settle(&issuer(&key), &signed, sample(7, 1_700))
            .await
            .expect("exact settlement retry"),
        settled
    );
    let changed = evidence(&key, &dispatched, SettlementStatus::Completed, 4, 1_600);
    assert!(matches!(
        store.settle(&issuer(&key), &changed, sample(8, 1_800)).await,
        Err(AuthBusAuthorityError::IdempotencyConflict)
    ));
}

#[tokio::test]
async fn unknown_expired_effect_keeps_reserve_until_signed_terminal_evidence() {
    let (_root, store, _decision, reservation) = configured().await;
    let dispatched = store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            /*expected_revision*/ 1,
            Digest32::of_bytes(b"dispatch"),
            sample(5, 1_500),
        )
        .await
        .expect("mark dispatch");
    let indeterminate = store
        .reconcile_expired_reservation(
            &reservation.reservation_id,
            /*expected_revision*/ 2,
            sample(6, 5_100),
        )
        .await
        .expect("expire after dispatch");
    assert_eq!(indeterminate.state, ReservationState::Indeterminate);
    let held = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota snapshot");
    assert_eq!((held.available, held.reserved, held.consumed), (3, 7, 0));

    let key = SigningKey::from_bytes(&[10; 32]);
    let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 5_200);
    store
        .settle(&issuer(&key), &signed, sample(7, 5_200))
        .await
        .expect("late terminal settlement");
    let closed = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota snapshot");
    assert_eq!((closed.available, closed.reserved, closed.consumed), (5, 0, 5));
}

#[tokio::test]
async fn revoked_policy_blocks_dispatch_and_held_expiry_refunds() {
    let (_root, store, decision, reservation) = configured().await;
    store
        .revoke_policy(
            decision.policy_id(),
            /*expected_revision*/ 1,
            sample(5, 1_500),
        )
        .await
        .expect("revoke policy");
    assert!(matches!(
        store
            .mark_dispatch_attempted(
                &reservation.reservation_id,
                /*expected_revision*/ 1,
                Digest32::of_bytes(b"dispatch"),
                sample(6, 1_600),
            )
            .await,
        Err(AuthBusAuthorityError::PolicyUnavailable)
    ));
    let expired = store
        .reconcile_expired_reservation(
            &reservation.reservation_id,
            /*expected_revision*/ 1,
            sample(7, 5_100),
        )
        .await
        .expect("refund undispatched expiry");
    assert_eq!(expired.state, ReservationState::Expired);
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota snapshot");
    assert_eq!((quota.available, quota.reserved, quota.consumed), (10, 0, 0));
}

use codex_hepta_authbus::AuthPolicy;
use codex_hepta_authbus::QuotaDefinition;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::TrustedTime;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::*;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn time(now_ms: u64) -> TrustedTime {
    TrustedTime {
        source_id: id("clock:test"),
        generation: 1,
        now_ms,
        uncertainty_ms: 0,
    }
}

#[tokio::test]
async fn policy_revisions_are_monotone_and_authorization_fails_closed() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let scope = Digest32::of_bytes(b"scope");
    let mut policy = AuthPolicy {
        policy_id: id("policy:one"),
        principal_id: id("principal:one"),
        action_id: id("action:read"),
        scope_digest: scope,
        revision: 1,
        allowed: true,
        revoked: false,
    };
    store.publish_authbus_policy(&policy).await.unwrap();
    let decision = store
        .authorize_authbus(
            &policy.principal_id,
            &policy.action_id,
            scope,
            1,
        )
        .await
        .unwrap();
    assert!(decision.allowed);

    assert!(matches!(
        store
            .authorize_authbus(
                &policy.principal_id,
                &policy.action_id,
                scope,
                2,
            )
            .await,
        Err(AuthBusAuthorityError::StaleRevision)
    ));

    policy.revision = 2;
    policy.revoked = true;
    store.publish_authbus_policy(&policy).await.unwrap();
    assert!(matches!(
        store
            .authorize_authbus(
                &policy.principal_id,
                &policy.action_id,
                scope,
                2,
            )
            .await,
        Err(AuthBusAuthorityError::Denied)
    ));
}

#[tokio::test]
async fn simultaneous_last_unit_reservations_cannot_both_succeed() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let quota = QuotaDefinition {
        quota_key: id("quota:last-unit"),
        limit: 1,
        revision: 1,
    };
    first.configure_authbus_quota(&quota).await.unwrap();
    let left = first.reserve_authbus_quota(
        id("reservation:left"),
        quota.quota_key.clone(),
        id("operation:left"),
        1,
        1,
        10_000,
        &time(1_000),
    );
    let right = second.reserve_authbus_quota(
        id("reservation:right"),
        quota.quota_key.clone(),
        id("operation:right"),
        1,
        1,
        10_000,
        &time(1_000),
    );
    let (left, right) = tokio::join!(left, right);
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let status = first.authbus_quota_status(&quota.quota_key).await.unwrap();
    assert_eq!((status.available, status.reserved, status.consumed), (0, 1, 0));
}

#[tokio::test]
async fn settlement_is_conservation_safe_and_exact_retry_is_idempotent() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let quota = QuotaDefinition {
        quota_key: id("quota:settlement"),
        limit: 10,
        revision: 1,
    };
    store.configure_authbus_quota(&quota).await.unwrap();
    let reservation = store
        .reserve_authbus_quota(
            id("reservation:settlement"),
            quota.quota_key.clone(),
            id("operation:settlement"),
            7,
            1,
            10_000,
            &time(1_000),
        )
        .await
        .unwrap();
    assert_eq!(reservation.state, ReservationState::Held);
    let evidence = Digest32::of_bytes(b"provider terminal");
    let settled = store
        .reconcile_authbus_reservation(
            &reservation.reservation_id,
            evidence,
            AuthBusSettlementOutcome::Applied { observed_cost: 5 },
            &time(2_000),
        )
        .await
        .unwrap();
    assert_eq!(settled.state, ReservationState::Settled);
    assert_eq!(settled.observed_cost, Some(5));
    let status = store.authbus_quota_status(&quota.quota_key).await.unwrap();
    assert_eq!(
        (status.limit, status.available, status.reserved, status.consumed),
        (10, 5, 0, 5)
    );

    let retry = store
        .reconcile_authbus_reservation(
            &reservation.reservation_id,
            evidence,
            AuthBusSettlementOutcome::Applied { observed_cost: 5 },
            &time(2_100),
        )
        .await
        .unwrap();
    assert_eq!(retry, settled);
    assert!(matches!(
        store
            .reconcile_authbus_reservation(
                &reservation.reservation_id,
                evidence,
                AuthBusSettlementOutcome::Applied { observed_cost: 6 },
                &time(2_200),
            )
            .await,
        Err(AuthBusAuthorityError::Conflict)
    ));
}

#[tokio::test]
async fn expiry_and_unknown_effect_keep_the_hold_until_reconciliation() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let quota = QuotaDefinition {
        quota_key: id("quota:expiry"),
        limit: 9,
        revision: 1,
    };
    store.configure_authbus_quota(&quota).await.unwrap();
    let reservation = store
        .reserve_authbus_quota(
            id("reservation:expiry"),
            quota.quota_key.clone(),
            id("operation:expiry"),
            7,
            1,
            2_000,
            &time(1_000),
        )
        .await
        .unwrap();
    assert_eq!(store.expire_authbus_reservations(&time(2_000), 32).await.unwrap(), 1);
    let status = store.authbus_quota_status(&quota.quota_key).await.unwrap();
    assert_eq!((status.available, status.reserved, status.consumed), (2, 7, 0));

    let reconciled = store
        .reconcile_authbus_reservation(
            &reservation.reservation_id,
            Digest32::of_bytes(b"proven not applied"),
            AuthBusSettlementOutcome::NotApplied,
            &time(2_100),
        )
        .await
        .unwrap();
    assert_eq!(reconciled.state, ReservationState::Cancelled);
    let status = store.authbus_quota_status(&quota.quota_key).await.unwrap();
    assert_eq!((status.available, status.reserved, status.consumed), (9, 0, 0));
}

#[tokio::test]
async fn observed_cost_overrun_keeps_reservation_indeterminate_and_held() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let quota = QuotaDefinition {
        quota_key: id("quota:overrun"),
        limit: 10,
        revision: 1,
    };
    store.configure_authbus_quota(&quota).await.unwrap();
    let reservation = store
        .reserve_authbus_quota(
            id("reservation:overrun"),
            quota.quota_key.clone(),
            id("operation:overrun"),
            4,
            1,
            10_000,
            &time(1_000),
        )
        .await
        .unwrap();
    assert!(matches!(
        store
            .reconcile_authbus_reservation(
                &reservation.reservation_id,
                Digest32::of_bytes(b"provider-overrun"),
                AuthBusSettlementOutcome::Applied { observed_cost: 5 },
                &time(2_000),
            )
            .await,
        Err(AuthBusAuthorityError::UsageOverrun)
    ));
    let status = store.authbus_quota_status(&quota.quota_key).await.unwrap();
    assert_eq!((status.available, status.reserved, status.consumed), (6, 4, 0));
    let row: String = sqlx::query_scalar(
        "SELECT state FROM authbus_quota_reservations WHERE reservation_id = ?",
    )
    .bind(reservation.reservation_id.as_str())
    .fetch_one(&store.pool)
    .await
    .unwrap();
    assert_eq!(row, "indeterminate");
}

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;

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

fn policy() -> PolicySpec {
    PolicySpec {
        policy_id: id("policy:provider"),
        principal: id("principal:agent"),
        action: id("action:provider.call"),
        scope_digest: Digest32::of_bytes(b"provider-scope"),
        effect: PolicyEffect::Allow,
        not_before_ms: 1_000,
        expires_at_ms: 10_000,
    }
}

fn quota(limit: u64) -> QuotaSpec {
    QuotaSpec {
        quota_key: id("quota:provider"),
        principal: id("principal:agent"),
        scope_digest: Digest32::of_bytes(b"provider-scope"),
        unit: id("unit:request"),
        period_id: id("period:one"),
        limit,
    }
}

async fn configured(
    limit: u64,
) -> (TempDir, AuthBusAuthorityStore, PolicyDecision, QuotaSnapshot) {
    let root = TempDir::new().expect("temp dir");
    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    let created_policy = store
        .create_policy(policy(), sample(1, 1_100))
        .await
        .expect("create policy");
    let decision = store
        .authorize(
            &created_policy.principal,
            &created_policy.action,
            created_policy.scope_digest,
            /*policy_revision*/ 1,
            sample(2, 1_200),
        )
        .await
        .expect("authorize");
    let quota = store
        .create_quota(quota(limit), sample(3, 1_300))
        .await
        .expect("create quota");
    (root, store, decision, quota)
}

#[tokio::test]
async fn simultaneous_last_unit_reservations_cannot_both_succeed() {
    let (_root, store, decision, quota) = configured(1).await;
    let request = |operation: &str| ReservationRequest {
        quota_key: quota.quota_key.clone(),
        operation_id: id(operation),
        amount: 1,
        expected_quota_revision: 1,
        expires_at_ms: 5_000,
    };
    let time = sample(4, 1_400);
    let left_store = store.clone();
    let right_store = store.clone();
    let (left, right) = tokio::join!(
        left_store.reserve(&decision, request("operation:left"), time.clone()),
        right_store.reserve(&decision, request("operation:right"), time),
    );
    assert_eq!(u8::from(left.is_ok()) + u8::from(right.is_ok()), 1);
    assert!(matches!(
        left.err().or_else(|| right.err()),
        Some(AuthBusAuthorityError::RevisionConflict)
    ));
    assert_eq!(
        store
            .quota_snapshot(&quota.quota_key)
            .await
            .expect("quota snapshot"),
        QuotaSnapshot {
            revision: 2,
            available: 0,
            reserved: 1,
            consumed: 0,
            ..quota
        }
    );
}

#[tokio::test]
async fn exact_reservation_retry_is_idempotent_and_changed_amount_conflicts() {
    let (_root, store, decision, quota) = configured(10).await;
    let request = ReservationRequest {
        quota_key: quota.quota_key.clone(),
        operation_id: id("operation:one"),
        amount: 7,
        expected_quota_revision: 1,
        expires_at_ms: 5_000,
    };
    let first = store
        .reserve(&decision, request.clone(), sample(4, 1_400))
        .await
        .expect("reserve quota");
    let retry = store
        .reserve(&decision, request.clone(), sample(5, 1_500))
        .await
        .expect("idempotent retry");
    assert_eq!(retry, first);

    let mut changed = request;
    changed.amount = 6;
    assert!(matches!(
        store.reserve(&decision, changed, sample(6, 1_600)).await,
        Err(AuthBusAuthorityError::IdempotencyConflict)
    ));
    assert_eq!(
        store
            .quota_snapshot(&quota.quota_key)
            .await
            .expect("quota snapshot"),
        QuotaSnapshot {
            revision: 2,
            available: 3,
            reserved: 7,
            consumed: 0,
            ..quota
        }
    );
}

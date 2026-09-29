use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::PolicyEffect;
use crate::PolicySpec;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::TrustedTimeSample;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identifier")
}

fn time(revision: u64, wall_time_ms: u64) -> TrustedTimeSample {
    TrustedTimeSample::new(
        wall_time_ms,
        revision,
        Digest32::of_bytes(format!("operation-lookup:{revision}:{wall_time_ms}").as_bytes()),
    )
    .expect("valid trusted time")
}

#[tokio::test]
async fn operation_lookup_finds_hot_reservation_and_reports_missing() {
    let root = tempfile::tempdir().expect("temporary authority root");
    let store = AuthBusAuthorityStore::open(&root.path().join("authority.sqlite"))
        .await
        .expect("open authority");
    let scope = Digest32::of_bytes(b"operation-lookup-scope");
    let policy = store
        .create_policy(
            PolicySpec {
                policy_id: id("policy:operation-lookup"),
                principal: id("principal:operation-lookup"),
                action: id("action:operation-lookup"),
                scope_digest: scope,
                effect: PolicyEffect::Allow,
                not_before_ms: 1_000,
                expires_at_ms: 20_000,
            },
            time(1, 1_100),
        )
        .await
        .expect("create policy");
    let decision = store
        .authorize(
            &policy.principal,
            &policy.action,
            scope,
            policy.revision,
            time(2, 1_200),
        )
        .await
        .expect("authorize");
    let quota = store
        .create_quota(
            QuotaSpec {
                quota_key: id("quota:operation-lookup"),
                principal: policy.principal,
                scope_digest: scope,
                unit: id("unit:request"),
                period_id: id("period:operation-lookup"),
                limit: 2,
            },
            time(3, 1_300),
        )
        .await
        .expect("create quota");
    let operation_id = id("operation:lookup");
    let reservation = store
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: quota.quota_key,
                operation_id: operation_id.clone(),
                amount: 1,
                effect_digest: Digest32::of_bytes(b"operation-lookup-effect"),
                expected_quota_revision: quota.revision,
                expires_at_ms: 10_000,
            },
            time(4, 1_400),
        )
        .await
        .expect("reserve");
    assert_eq!(
        store
            .reservation_by_operation(&operation_id)
            .await
            .expect("lookup hot reservation"),
        Some(reservation)
    );
    assert_eq!(
        store
            .reservation_by_operation(&id("operation:missing"))
            .await
            .expect("lookup missing reservation"),
        None
    );
}

async fn admission_fixture() -> (
    tempfile::TempDir,
    AuthBusAuthorityStore,
    crate::PolicyDecision,
    ReservationRequest,
) {
    let root = tempfile::tempdir().expect("temporary authority root");
    let store = AuthBusAuthorityStore::open(&root.path().join("authority.sqlite"))
        .await
        .expect("open authority");
    let scope = Digest32::of_bytes(b"operation-lookup-scope");
    let policy = store
        .create_policy(
            PolicySpec {
                policy_id: id("policy:operation-lookup"),
                principal: id("principal:operation-lookup"),
                action: id("action:operation-lookup"),
                scope_digest: scope,
                effect: PolicyEffect::Allow,
                not_before_ms: 1_000,
                expires_at_ms: 20_000,
            },
            time(1, 1_100),
        )
        .await
        .expect("create policy");
    let decision = store
        .authorize(
            &policy.principal,
            &policy.action,
            scope,
            policy.revision,
            time(2, 1_200),
        )
        .await
        .expect("authorize");
    let quota = store
        .create_quota(
            QuotaSpec {
                quota_key: id("quota:operation-lookup"),
                principal: policy.principal,
                scope_digest: scope,
                unit: id("unit:request"),
                period_id: id("period:operation-lookup"),
                limit: 2,
            },
            time(3, 1_300),
        )
        .await
        .expect("create quota");

    let request = ReservationRequest {
        quota_key: quota.quota_key,
        operation_id: id("operation:admission-race"),
        amount: 1,
        effect_digest: Digest32::of_bytes(b"admission-race-effect"),
        expected_quota_revision: quota.revision,
        expires_at_ms: 10_000,
    };
    (root, store, decision, request)
}

#[tokio::test]
async fn sealed_absence_is_idempotent_durable_and_rejects_late_reserve() {
    let (root, store, decision, request) = admission_fixture().await;
    let before = store.authority_frontier_digest().await.unwrap();
    assert_eq!(
        store
            .seal_unreserved_operation(&request.operation_id, request.effect_digest)
            .await
            .unwrap(),
        None
    );
    let sealed = store.authority_frontier_digest().await.unwrap();
    assert_ne!(before, sealed);
    assert_eq!(
        store
            .seal_unreserved_operation(&request.operation_id, request.effect_digest)
            .await
            .unwrap(),
        None
    );
    assert_eq!(store.authority_frontier_digest().await.unwrap(), sealed);
    assert!(matches!(
        store
            .seal_unreserved_operation(&request.operation_id, Digest32::of_bytes(b"changed"))
            .await,
        Err(AuthBusAuthorityError::IdempotencyConflict)
    ));
    drop(store);
    let store = AuthBusAuthorityStore::open(&root.path().join("authority.sqlite"))
        .await
        .unwrap();
    assert!(matches!(
        store.reserve(&decision, request, time(4, 1_400)).await,
        Err(AuthBusAuthorityError::IdempotencyConflict)
    ));
}

#[tokio::test]
async fn admission_seal_returns_original_reservation_without_cancelling_it() {
    let (_root, store, decision, request) = admission_fixture().await;
    let operation = request.operation_id.clone();
    let effect = request.effect_digest;
    let reservation = store
        .reserve(&decision, request, time(4, 1_400))
        .await
        .unwrap();
    assert_eq!(
        store
            .seal_unreserved_operation(&operation, effect)
            .await
            .unwrap(),
        Some(reservation)
    );
}

#[tokio::test]
async fn concurrent_seal_and_reserve_have_one_serializable_outcome() {
    for _ in 0..12 {
        let (_root, store, decision, request) = admission_fixture().await;
        let operation = request.operation_id.clone();
        let effect = request.effect_digest;
        let (reserved, sealed) = tokio::join!(
            store.reserve(&decision, request, time(4, 1_400)),
            store.seal_unreserved_operation(&operation, effect),
        );
        match (reserved, sealed.unwrap()) {
            (Ok(reservation), Some(observed)) => assert_eq!(reservation, observed),
            (Err(AuthBusAuthorityError::IdempotencyConflict), None) => {}
            other => panic!("non-serializable admission outcome: {other:?}"),
        }
    }
}

#[tokio::test]
async fn admission_seal_cannot_be_removed_or_rebound_by_sql() {
    let (_root, store, _decision, request) = admission_fixture().await;
    store
        .seal_unreserved_operation(&request.operation_id, request.effect_digest)
        .await
        .unwrap();
    for sql in [
        "DELETE FROM authbus_operation_admission_fence",
        "UPDATE authbus_operation_admission_fence SET effect_digest = zeroblob(32)",
    ] {
        assert!(sqlx::query(sql).execute(&store.pool).await.is_err());
    }
}

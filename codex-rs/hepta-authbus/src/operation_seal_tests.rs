use super::*;
use crate::PolicyDecision;
use crate::PolicyEffect;
use crate::PolicySpec;
use crate::QuotaSpec;
use crate::ReservationRequest;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn time() -> TrustedTimeSample {
    TrustedTimeSample::new(1_000, 1, Digest32::of_bytes(b"seal-test-time")).unwrap()
}

async fn fixture() -> (
    tempfile::TempDir,
    AuthBusAuthorityStore,
    PolicyDecision,
    ReservationRequest,
) {
    let root = tempfile::tempdir().unwrap();
    let store = AuthBusAuthorityStore::open(&root.path().join("authority.sqlite"))
        .await
        .unwrap();
    let scope = Digest32::of_bytes(b"seal-scope");
    let policy = store
        .create_policy(
            PolicySpec {
                policy_id: id("policy:seal"),
                principal: id("principal:seal"),
                action: id("action:seal"),
                scope_digest: scope,
                effect: PolicyEffect::Allow,
                not_before_ms: 1,
                expires_at_ms: 10_000,
            },
            time(),
        )
        .await
        .unwrap();
    let decision = store
        .authorize(
            &policy.principal,
            &policy.action,
            scope,
            policy.revision,
            time(),
        )
        .await
        .unwrap();
    let quota = store
        .create_quota(
            QuotaSpec {
                quota_key: id("quota:seal"),
                principal: policy.principal,
                scope_digest: scope,
                unit: id("unit:request"),
                period_id: id("period:seal"),
                limit: 1,
            },
            time(),
        )
        .await
        .unwrap();
    let request = ReservationRequest {
        quota_key: quota.quota_key,
        operation_id: id("operation:seal"),
        amount: 1,
        effect_digest: Digest32::of_bytes(b"original-seal-effect"),
        expected_quota_revision: quota.revision,
        expires_at_ms: 9_000,
    };
    (root, store, decision, request)
}

#[tokio::test]
async fn durable_seal_blocks_late_reserve_and_survives_restart() {
    let (root, store, decision, request) = fixture().await;
    let before = store.quota_snapshot(&request.quota_key).await.unwrap();
    let seal = store
        .seal_unreserved_operation(&request.operation_id, request.effect_digest, time())
        .await
        .unwrap();
    assert_eq!(seal, None);
    store.pool.close().await;
    let store = AuthBusAuthorityStore::open(&root.path().join("authority.sqlite"))
        .await
        .unwrap();
    assert!(matches!(
        store.reserve(&decision, request.clone(), time()).await,
        Err(AuthBusAuthorityError::IdempotencyConflict)
    ));
    assert_eq!(store.quota_snapshot(&request.quota_key).await.unwrap(), before);
    assert_eq!(
        store
            .seal_unreserved_operation(&request.operation_id, request.effect_digest, time())
            .await
            .unwrap(),
        None
    );
    assert!(matches!(
        store
            .seal_unreserved_operation(
                &request.operation_id,
                Digest32::of_bytes(b"changed-effect"),
                time(),
            )
            .await,
        Err(AuthBusAuthorityError::IdempotencyConflict)
    ));
}

#[tokio::test]
async fn reservation_winner_is_adopted_not_falsely_closed() {
    let (_root, store, decision, request) = fixture().await;
    let original = store.reserve(&decision, request.clone(), time()).await.unwrap();
    assert_eq!(
        store
            .seal_unreserved_operation(&request.operation_id, request.effect_digest, time())
            .await
            .unwrap(),
        Some(original.clone())
    );
    assert_eq!(store.reserve(&decision, request, time()).await.unwrap(), original);
}

#[tokio::test]
async fn reserve_and_closure_have_one_serialized_winner() {
    for _ in 0..16 {
        let (_root, store, decision, request) = fixture().await;
        let (reserved, sealed) = tokio::join!(
            store.reserve(&decision, request.clone(), time()),
            store.seal_unreserved_operation(&request.operation_id, request.effect_digest, time()),
        );
        match (reserved, sealed.unwrap()) {
            (Ok(reservation), Some(adopted)) => assert_eq!(reservation, adopted),
            (Err(AuthBusAuthorityError::IdempotencyConflict), None) => {
                assert_eq!(
                    store.reservation_by_operation(&request.operation_id).await.unwrap(),
                    None
                );
            }
            other => panic!("invalid reserve/seal race outcome: {other:?}"),
        }
    }
}

#[tokio::test]
async fn seal_is_in_frontier_and_cannot_be_mutated_or_deleted() {
    let (_root, store, _decision, request) = fixture().await;
    let before = store.authority_frontier_digest().await.unwrap();
    store
        .seal_unreserved_operation(&request.operation_id, request.effect_digest, time())
        .await
        .unwrap();
    assert_ne!(store.authority_frontier_digest().await.unwrap(), before);
    assert!(
        sqlx::query("UPDATE authbus_operation_closure SET closed_at_ms = ?")
            .bind(u64_bytes(2_000).as_slice())
            .execute(&store.pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM authbus_operation_closure")
            .execute(&store.pool)
            .await
            .is_err()
    );
}

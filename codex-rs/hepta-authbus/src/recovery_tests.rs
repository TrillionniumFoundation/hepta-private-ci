use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use super::*;
use crate::PolicyEffect;
use crate::PolicySpec;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::TrustedTimeSample;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn sample(revision: u64, wall_time_ms: u64) -> TrustedTimeSample {
    TrustedTimeSample::new(
        wall_time_ms,
        revision,
        Digest32::of_bytes(format!("recovery-time:{revision}:{wall_time_ms}").as_bytes()),
    )
    .expect("valid time")
}

fn policy(scope: Digest32) -> PolicySpec {
    PolicySpec {
        policy_id: id("policy:recovery"),
        principal: id("principal:recovery"),
        action: id("action:recovery"),
        scope_digest: scope,
        effect: PolicyEffect::Allow,
        not_before_ms: 1_000,
        expires_at_ms: 20_000,
    }
}

#[tokio::test]
async fn advanced_external_checkpoint_rejects_real_old_database_restore() {
    let root = TempDir::new().unwrap();
    let path = root.path().join("authbus.sqlite");
    let backup = root.path().join("authbus-old.sqlite");

    let store = AuthBusAuthorityStore::open(&path).await.unwrap();
    let first = AuthorityCheckpoint {
        generation: 1,
        digest: store.authority_frontier_digest().await.unwrap(),
    };
    store.initialize_authority_checkpoint(first).await.unwrap();
    sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
        .execute(&store.pool)
        .await
        .unwrap();
    store.pool.close().await;
    std::fs::copy(&path, &backup).unwrap();

    let store = AuthBusAuthorityStore::open(&path).await.unwrap();
    store
        .create_policy(
            policy(Digest32::of_bytes(b"restore-scope")),
            sample(1, 2_000),
        )
        .await
        .unwrap();
    let next = store
        .reconcile_authority_checkpoint(first)
        .await
        .unwrap()
        .expect("mutation must require successor checkpoint");
    assert_eq!(next.generation, 2);
    store
        .advance_authority_checkpoint(first.generation, next)
        .await
        .unwrap();
    sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
        .execute(&store.pool)
        .await
        .unwrap();
    store.pool.close().await;

    let _ = std::fs::remove_file(root.path().join("authbus.sqlite-wal"));
    let _ = std::fs::remove_file(root.path().join("authbus.sqlite-shm"));
    std::fs::copy(&backup, &path).unwrap();

    let restored = AuthBusAuthorityStore::open(&path).await.unwrap();
    assert!(matches!(
        restored.reconcile_authority_checkpoint(next).await,
        Err(AuthBusAuthorityError::RollbackDetected)
    ));
}

#[tokio::test]
async fn restart_fences_new_reservations_until_dispatch_attempts_become_indeterminate() {
    let root = TempDir::new().unwrap();
    let path = root.path().join("authbus.sqlite");
    let scope = Digest32::of_bytes(b"recovery-scope");

    let store = AuthBusAuthorityStore::open(&path).await.unwrap();
    let created = store
        .create_policy(policy(scope), sample(1, 2_000))
        .await
        .unwrap();
    let decision = store
        .authorize(
            &created.principal,
            &created.action,
            scope,
            created.revision,
            sample(2, 2_100),
        )
        .await
        .unwrap();
    let quota = store
        .create_quota(
            QuotaSpec {
                quota_key: id("quota:recovery"),
                principal: created.principal.clone(),
                scope_digest: scope,
                unit: id("unit:request"),
                period_id: id("period:recovery"),
                limit: 2,
            },
            sample(3, 2_200),
        )
        .await
        .unwrap();
    let first = store
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: quota.quota_key.clone(),
                operation_id: id("operation:first"),
                amount: 1,
                effect_digest: Digest32::of_bytes(b"effect:first"),
                expected_quota_revision: quota.revision,
                expires_at_ms: 10_000,
            },
            sample(4, 2_300),
        )
        .await
        .unwrap();
    let dispatched = store
        .mark_dispatch_attempted(
            &first.reservation_id,
            first.revision,
            first.effect_digest,
            sample(5, 2_400),
        )
        .await
        .unwrap();
    drop(store);

    let reopened = AuthBusAuthorityStore::open(&path).await.unwrap();
    assert!(reopened.recovery_required().await.unwrap());
    assert!(matches!(
        reopened
            .reserve(
                &decision,
                ReservationRequest {
                    quota_key: quota.quota_key.clone(),
                    operation_id: id("operation:blocked"),
                    amount: 1,
                    effect_digest: Digest32::of_bytes(b"effect:blocked"),
                    expected_quota_revision: 2,
                    expires_at_ms: 10_000,
                },
                sample(6, 2_500),
            )
            .await,
        Err(AuthBusAuthorityError::RecoveryRequired)
    ));
    assert!(reopened.reconcile_after_restart(256).await.unwrap());
    assert!(!reopened.recovery_required().await.unwrap());
    let recovered = reopened
        .reservation(&dispatched.reservation_id)
        .await
        .unwrap();
    assert_eq!(recovered.state, ReservationState::Indeterminate);
    let held = reopened.quota_snapshot(&quota.quota_key).await.unwrap();
    assert_eq!((held.available, held.reserved, held.consumed), (1, 1, 0));
}

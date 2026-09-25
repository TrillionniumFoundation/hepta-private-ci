use super::*;
use pretty_assertions::assert_eq;
use std::time::Duration;

#[tokio::test]
async fn late_success_and_no_effect_survive_indeterminate_and_restart() {
    for (status, cost) in [
        (SettlementStatus::Completed, 5),
        (SettlementStatus::Rejected, 0),
    ] {
        let (root, store, _, reservation) = configured().await;
        let dispatched = store
            .mark_dispatch_attempted(
                &reservation.reservation_id,
                reservation.revision,
                reservation.effect_digest,
                sample(5, 1_500),
            )
            .await
            .expect("dispatch");
        let key = SigningKey::from_bytes(&[25; 32]);
        enroll_settlement_issuer(&store, &key).await;
        let signed = evidence(&key, &dispatched, status, cost, 1_600);
        store
            .mark_indeterminate(
                &reservation.reservation_id,
                dispatched.revision,
                sample(6, 1_800),
            )
            .await
            .expect("record uncertainty after the observation");
        store.pool.close().await;
        let reopened = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
            .await
            .expect("reopen durable owner");
        let recovered = reopened
            .reservation(&reservation.reservation_id)
            .await
            .expect("reservation");
        assert_eq!(recovered.dispatched_at_ms, Some(1_500));
        assert_eq!(recovered.updated_at_ms, 1_800);
        let settled = reopened
            .settle(&signed, sample(7, 1_900))
            .await
            .expect("late settlement");
        assert_eq!(settled.observed_cost, cost);
        let quota = reopened
            .quota_snapshot(&reservation.quota_key)
            .await
            .expect("quota");
        assert_eq!(
            (quota.available, quota.reserved, quota.consumed),
            (10 - cost, 0, cost)
        );
        assert_eq!(
            reopened
                .settle(&signed, sample(8, 2_000))
                .await
                .expect("exact retry"),
            settled
        );
    }
}

#[tokio::test]
async fn issuer_revocation_committed_while_settlement_waits_is_observed() {
    let (_root, store, _, reservation) = configured().await;
    let dispatched = store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            reservation.effect_digest,
            sample(5, 1_500),
        )
        .await
        .expect("dispatch");
    let key = SigningKey::from_bytes(&[26; 32]);
    let cached = enroll_settlement_issuer(&store, &key).await;
    let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 1_600);
    let mut revocation = begin(&store.pool).await.expect("hold writer transaction");
    sqlx::query("UPDATE authbus_issuer_registry SET state = 'revoked', revision = ? WHERE issuer_id = ? AND purpose = 'settlement'")
        .bind(u64_bytes(2).as_slice()).bind(cached.issuer_id.as_str())
        .execute(&mut *revocation).await.expect("stage revocation");
    let mut pending = Box::pin(store.settle(&signed, sample(6, 1_700)));
    assert!(
        tokio::time::timeout(Duration::from_millis(50), pending.as_mut())
            .await
            .is_err()
    );
    revocation
        .commit()
        .await
        .expect("commit revocation before settlement admission");
    assert_eq!(cached.state, IssuerLifecycleState::Active);
    assert!(matches!(
        pending.await,
        Err(AuthBusAuthorityError::SettlementIssuerRevoked)
    ));
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota");
    assert_eq!((quota.available, quota.reserved, quota.consumed), (3, 7, 0));
}

#[tokio::test]
async fn an_unregistered_key_cannot_reuse_a_registered_issuer_identity() {
    let (_root, store, _, reservation) = configured().await;
    let dispatched = store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            reservation.effect_digest,
            sample(5, 1_500),
        )
        .await
        .expect("dispatch");
    enroll_settlement_issuer(&store, &SigningKey::from_bytes(&[27; 32])).await;
    let signed = evidence(
        &SigningKey::from_bytes(&[28; 32]),
        &dispatched,
        SettlementStatus::Completed,
        5,
        1_600,
    );
    assert!(matches!(
        store.settle(&signed, sample(6, 1_700)).await,
        Err(AuthBusAuthorityError::InvalidSettlementSignature)
    ));
}

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

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

async fn fixture() -> (tempfile::TempDir, AuthBusAuthorityStore, QuotaReservation) {
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
    let reservation = store
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: quota.quota_key,
                operation_id: id("operation:lookup"),
                amount: 1,
                effect_digest: Digest32::of_bytes(b"operation-lookup-effect"),
                expected_quota_revision: quota.revision,
                expires_at_ms: 10_000,
            },
            time(4, 1_400),
        )
        .await
        .expect("reserve");
    (root, store, reservation)
}

#[tokio::test]
async fn operation_lookup_finds_hot_reservation_and_reports_missing() {
    let (_root, store, reservation) = fixture().await;
    assert_eq!(
        store
            .reservation_by_operation(&reservation.operation_id)
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

#[tokio::test]
async fn operation_lookup_retains_original_terminal_row_after_archival_and_reopen() {
    let (root, store, reservation) = fixture().await;
    let terminal = store
        .cancel_reservation(&reservation.reservation_id, reservation.revision, time(5, 1_500))
        .await
        .expect("cancel before dispatch");
    assert_eq!(
        store.compact_terminal_reservations(1_600, 10).await.expect("archive terminal"),
        1
    );
    assert_eq!(
        store.reservation_by_operation(&terminal.operation_id).await.expect("archive lookup"),
        Some(terminal.clone())
    );
    drop(store);
    let reopened = AuthBusAuthorityStore::open(&root.path().join("authority.sqlite"))
        .await
        .expect("reopen authority");
    assert_eq!(
        reopened.reservation_by_operation(&terminal.operation_id).await.expect("restart lookup"),
        Some(terminal)
    );
}

#[tokio::test]
async fn operation_lookup_does_not_lose_identity_during_concurrent_compaction() {
    let (_root, store, reservation) = fixture().await;
    let terminal = store
        .cancel_reservation(&reservation.reservation_id, reservation.revision, time(5, 1_500))
        .await
        .expect("cancel before dispatch");
    let (archived, observed) = tokio::join!(
        store.compact_terminal_reservations(1_600, 10),
        store.reservation_by_operation(&terminal.operation_id),
    );
    assert_eq!(archived.expect("archive"), 1);
    assert_eq!(observed.expect("single-snapshot lookup"), Some(terminal));
}

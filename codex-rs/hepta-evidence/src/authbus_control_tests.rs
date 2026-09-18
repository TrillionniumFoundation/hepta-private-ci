use codex_hepta_authbus::PolicyRevision;
use codex_hepta_authbus::PolicyRule;
use codex_hepta_authbus::QuotaConfig;
use codex_hepta_authbus::ReservationState;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::*;

fn id(v: &str) -> StableId {
    StableId::new(v).unwrap()
}

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

async fn seed(store: &HeptaEvidenceStore, endowment: u64) {
    let scope = Digest32::of_bytes(b"scope");
    store
        .install_authbus_policy(
            &PolicyRevision {
                policy_id: id("policy:one"),
                revision: 1,
                rules: vec![PolicyRule {
                    principal_id: id("principal:one"),
                    action_id: id("action:effect"),
                    scope_digest: scope,
                    allow: true,
                }],
            },
            false,
        )
        .await
        .unwrap();
    store
        .configure_authbus_quota(&QuotaConfig {
            quota_key: id("quota:one"),
            revision: 1,
            endowment,
        })
        .await
        .unwrap();
}

async fn reserve(
    store: &HeptaEvidenceStore,
    suffix: &str,
    amount: u64,
) -> Result<
    (
        codex_hepta_authbus::PolicyDecision,
        codex_hepta_authbus::Reservation,
    ),
    AuthBusControlError,
> {
    store
        .authorize_and_reserve_authbus(
            &id("policy:one"),
            1,
            &id("principal:one"),
            &id("action:effect"),
            Digest32::of_bytes(b"scope"),
            &id("quota:one"),
            1,
            &id(&format!("reservation:{suffix}")),
            &id(&format!("operation:{suffix}")),
            amount,
            u64::MAX,
        )
        .await
}

#[tokio::test]
async fn bus_01_simultaneous_last_unit_reservations_cannot_both_succeed() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    seed(&first, 1).await;
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let (left, right) = tokio::join!(reserve(&first, "left", 1), reserve(&second, "right", 1));
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let rejected = left.err().or_else(|| right.err()).unwrap();
    assert!(matches!(rejected, AuthBusControlError::QuotaExceeded));
}

#[tokio::test]
async fn bus_02_duplicate_settlement_is_idempotent_and_altered_cost_conflicts() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 10).await;
    let reservation = reserve(&store, "settle", 7).await.unwrap().1;
    let evidence = Digest32::of_bytes(b"terminal");
    let first = store
        .settle_authbus_reservation(&reservation.reservation_id, 5, evidence)
        .await
        .unwrap();
    let duplicate = store
        .settle_authbus_reservation(&reservation.reservation_id, 5, evidence)
        .await
        .unwrap();
    assert_eq!(first, duplicate);
    assert!(matches!(
        store
            .settle_authbus_reservation(
                &reservation.reservation_id,
                4,
                Digest32::of_bytes(b"other")
            )
            .await,
        Err(AuthBusControlError::IdempotencyConflict)
    ));
    store
        .reconcile_authbus_quota(&id("quota:one"))
        .await
        .unwrap();
}

#[tokio::test]
async fn bus_03_expiry_racing_terminal_result_preserves_conservation() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 10).await;
    let reservation = store
        .authorize_and_reserve_authbus(
            &id("policy:one"),
            1,
            &id("principal:one"),
            &id("action:effect"),
            Digest32::of_bytes(b"scope"),
            &id("quota:one"),
            1,
            &id("reservation:race"),
            &id("operation:race"),
            6,
            10,
        )
        .await
        .unwrap()
        .1;
    let settle = store.settle_authbus_reservation(
        &reservation.reservation_id,
        4,
        Digest32::of_bytes(b"terminal"),
    );
    let expire = store.expire_authbus_reservation(&reservation.reservation_id, 10);
    let (settled, expired) = tokio::join!(settle, expire);
    assert_eq!(
        usize::from(settled.is_ok()) + usize::from(expired.is_ok()),
        1
    );
    store
        .reconcile_authbus_quota(&id("quota:one"))
        .await
        .unwrap();
}

#[tokio::test]
async fn bus_04_revocation_blocks_final_use_and_new_reservations() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 10).await;
    let reservation = reserve(&store, "revoked", 3).await.unwrap().1;
    store
        .set_authbus_policy_revoked(&id("policy:one"), 1, true)
        .await
        .unwrap();
    assert!(matches!(
        store
            .validate_authbus_reservation_for_effect(&reservation.reservation_id, 1)
            .await,
        Err(AuthBusControlError::Denied)
    ));
    assert!(matches!(
        reserve(&store, "after-revoke", 1).await,
        Err(AuthBusControlError::Denied)
    ));
    store
        .quarantine_authbus_reservation(&reservation.reservation_id)
        .await
        .unwrap();
    store
        .reconcile_authbus_quota(&id("quota:one"))
        .await
        .unwrap();
    let state: String =
        sqlx::query_scalar("SELECT state FROM authbus_quota_reservations WHERE reservation_id=?")
            .bind(reservation.reservation_id.as_str())
            .fetch_one(&store.pool)
            .await
            .unwrap();
    assert_eq!(state, ReservationState::Quarantined.as_str());
}

#[tokio::test]
async fn control_state_survives_reopen_and_reconcile_repairs_derived_counters() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    seed(&store, 20).await;
    let reservation = reserve(&store, "reopen", 8).await.unwrap().1;
    store.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    reopened
        .reconcile_authbus_quota(&id("quota:one"))
        .await
        .unwrap();
    let active = reopened
        .validate_authbus_reservation_for_effect(&reservation.reservation_id, 1)
        .await
        .unwrap();
    assert_eq!(active.state, ReservationState::Active);
}

use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::PolicyRevision;
use codex_hepta_authbus::PolicyRule;
use codex_hepta_authbus::QuotaConfig;
use codex_hepta_authbus::ReservationState;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::Row;
use tempfile::TempDir;

use super::*;

fn id(v: &str) -> StableId {
    StableId::new(v).unwrap()
}

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap()
}

fn effect(suffix: &str) -> Digest32 {
    Digest32::of_bytes(format!("effect:{suffix}").as_bytes())
}

fn decode_counter(bytes: Vec<u8>) -> u64 {
    u64::from_be_bytes(bytes.try_into().unwrap())
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
            unit_id: id("unit:effect"),
            window_start_ms: 1,
            window_end_ms: u64::MAX,
            endowment,
        })
        .await
        .unwrap();
}

async fn reserve_with(
    store: &HeptaEvidenceStore,
    suffix: &str,
    amount: u64,
    expires_at_ms: u64,
    effect_digest: Digest32,
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
            expires_at_ms,
            effect_digest,
        )
        .await
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
    reserve_with(store, suffix, amount, u64::MAX - 1, effect(suffix)).await
}

async fn begin_effect(
    store: &HeptaEvidenceStore,
    reservation: &codex_hepta_authbus::Reservation,
    effect_digest: Digest32,
) -> Result<codex_hepta_authbus::Reservation, AuthBusControlError> {
    store
        .begin_authbus_effect(
            &reservation.reservation_id,
            &id("principal:one"),
            &id("action:effect"),
            Digest32::of_bytes(b"scope"),
            effect_digest,
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
    store
        .begin_authbus_effect(
            &reservation.reservation_id,
            &id("principal:one"),
            &id("action:effect"),
            Digest32::of_bytes(b"scope"),
            effect("settle"),
        )
        .await
        .unwrap();
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
async fn bus_03_expiry_after_effect_start_cannot_refund_observed_effect() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 10).await;
    let expires = now_ms().checked_add(500).unwrap();
    let reservation = reserve_with(&store, "race", 6, expires, effect("race"))
        .await
        .unwrap()
        .1;
    store
        .begin_authbus_effect(
            &reservation.reservation_id,
            &id("principal:one"),
            &id("action:effect"),
            Digest32::of_bytes(b"scope"),
            effect("race"),
        )
        .await
        .unwrap();

    let delay = expires.saturating_sub(now_ms()).saturating_add(30);
    tokio::time::sleep(Duration::from_millis(delay)).await;

    let settle = store.settle_authbus_reservation(
        &reservation.reservation_id,
        4,
        Digest32::of_bytes(b"terminal"),
    );
    let expire = store.expire_authbus_reservation(&reservation.reservation_id);
    let (settled, expired) = tokio::join!(settle, expire);
    assert!(settled.is_ok());
    assert!(matches!(
        expired,
        Err(AuthBusControlError::InvalidTransition)
    ));

    store
        .reconcile_authbus_quota(&id("quota:one"))
        .await
        .unwrap();
    let row = sqlx::query("SELECT reserved, consumed FROM authbus_quota_registry WHERE quota_key=?")
        .bind("quota:one")
        .fetch_one(&store.pool)
        .await
        .unwrap();
    let reserved: Vec<u8> = row.try_get("reserved").unwrap();
    let consumed: Vec<u8> = row.try_get("consumed").unwrap();
    assert_eq!(decode_counter(reserved), 0);
    assert_eq!(decode_counter(consumed), 4);
}

#[tokio::test]
async fn bus_04_revocation_blocks_effect_start_and_new_reservations() {
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
            .begin_authbus_effect(
                &reservation.reservation_id,
                &id("principal:one"),
                &id("action:effect"),
                Digest32::of_bytes(b"scope"),
                effect("revoked"),
            )
            .await,
        Err(AuthBusControlError::Denied)
    ));
    assert!(matches!(
        reserve(&store, "after-revoke", 1).await,
        Err(AuthBusControlError::Denied)
    ));
    store
        .cancel_authbus_reservation(&reservation.reservation_id)
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
    assert_eq!(state, ReservationState::Cancelled.as_str());
}

#[tokio::test]
async fn operation_retry_binds_full_authorization_and_effect_semantics() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 10).await;
    let first = reserve(&store, "binding", 2).await.unwrap().1;
    let duplicate = reserve(&store, "binding", 2).await.unwrap().1;
    assert_eq!(first, duplicate);

    assert!(matches!(
        reserve_with(
            &store,
            "binding",
            2,
            u64::MAX - 1,
            Digest32::of_bytes(b"different-effect")
        )
        .await,
        Err(AuthBusControlError::IdempotencyConflict)
    ));

    assert!(matches!(
        store
            .begin_authbus_effect(
                &first.reservation_id,
                &id("principal:one"),
                &id("action:effect"),
                Digest32::of_bytes(b"scope"),
                Digest32::of_bytes(b"different-effect"),
            )
            .await,
        Err(AuthBusControlError::InvalidTransition)
    ));
    assert!(matches!(
        store
            .begin_authbus_effect(
                &first.reservation_id,
                &id("principal:other"),
                &id("action:effect"),
                Digest32::of_bytes(b"scope"),
                effect("binding"),
            )
            .await,
        Err(AuthBusControlError::InvalidTransition)
    ));
    assert!(matches!(
        store
            .begin_authbus_effect(
                &first.reservation_id,
                &id("principal:one"),
                &id("action:other"),
                Digest32::of_bytes(b"scope"),
                effect("binding"),
            )
            .await,
        Err(AuthBusControlError::InvalidTransition)
    ));
    assert!(matches!(
        store
            .begin_authbus_effect(
                &first.reservation_id,
                &id("principal:one"),
                &id("action:effect"),
                Digest32::of_bytes(b"other-scope"),
                effect("binding"),
            )
            .await,
        Err(AuthBusControlError::InvalidTransition)
    ));
    let started = begin_effect(&store, &first, effect("binding"))
        .await
        .unwrap();
    assert_eq!(started.state, ReservationState::EffectStarted);
    assert!(started.effect_started_at_ms.is_some());
}

#[tokio::test]
async fn begin_effect_racing_cancel_has_one_linearization_and_never_double_refunds() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    seed(&first, 5).await;
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let reservation = reserve(&first, "begin-cancel-race", 4).await.unwrap().1;

    let begin = first.begin_authbus_effect(
        &reservation.reservation_id,
        &id("principal:one"),
        &id("action:effect"),
        Digest32::of_bytes(b"scope"),
        effect("begin-cancel-race"),
    );
    let cancel = second.cancel_authbus_reservation(&reservation.reservation_id);
    let (begun, cancelled) = tokio::join!(begin, cancel);
    assert_eq!(
        usize::from(begun.is_ok()) + usize::from(cancelled.is_ok()),
        1
    );

    first
        .reconcile_authbus_quota(&id("quota:one"))
        .await
        .unwrap();
    let row = sqlx::query(
        "SELECT state FROM authbus_quota_reservations WHERE reservation_id=?",
    )
    .bind(reservation.reservation_id.as_str())
    .fetch_one(&first.pool)
    .await
    .unwrap();
    let state: String = row.try_get("state").unwrap();
    let reserved: Vec<u8> =
        sqlx::query_scalar("SELECT reserved FROM authbus_quota_registry WHERE quota_key=?")
            .bind("quota:one")
            .fetch_one(&first.pool)
            .await
            .unwrap();
    match state.as_str() {
        "effect_started" => assert_eq!(decode_counter(reserved), 4),
        "cancelled" => assert_eq!(decode_counter(reserved), 0),
        other => panic!("unexpected race terminal state: {other}"),
    }
}

#[tokio::test]
async fn exact_reservation_retry_after_revocation_is_observation_not_new_authority() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 5).await;
    let original = reserve(&store, "lost-response", 2).await.unwrap();
    store
        .set_authbus_policy_revoked(&id("policy:one"), 1, true)
        .await
        .unwrap();

    let duplicate = reserve(&store, "lost-response", 2).await.unwrap();
    assert_eq!(duplicate, original);
    assert!(matches!(
        begin_effect(&store, &duplicate.1, effect("lost-response")).await,
        Err(AuthBusControlError::Denied)
    ));
}

#[tokio::test]
async fn owner_clock_rejects_already_expired_reservation() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 10).await;
    assert!(matches!(
        reserve_with(&store, "expired", 1, 1, effect("expired")).await,
        Err(AuthBusControlError::InvalidTransition)
    ));
    let reserved: Vec<u8> =
        sqlx::query_scalar("SELECT reserved FROM authbus_quota_registry WHERE quota_key=?")
            .bind("quota:one")
            .fetch_one(&store.pool)
            .await
            .unwrap();
    assert_eq!(decode_counter(reserved), 0);
}

#[tokio::test]
async fn quota_window_and_revision_are_enforced_and_rollover_is_bounded() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let now = now_ms();
    let window_end = now.checked_add(20_000).unwrap();
    store
        .install_authbus_policy(
            &PolicyRevision {
                policy_id: id("policy:one"),
                revision: 1,
                rules: vec![PolicyRule {
                    principal_id: id("principal:one"),
                    action_id: id("action:effect"),
                    scope_digest: Digest32::of_bytes(b"scope"),
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
            unit_id: id("unit:effect"),
            window_start_ms: now.saturating_sub(1_000),
            window_end_ms: window_end,
            endowment: 5,
        })
        .await
        .unwrap();
    let reservation = reserve_with(
        &store,
        "window",
        1,
        now.checked_add(5_000).unwrap(),
        effect("window"),
    )
    .await
    .unwrap()
    .1;

    assert!(matches!(
        store
            .configure_authbus_quota(&QuotaConfig {
                quota_key: id("quota:one"),
                revision: 2,
                unit_id: id("unit:effect"),
                window_start_ms: now.saturating_sub(1_000),
                window_end_ms: window_end,
                endowment: 6,
            })
            .await,
        Err(AuthBusControlError::Invalid(_))
    ));
    store
        .cancel_authbus_reservation(&reservation.reservation_id)
        .await
        .unwrap();
    store
        .configure_authbus_quota(&QuotaConfig {
            quota_key: id("quota:one"),
            revision: 2,
            unit_id: id("unit:effect"),
            window_start_ms: now.saturating_sub(1_000),
            window_end_ms: window_end,
            endowment: 6,
        })
        .await
        .unwrap();
    store
        .configure_authbus_quota(&QuotaConfig {
            quota_key: id("quota:one"),
            revision: 3,
            unit_id: id("unit:effect"),
            window_start_ms: window_end,
            window_end_ms: window_end.checked_add(20_000).unwrap(),
            endowment: 7,
        })
        .await
        .unwrap();

    assert!(matches!(
        store
            .authorize_and_reserve_authbus(
                &id("policy:one"),
                1,
                &id("principal:one"),
                &id("action:effect"),
                Digest32::of_bytes(b"scope"),
                &id("quota:one"),
                3,
                &id("reservation:not-yet"),
                &id("operation:not-yet"),
                1,
                window_end.checked_add(1_000).unwrap(),
                effect("not-yet"),
            )
            .await,
        Err(AuthBusControlError::Invalid(_))
    ));
}

#[tokio::test]
async fn sqlite_triggers_fail_closed_on_binding_transition_and_delete() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    seed(&store, 10).await;
    let reservation = reserve(&store, "sql", 2).await.unwrap().1;

    assert!(
        sqlx::query(
            "UPDATE authbus_quota_reservations SET operation_id='operation:tampered'
             WHERE reservation_id=?"
        )
        .bind(reservation.reservation_id.as_str())
        .execute(&store.pool)
        .await
        .is_err()
    );
    assert!(
        sqlx::query(
            "UPDATE authbus_quota_reservations SET state='settled', updated_at_ms=updated_at_ms+1
             WHERE reservation_id=?"
        )
        .bind(reservation.reservation_id.as_str())
        .execute(&store.pool)
        .await
        .is_err()
    );

    store
        .begin_authbus_effect(
            &reservation.reservation_id,
            &id("principal:one"),
            &id("action:effect"),
            Digest32::of_bytes(b"scope"),
            effect("sql"),
        )
        .await
        .unwrap();
    assert!(
        sqlx::query("DELETE FROM authbus_quota_reservations WHERE reservation_id=?")
            .bind(reservation.reservation_id.as_str())
            .execute(&store.pool)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn effect_start_survives_reopen_and_failed_settlement_without_refund() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    seed(&store, 20).await;
    let reservation = reserve(&store, "reopen", 8).await.unwrap().1;
    store
        .begin_authbus_effect(
            &reservation.reservation_id,
            &id("principal:one"),
            &id("action:effect"),
            Digest32::of_bytes(b"scope"),
            effect("reopen"),
        )
        .await
        .unwrap();

    store.pool.close().await;
    assert!(matches!(
        store
            .settle_authbus_reservation(
                &reservation.reservation_id,
                3,
                Digest32::of_bytes(b"terminal")
            )
            .await,
        Err(AuthBusControlError::Storage(_))
    ));

    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let pending = reopened
        .pending_authbus_effect_reservations(&id("quota:one"), 16)
        .await
        .unwrap();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].state, ReservationState::EffectStarted);
    assert!(matches!(
        reopened
            .cancel_authbus_reservation(&reservation.reservation_id)
            .await,
        Err(AuthBusControlError::InvalidTransition)
    ));
    assert!(matches!(
        reopened
            .expire_authbus_reservation(&reservation.reservation_id)
            .await,
        Err(AuthBusControlError::InvalidTransition)
    ));
    reopened
        .reconcile_authbus_quota(&id("quota:one"))
        .await
        .unwrap();
    let reserved: Vec<u8> =
        sqlx::query_scalar("SELECT reserved FROM authbus_quota_registry WHERE quota_key=?")
            .bind("quota:one")
            .fetch_one(&reopened.pool)
            .await
            .unwrap();
    assert_eq!(decode_counter(reserved), 8);

    reopened
        .quarantine_authbus_reservation(&reservation.reservation_id)
        .await
        .unwrap();
    reopened
        .settle_authbus_reservation(
            &reservation.reservation_id,
            3,
            Digest32::of_bytes(b"reconciled-terminal"),
        )
        .await
        .unwrap();
}

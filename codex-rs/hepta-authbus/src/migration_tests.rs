use codex_hepta_types::StableId;
use sqlx::migrate::Migrator;

use crate::AuthBusAuthorityStore;
use crate::ReservationState;

static TEST_MIGRATOR: Migrator = sqlx::migrate!("./migrations");

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identifier")
}

fn u64_blob(value: u64) -> Vec<u8> {
    value.to_be_bytes().to_vec()
}

#[tokio::test]
async fn dispatch_boundary_migration_preserves_legacy_terminal_rows() {
    let root = tempfile::tempdir().expect("temporary root");
    let path = root.path().join("authbus.sqlite");
    let pool = codex_state::open_durable_sqlite_pool(&path, 1)
        .await
        .unwrap();
    TEST_MIGRATOR
        .run_to(4, &pool)
        .await
        .expect("apply migrations through v4");

    sqlx::query(
        "INSERT INTO authbus_quota_registry
         (quota_key, principal, scope_digest, unit, period_id, limit_amount,
          available, reserved, consumed, revision)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind("quota:legacy")
    .bind("principal:legacy")
    .bind([1_u8; 32].as_slice())
    .bind("unit:request")
    .bind("period:legacy")
    .bind(u64_blob(2))
    .bind(u64_blob(0))
    .bind(u64_blob(0))
    .bind(u64_blob(2))
    .bind(u64_blob(1))
    .execute(&pool)
    .await
    .expect("insert legacy quota");

    sqlx::query(
        "INSERT INTO authbus_quota_reservation
         (reservation_id, operation_id, quota_key, period_id, principal, amount,
          effect_digest, policy_id, policy_revision, policy_decision_digest, state,
          revision, expires_at_ms, created_at_ms, updated_at_ms, dispatch_digest,
          terminal_evidence, observed_cost, settlement_digest)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'settled', ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind("reservation:legacy-live")
    .bind("operation:legacy-live")
    .bind("quota:legacy")
    .bind("period:legacy")
    .bind("principal:legacy")
    .bind(u64_blob(1))
    .bind([2_u8; 32].as_slice())
    .bind("policy:legacy")
    .bind(u64_blob(1))
    .bind([3_u8; 32].as_slice())
    .bind(u64_blob(3))
    .bind(u64_blob(10_000))
    .bind(u64_blob(1_000))
    .bind(u64_blob(2_000))
    .bind([4_u8; 32].as_slice())
    .bind([5_u8; 32].as_slice())
    .bind(u64_blob(1))
    .bind([6_u8; 32].as_slice())
    .execute(&pool)
    .await
    .expect("insert legacy live terminal row");

    sqlx::query(
        "INSERT INTO authbus_quota_reservation_archive
         (reservation_id, operation_id, quota_key, period_id, principal, amount,
          effect_digest, policy_id, policy_revision, policy_decision_digest, state,
          revision, expires_at_ms, created_at_ms, updated_at_ms, dispatch_digest,
          terminal_evidence, observed_cost, settlement_digest, archived_at_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'released', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind("reservation:legacy-archive")
    .bind("operation:legacy-archive")
    .bind("quota:legacy")
    .bind("period:legacy")
    .bind("principal:legacy")
    .bind(u64_blob(1))
    .bind([7_u8; 32].as_slice())
    .bind("policy:legacy")
    .bind(u64_blob(1))
    .bind([8_u8; 32].as_slice())
    .bind(u64_blob(3))
    .bind(u64_blob(10_000))
    .bind(u64_blob(1_000))
    .bind(u64_blob(2_100))
    .bind([9_u8; 32].as_slice())
    .bind([10_u8; 32].as_slice())
    .bind(u64_blob(0))
    .bind([11_u8; 32].as_slice())
    .bind(u64_blob(2_200))
    .execute(&pool)
    .await
    .expect("insert legacy archived terminal row");
    pool.close().await;

    let store = AuthBusAuthorityStore::open(&path)
        .await
        .expect("migrate legacy database through v5");
    let live = store
        .reservation(&id("reservation:legacy-live"))
        .await
        .expect("read migrated live terminal row");
    assert_eq!(live.state, ReservationState::Settled);
    assert_eq!(live.dispatched_at_ms, None);
    let archived = store
        .reservation(&id("reservation:legacy-archive"))
        .await
        .expect("read migrated archived terminal row");
    assert_eq!(archived.state, ReservationState::Released);
    assert_eq!(archived.dispatched_at_ms, None);

    assert_eq!(
        store
            .compact_terminal_reservations(2_500, 16)
            .await
            .expect("compact migrated live terminal row"),
        1
    );
    let compacted = store
        .reservation(&id("reservation:legacy-live"))
        .await
        .expect("read compacted legacy terminal row");
    assert_eq!(compacted.state, ReservationState::Settled);
    assert_eq!(compacted.dispatched_at_ms, None);
}

#[cfg(unix)]
#[path = "migration_checkpoint_tests.rs"]
mod checkpoint_tests;

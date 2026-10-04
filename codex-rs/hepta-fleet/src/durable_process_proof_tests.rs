//! The observer reads the original SQL clock; it never advances that owner.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use pretty_assertions::assert_eq;
use std::sync::Arc;

struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(100)
    }
}

#[tokio::test]
async fn observer_clock_floor_rejects_rollback_without_publishing_time()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let store = crate::DurableFleetStore::open_with_clock(
        &temp.path().join("fleet.sqlite3"),
        Arc::new(Clock),
    )
    .await?;
    // Only this fixture constructs the pool directly. The public verifier's
    // open path continues to require the real root-protected owner database.
    let verifier = FleetExecutionVerifier {
        pool: store.pool.clone(),
    };
    assert!(matches!(
        verifier.verify_owner_clock_floor(99).await,
        Err(DurableFleetError::Stale)
    ));
    verifier.verify_owner_clock_floor(100).await?;
    verifier.verify_owner_clock_floor(500).await?;
    verifier.verify_owner_clock_floor(200).await?;
    let floor: i64 = sqlx::query_scalar("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1")
        .fetch_one(&store.pool)
        .await?;
    assert_eq!(floor, 100);
    Ok(())
}

#[tokio::test]
async fn durable_owner_shim_preserves_pool_budget_and_rejects_reopen_clock_rollback()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("fleet.sqlite3");
    let store = crate::DurableFleetStore::open_with_clock(&path, Arc::new(Clock)).await?;
    assert_eq!(store.pool.options().get_max_connections(), 4);
    let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
        .fetch_one(&store.pool)
        .await?;
    let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
        .fetch_one(&store.pool)
        .await?;
    let busy: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
        .fetch_one(&store.pool)
        .await?;
    assert_eq!((synchronous, foreign_keys, busy), (2, 1, 5000));
    sqlx::query("UPDATE fleet_clock SET last_now_ms = 500 WHERE singleton = 1")
        .execute(&store.pool)
        .await?;
    store.close().await;
    assert!(matches!(
        crate::DurableFleetStore::open_with_clock(&path, Arc::new(Clock)).await,
        Err(DurableFleetError::ClockRollback)
    ));
    let reader = SqliteConfig::open_owner_read_only_pool(
        &path,
        /*max_connections*/ 2,
        Duration::from_secs(1),
    )
    .await?;
    let floor: i64 = sqlx::query_scalar("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1")
        .fetch_one(&reader)
        .await?;
    assert_eq!(floor, 500);
    reader.close().await;
    Ok(())
}

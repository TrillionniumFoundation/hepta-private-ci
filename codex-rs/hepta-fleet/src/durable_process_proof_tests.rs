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

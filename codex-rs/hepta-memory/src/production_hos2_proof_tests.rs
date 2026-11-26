//! Verify an original owner witness survives the migration to the proof guard.

use super::*;
use pretty_assertions::assert_eq;

type ProofRow = (
    i64,
    String,
    String,
    String,
    String,
    String,
    String,
    String,
    i64,
);
const PROOF_ROWS: &str = "SELECT rowid, operation_id, entered_claim_sha256,
    settled_claim_sha256, dispatch_event_id, lease_id, proof_json, proof_sha256,
    recorded_at_unix_ms FROM cognitive_operation_pre_boundary_rejections
    ORDER BY operation_id, entered_claim_sha256";

#[tokio::test]
async fn pre_boundary_proof_upgrade_preserves_the_existing_owner_witness() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let claim = fixture.reject_claim(&queued).await?;
    let before: Vec<ProofRow> = sqlx::query_as(PROOF_ROWS)
        .fetch_all(&fixture.writer.store.pool)
        .await?;
    assert_eq!(before.len(), 1);
    // Isolate the exact v19 schema/ledger after producing a real owner witness.
    // Migration 20 adds only this trigger; no proof or older migration bytes
    // are changed. This fixture is not a production recovery fallback.
    sqlx::raw_sql(
        "BEGIN IMMEDIATE;
         DROP TRIGGER cognitive_operation_pre_boundary_rejections_no_replace;
         DELETE FROM _sqlx_migrations WHERE version = 20;
         COMMIT;",
    )
    .execute(&fixture.writer.store.pool)
    .await?;
    let legacy: Vec<(i64, String, bool, Vec<u8>)> = sqlx::query_as(
        "SELECT version, description, success, checksum FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&fixture.writer.store.pool)
    .await?;
    assert_eq!(
        legacy.iter().map(|row| row.0).collect::<Vec<_>>(),
        (1..=19).collect::<Vec<_>>()
    );
    fixture.writer.store.pool.close().await;
    drop(fixture);

    let reopened = Fixture::open(directory.path()).await?;
    let after: Vec<ProofRow> = sqlx::query_as(PROOF_ROWS)
        .fetch_all(&reopened.writer.store.pool)
        .await?;
    assert_eq!(after, before);
    let migrated: Vec<(i64, String, bool, Vec<u8>)> = sqlx::query_as(
        "SELECT version, description, success, checksum FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&reopened.writer.store.pool)
    .await?;
    assert_eq!(
        migrated.iter().map(|row| row.0).collect::<Vec<_>>(),
        (1..=20).collect::<Vec<_>>()
    );
    assert_eq!(&migrated[..19], legacy.as_slice());
    reopened.wait_eligible(&claim).await?;
    let mut expected = queued;
    expected.replayed = true;
    assert_eq!(
        reopened
            .writer
            .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
            .await?,
        vec![expected]
    );
    assert_eq!(reopened.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

//! Proof immutability uses the real CognitiveStore and original FinalUse owner.

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
async fn pre_boundary_proofs_reject_replace_for_every_identity() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let claim = fixture.reject_claim(&queued).await?;
    let cut = fixture.writer.recovery_anchor().await?;
    let mut connection = fixture.writer.store.pool.acquire().await?;
    sqlx::query("PRAGMA foreign_keys=ON")
        .execute(&mut *connection)
        .await?;
    sqlx::query("PRAGMA recursive_triggers=OFF")
        .execute(&mut *connection)
        .await?;
    assert_eq!(
        sqlx::query_scalar::<_, i64>("PRAGMA recursive_triggers")
            .fetch_one(&mut *connection)
            .await?,
        0
    );
    let before: Vec<ProofRow> = sqlx::query_as(PROOF_ROWS)
        .fetch_all(&mut *connection)
        .await?;
    assert_eq!(before.len(), 1);
    let (rowid, operation, entered, settled, event, lease, payload, digest, recorded) = &before[0];
    let first_claim: String = sqlx::query_scalar(
        "SELECT claim_sha256 FROM cognitive_operation_dispatch_claims
         WHERE operation_id = ? ORDER BY claim_sequence LIMIT 1",
    )
    .bind(operation)
    .fetch_one(&mut *connection)
    .await?;
    assert_ne!(&first_claim, entered);
    assert_ne!(&first_claim, settled);
    // Every substituted claim digest names an existing row, so foreign-key
    // failures cannot stand in for the new immutable-identity guard. The rowid
    // case changes both declared keys, isolating the implicit rowid collision.
    let collisions = [
        (
            "both declared keys",
            rowid + 1,
            entered.as_str(),
            settled.as_str(),
        ),
        (
            "entered key only",
            rowid + 1,
            entered.as_str(),
            first_claim.as_str(),
        ),
        (
            "settled key only",
            rowid + 1,
            first_claim.as_str(),
            settled.as_str(),
        ),
        ("rowid only", *rowid, first_claim.as_str(), entered.as_str()),
    ];
    for verb in ["INSERT", "INSERT OR REPLACE", "REPLACE"] {
        for (identity, candidate_rowid, candidate_entered, candidate_settled) in collisions {
            sqlx::query("BEGIN IMMEDIATE")
                .execute(&mut *connection)
                .await?;
            let result = sqlx::query(sqlx::AssertSqlSafe(format!(
                "{verb} INTO cognitive_operation_pre_boundary_rejections (
                    rowid, operation_id, entered_claim_sha256, settled_claim_sha256,
                    dispatch_event_id, lease_id, proof_json, proof_sha256, recorded_at_unix_ms
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )))
            .bind(candidate_rowid)
            .bind(operation)
            .bind(candidate_entered)
            .bind(candidate_settled)
            .bind(event)
            .bind(lease)
            .bind(payload)
            .bind(digest)
            .bind(recorded + 1)
            .execute(&mut *connection)
            .await;
            let after: Vec<ProofRow> = sqlx::query_as(PROOF_ROWS)
                .fetch_all(&mut *connection)
                .await?;
            sqlx::query("ROLLBACK").execute(&mut *connection).await?;
            let error = result.expect_err("an existing proof cannot be inserted over");
            assert!(
                error
                    .to_string()
                    .contains("pre-boundary rejection proofs are immutable"),
                "{verb} with {identity} must fail at the proof guard: {error}"
            );
            assert_eq!(
                after, before,
                "{verb} with {identity} changed the original complete row"
            );
        }
    }
    drop(connection);
    assert_eq!(fixture.writer.recovery_anchor().await?, cut);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);

    // The rejected mutations do not consume the valid proof. The same K/D can
    // still follow the existing fresh external grant path, and the original
    // writer can insert a distinct proof with an automatically assigned rowid.
    fixture.wait_eligible(&claim).await?;
    let (binding, fresh) = fixture.signed(&queued, /*nonce*/ 2).await?;
    assert_eq!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &fresh, &binding, queued)
            .await?
            .state,
        LocalOutcomeState::Committed
    );
    let next = fixture.prepare("hos2:proof:fresh", /*sequence*/ 2).await?;
    fixture
        .writer
        .claim_dispatch_lease(&next, /*lease_duration_ms*/ 5_000)
        .await?;
    let (binding, mut invalid) = fixture.signed(&next, /*nonce*/ 3).await?;
    invalid.signature[0] ^= 1;
    assert!(matches!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &invalid, &binding, next)
            .await,
        Err(ProductionWriterError::FinalUse(
            FinalUseError::InvalidSignature
        ))
    ));
    let after: Vec<ProofRow> = sqlx::query_as(PROOF_ROWS)
        .fetch_all(&fixture.writer.store.pool)
        .await?;
    assert_eq!(after.len(), 2);
    assert!(
        after.contains(&before[0]),
        "new proof insertion changed prior proof history"
    );
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

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
    // Isolate the exact v16 schema/ledger after producing a real owner witness.
    // Migration 17 adds only this trigger; no proof or older migration bytes
    // are changed. This fixture is not a production recovery fallback.
    sqlx::raw_sql(
        "BEGIN IMMEDIATE;
         DROP TRIGGER cognitive_operation_pre_boundary_rejections_no_replace;
         DELETE FROM _sqlx_migrations WHERE version = 17;
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
        (1..=16).collect::<Vec<_>>()
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
        (1..=17).collect::<Vec<_>>()
    );
    assert_eq!(&migrated[..16], legacy.as_slice());
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

#[tokio::test]
async fn pre_boundary_proof_guard_definition_is_checked_on_reopen() -> TestResult {
    for replacement in [
        "CREATE TRIGGER cognitive_operation_pre_boundary_rejections_no_replace
         BEFORE INSERT ON cognitive_operation_pre_boundary_rejections WHEN 0 BEGIN
         SELECT RAISE(ABORT, 'pre-boundary rejection proofs are immutable'); END;",
        "CREATE TRIGGER cognitive_operation_pre_boundary_rejections_no_replace
         BEFORE INSERT ON cognitive_operation_pre_boundary_rejections
         WHEN EXISTS (SELECT 1 FROM cognitive_operation_pre_boundary_rejections
             WHERE operation_id = NEW.operation_id AND entered_claim_sha256 = NEW.entered_claim_sha256)
         BEGIN SELECT RAISE(ABORT, 'pre-boundary rejection proofs are immutable'); END;",
    ] {
        let directory = tempfile::tempdir()?;
        let fixture = Fixture::open(directory.path()).await?;
        sqlx::query("DROP TRIGGER cognitive_operation_pre_boundary_rejections_no_replace")
            .execute(&fixture.writer.store.pool).await?;
        sqlx::raw_sql(replacement).execute(&fixture.writer.store.pool).await?;
        fixture.writer.store.pool.close().await;
        drop(fixture);
        let error = match Fixture::open(directory.path()).await {
            Ok(_) => return Err("a weakened proof guard must fail the schema oracle".into()),
            Err(error) => error,
        };
        assert!(error.to_string().contains("schema definition oracle mismatch"), "{error}");
    }
    Ok(())
}

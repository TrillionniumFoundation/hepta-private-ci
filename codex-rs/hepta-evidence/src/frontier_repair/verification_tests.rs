use super::*;

#[tokio::test]
async fn disabled_immutability_trigger_is_rejected() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    sqlx::raw_sql(
        "DROP TRIGGER evidence_frontier_repair_events_no_update;
         CREATE TRIGGER evidence_frontier_repair_events_no_update
         BEFORE UPDATE ON evidence_frontier_repair_events WHEN 0
         BEGIN SELECT RAISE(ABORT, 'evidence frontier repair events are immutable'); END;",
    )
    .execute(&store.pool)
    .await
    .expect("simulate a disabled trigger retaining every required substring");
    assert!(matches!(
        store.verify_frontier_repair_ledger().await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[tokio::test]
async fn rehashed_unknown_event_version_is_rejected() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare repair");
    let mut transaction = store
        .pool
        .begin()
        .await
        .expect("offline mutation transaction");
    let original: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'evidence_frontier_repair_events_no_update'",
    )
    .fetch_one(&mut *transaction)
    .await
    .expect("read original trigger");
    sqlx::query("DROP TRIGGER evidence_frontier_repair_events_no_update")
        .execute(&mut *transaction)
        .await
        .expect("simulate offline mutation");
    let json: String = sqlx::query_scalar("SELECT event_json FROM evidence_frontier_repair_events")
        .fetch_one(&mut *transaction)
        .await
        .expect("read event");
    let mut event: super::super::EvidenceFrontierRepairEventV1 =
        serde_json::from_str(&json).expect("decode event");
    event.schema_version += 1;
    let bytes = crate::canonical::canonical_json(&event).expect("recanonicalize mutation");
    sqlx::query("UPDATE evidence_frontier_repair_events SET event_json = ?, event_sha256 = ?")
        .bind(String::from_utf8(bytes.clone()).expect("UTF-8 JSON"))
        .bind(Sha256Digest::for_bytes(&bytes).as_str())
        .execute(&mut *transaction)
        .await
        .expect("persist rehashed unknown version");
    sqlx::query(sqlx::AssertSqlSafe(original))
        .execute(&mut *transaction)
        .await
        .expect("restore original trigger");
    transaction.commit().await.expect("commit offline mutation");
    assert!(matches!(
        store.verify_frontier_repair_ledger().await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[tokio::test]
async fn orphan_event_is_rejected_by_attachment_gate() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let mut connection = store.pool.acquire().await.expect("dedicated connection");
    sqlx::query("PRAGMA foreign_keys = OFF")
        .execute(&mut *connection)
        .await
        .expect("simulate offline writer");
    sqlx::query(
        "INSERT INTO evidence_frontier_repair_events
         (repair_id, event_index, event_kind, event_json, event_sha256, observed_at_ms)
         VALUES ('repair:missing', 1, 'prepared', '{}', ?, 1)",
    )
    .bind(digest("orphan").as_str())
    .execute(&mut *connection)
    .await
    .expect("insert orphan event");
    sqlx::query("PRAGMA foreign_keys = ON")
        .execute(&mut *connection)
        .await
        .expect("restore enforcement");
    drop(connection);
    assert!(matches!(
        store.verify_frontier_repair_ledger().await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[tokio::test]
async fn expired_prepared_authorization_cannot_begin_dispatch() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    let prepared = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare repair");
    assert!(matches!(
        store
            .begin_frontier_repair_dispatch(
                &prepared.repair_id,
                "dispatch:expired",
                &target.backend_identity_sha256,
                authorization.expires_at_unix_ms + 1,
            )
            .await,
        Err(EvidenceError::InvalidRecord(_))
    ));
    assert_eq!(
        store
            .get_frontier_repair(&prepared.repair_id)
            .await
            .expect("read repair"),
        Some(prepared)
    );
}

#[tokio::test]
async fn rehashed_dispatch_backend_substitution_is_rejected() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    let prepared = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare repair");
    store
        .begin_frontier_repair_dispatch(
            &prepared.repair_id,
            "dispatch:original",
            &target.backend_identity_sha256,
            now + 1,
        )
        .await
        .expect("dispatch exact target");
    let mut transaction = store
        .pool
        .begin()
        .await
        .expect("offline mutation transaction");
    let triggers: Vec<String> = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name IN
         ('evidence_frontier_repairs_transition', 'evidence_frontier_repair_events_no_update')",
    )
    .fetch_all(&mut *transaction)
    .await
    .expect("capture original triggers");
    sqlx::raw_sql(
        "DROP TRIGGER evidence_frontier_repairs_transition;
        DROP TRIGGER evidence_frontier_repair_events_no_update;",
    )
    .execute(&mut *transaction)
    .await
    .expect("simulate offline mutation");
    let substituted = digest("different backend");
    sqlx::query("UPDATE evidence_frontier_repairs SET backend_identity_sha256 = ?")
        .bind(substituted.as_str())
        .execute(&mut *transaction)
        .await
        .expect("substitute row backend");
    let json: String = sqlx::query_scalar(
        "SELECT event_json FROM evidence_frontier_repair_events WHERE event_index = 2",
    )
    .fetch_one(&mut *transaction)
    .await
    .expect("read dispatch event");
    let mut event: super::super::EvidenceFrontierRepairEventV1 =
        serde_json::from_str(&json).expect("decode dispatch event");
    event.backend_identity_sha256 = Some(substituted);
    let bytes = crate::canonical::canonical_json(&event).expect("recanonicalize event");
    sqlx::query("UPDATE evidence_frontier_repair_events SET event_json = ?, event_sha256 = ? WHERE event_index = 2")
        .bind(String::from_utf8(bytes.clone()).expect("UTF-8 JSON"))
        .bind(Sha256Digest::for_bytes(&bytes).as_str()).execute(&mut *transaction).await.expect("rehash dispatch event");
    for original in triggers {
        sqlx::query(sqlx::AssertSqlSafe(original))
            .execute(&mut *transaction)
            .await
            .expect("restore original trigger");
    }
    transaction.commit().await.expect("commit offline mutation");
    assert!(matches!(
        store.verify_frontier_repair_ledger().await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[test]
fn schema_extraction_cannot_silently_omit_or_duplicate_guards() {
    let migration = include_str!("../../migrations/0017_frontier_repair_publication.sql");
    for invalid in [
        migration.replacen("\nCREATE TRIGGER", "\n CREATE TRIGGER", 1),
        migration.replace(
            "evidence_frontier_repair_events_no_delete",
            "unexpected_trigger",
        ),
        format!(
            "{migration}\nCREATE TRIGGER evidence_frontier_repairs_no_delete BEGIN SELECT 1; END;"
        ),
    ] {
        assert!(matches!(
            super::super::repair_schema_definitions(&invalid),
            Err(EvidenceError::Corrupt(_))
        ));
    }
}

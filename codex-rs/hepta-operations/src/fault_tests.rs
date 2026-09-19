use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DurableOperationError;
use crate::DurableOperationStore;
use crate::OperationIntentV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn intent(index: usize) -> OperationIntentV1 {
    let operation_id = format!("operation:disk-full:{index:05}");
    OperationIntentV1 {
        scope_id: id("scope:disk-full"),
        operation_id: id(&operation_id),
        expected_predecessor: None,
        destination: id("automation.taskflow"),
        payload_digest: Digest32::of_bytes(operation_id.as_bytes()),
        owner_generation: generation(1),
    }
}

#[tokio::test]
async fn sqlite_full_never_leaves_half_of_the_ledger_outbox_transaction() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let mut store = DurableOperationStore::open(&path).await.expect("open");

    sqlx::query("VACUUM")
        .execute(&store.pool)
        .await
        .expect("vacuum");
    let pages: i64 = sqlx::query_scalar("PRAGMA page_count")
        .fetch_one(&store.pool)
        .await
        .expect("page count");
    assert!(pages > 0);
    // The cap belongs to a connection, not to the pool or database file.
    // Install it in every new connection's options while retaining the real
    // four-connection owner store. A one-off PRAGMA on an arbitrary pooled
    // connection lets another writer silently evade the fault.
    let options = store
        .pool
        .connect_options()
        .as_ref()
        .clone()
        .pragma("max_page_count", pages.to_string());
    store.pool.close().await;
    store.pool = sqlx::sqlite::SqlitePoolOptions::new()
        .max_connections(4)
        .min_connections(4)
        .connect_with(options)
        .await
        .expect("reopen owner pool with per-connection fault");
    let mut held = Vec::new();
    for _ in 0..4 {
        let mut connection = store.pool.acquire().await.expect("fault connection");
        let capped: i64 = sqlx::query_scalar("PRAGMA max_page_count")
            .fetch_one(&mut *connection)
            .await
            .expect("read back page cap");
        assert_eq!(
            capped, pages,
            "every writer must have the disk-full fault armed"
        );
        held.push(connection);
    }
    drop(held);

    let mut saw_full = false;
    for index in 0..20_000 {
        let before: (i64, i64) = sqlx::query_as(
            "SELECT (SELECT COUNT(*) FROM operation_ledger),
                    (SELECT COUNT(*) FROM cross_owner_outbox)",
        )
        .fetch_one(&store.pool)
        .await
        .expect("before counts");
        match store.prepare_intent(&intent(index)).await {
            Ok(_) => {
                let after: (i64, i64) = sqlx::query_as(
                    "SELECT (SELECT COUNT(*) FROM operation_ledger),
                            (SELECT COUNT(*) FROM cross_owner_outbox)",
                )
                .fetch_one(&store.pool)
                .await
                .expect("after counts");
                assert_eq!(after.0, before.0 + 1);
                assert_eq!(after.1, before.1 + 1);
            }
            Err(DurableOperationError::Unavailable(message))
                if message.to_ascii_lowercase().contains("full") =>
            {
                let after: (i64, i64) = sqlx::query_as(
                    "SELECT (SELECT COUNT(*) FROM operation_ledger),
                            (SELECT COUNT(*) FROM cross_owner_outbox)",
                )
                .fetch_one(&store.pool)
                .await
                .expect("failure counts");
                assert_eq!(after, before, "SQLITE_FULL exposed a partial transaction");
                saw_full = true;
                break;
            }
            Err(error) => panic!("unexpected fault result: {error}"),
        }
    }
    assert!(saw_full, "fault fixture never reached SQLITE_FULL");
}

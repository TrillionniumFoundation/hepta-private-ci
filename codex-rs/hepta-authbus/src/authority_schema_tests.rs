use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;

#[tokio::test]
async fn missing_and_replaced_authority_triggers_fail_closed_on_reopen() {
    let root = tempfile::tempdir().unwrap();
    let baseline = root.path().join("fixture.sqlite");
    let fixture = AuthBusAuthorityStore::open(&baseline).await.unwrap();
    let triggers = sqlx::query_as::<_, (String, String)>(
        "SELECT name, tbl_name FROM sqlite_schema WHERE type = 'trigger' ORDER BY name",
    )
    .fetch_all(&fixture.pool)
    .await
    .unwrap();
    assert!(!triggers.is_empty());
    // Migrate the trusted fixture once, then checkpoint and close ALL handles
    // before copying it. Each corruption case still opens and validates its own
    // durable database; no live SQLite/WAL file is copied or repaired.
    sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
        .execute(&fixture.pool)
        .await
        .unwrap();
    fixture.pool.close().await;
    for (name, table) in triggers {
        for replace in [false, true] {
            let path = root.path().join(format!("{name}-{replace}.sqlite"));
            std::fs::copy(&baseline, &path).unwrap();
            let store = AuthBusAuthorityStore::open(&path).await.unwrap();
            // Keep DDL on one connection: a different pooled connection may
            // still hold the pre-DROP schema cache while preparing CREATE.
            // This is fixture mutation, not permission for runtime repair.
            let mut connection = store.pool.acquire().await.unwrap();
            // These identifiers come from the freshly migrated reference.
            // Quote and escape them before forming identifier-only DDL; no
            // data or untrusted SQL fragments are interpolated.
            let quoted_name = format!("\"{}\"", name.replace('"', "\"\""));
            let quoted_table = format!("\"{}\"", table.replace('"', "\"\""));
            sqlx::query(sqlx::AssertSqlSafe(format!("DROP TRIGGER {quoted_name}")))
                .execute(&mut *connection)
                .await
                .unwrap();
            if replace {
                sqlx::query(sqlx::AssertSqlSafe(format!(
                    "CREATE TRIGGER {quoted_name} AFTER UPDATE ON {quoted_table} BEGIN SELECT 1; END"
                )))
                .execute(&mut *connection)
                .await
                .unwrap();
            }
            let check: String = sqlx::query_scalar("PRAGMA quick_check")
                .fetch_one(&mut *connection)
                .await
                .unwrap();
            assert_eq!(check, "ok");
            let remaining: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'trigger' AND name = ?",
            )
            .bind(&name)
            .fetch_one(&mut *connection)
            .await
            .unwrap();
            assert_eq!(remaining, i64::from(replace));
            drop(connection);
            store.pool.close().await;
            assert!(
                matches!(
                    AuthBusAuthorityStore::open(&path).await,
                    Err(AuthBusAuthorityError::CorruptState(_))
                ),
                "trigger {name}, replacement {replace}"
            );
        }
    }
}

#[tokio::test]
async fn missing_tables_and_unrecognized_schema_objects_fail_closed() {
    for statement in [
        "DROP TABLE authbus_recovery_state",
        "CREATE TABLE competing_authority (id INTEGER PRIMARY KEY)",
        "CREATE INDEX unreviewed_policy_index ON authbus_policy (principal)",
    ] {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("authbus.sqlite");
        let store = AuthBusAuthorityStore::open(&path).await.unwrap();
        sqlx::query(statement).execute(&store.pool).await.unwrap();
        store.pool.close().await;
        assert!(
            matches!(
                AuthBusAuthorityStore::open(&path).await,
                Err(AuthBusAuthorityError::CorruptState(_))
            ),
            "schema mutation {statement}"
        );
    }
}

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;

#[tokio::test]
async fn missing_and_replaced_authority_triggers_fail_closed_on_reopen() {
    let root = tempfile::tempdir().unwrap();
    let fixture = AuthBusAuthorityStore::open(&root.path().join("fixture.sqlite"))
        .await
        .unwrap();
    let triggers = sqlx::query_as::<_, (String, String)>(
        "SELECT name, tbl_name FROM sqlite_schema WHERE type = 'trigger' ORDER BY name",
    )
    .fetch_all(&fixture.pool)
    .await
    .unwrap();
    assert!(!triggers.is_empty());
    fixture.pool.close().await;
    for (name, table) in triggers {
        for replace in [false, true] {
            let path = root.path().join(format!("{name}-{replace}.sqlite"));
            let store = AuthBusAuthorityStore::open(&path).await.unwrap();
            // These identifiers come from the freshly migrated reference.
            // Quote and escape them before forming identifier-only DDL; no
            // data or untrusted SQL fragments are interpolated.
            let quoted_name = format!("\"{}\"", name.replace('"', "\"\""));
            let quoted_table = format!("\"{}\"", table.replace('"', "\"\""));
            // Keep the destructive fixture DDL on one SQLite connection. A
            // pooled second connection may retain a stale schema cache between
            // DROP and CREATE and report the just-dropped trigger as existing.
            let mut connection = store.pool.acquire().await.unwrap();
            sqlx::query(sqlx::AssertSqlSafe(format!("DROP TRIGGER {quoted_name}")))
                .execute(&mut *connection)
                .await
                .unwrap();
            let remaining: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'trigger' AND name = ?",
            )
            .bind(&name)
            .fetch_one(&mut *connection)
            .await
            .unwrap();
            assert_eq!(remaining, 0, "trigger {name} remained after DROP");
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
            drop(connection);
            assert_eq!(check, "ok");
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

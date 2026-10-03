use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::super::super::CognitiveStore;
use super::*;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[tokio::test]
async fn complete_current_catalog_matches_compiled_scalar_and_vector_oracles() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(112);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("compiled owner");
    let mut transaction = store.pool.begin().await.expect("catalog snapshot");
    let references = references().await.expect("compiled references");
    let expected = &references[MIGRATOR.migrations.len()];
    let actual = schema_metadata(&mut transaction)
        .await
        .expect("complete native catalog");
    // Compare the entire catalog, including physical shadows and NULL-SQL
    // autoindexes, rather than only the registered required-object subset.
    assert_eq!(&actual, expected);
    assert!(actual.iter().any(|object| object.0 == "memory_fts_data"));
    assert!(actual.iter().any(|object| object.3.is_none()));
    let query = compiled_catalog_query()
        .await
        .expect("compiled scalar SQL")
        .expect("current compiled SQL fits optimization bound");
    assert!(query.len() <= MAX_SCHEMA_BYTES as usize);
    let matches: bool = sqlx::query_scalar(sqlx::AssertSqlSafe(Arc::clone(query)))
        .fetch_one(&mut *transaction)
        .await
        .expect("native scalar equality");
    assert!(matches);
    verify_full_schema(&mut transaction)
        .await
        .expect("native full-schema fast path");
    transaction
        .rollback()
        .await
        .expect("close catalog snapshot");
    store.pool.close().await;
}

#[tokio::test]
async fn scalar_catalog_rejection_preserves_the_complete_typed_vector_oracle() {
    for mutation in [
        "UPDATE sqlite_schema SET type = 'view' WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET name = NULL WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET type = NULL WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET tbl_name = NULL WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET tbl_name = 'memory_revisions' WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET sql = 'changed compiled definition' WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET sql = NULL WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET sql = 'changed autoindex definition' WHERE name = 'sqlite_autoindex_source_ledger_1'",
        "DELETE FROM sqlite_schema WHERE name = 'source_ledger_no_update'",
        "INSERT INTO sqlite_schema(type, name, tbl_name, rootpage, sql)
         VALUES('table', 'catalog_extra', 'catalog_extra', 0, 'CREATE TABLE catalog_extra(v)')",
        "INSERT INTO sqlite_schema(type, name, tbl_name, rootpage, sql)
         SELECT type, name, tbl_name, rootpage, sql FROM sqlite_schema
         WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET (type, name, tbl_name, rootpage, sql) = (
            SELECT type, name, tbl_name, rootpage, sql FROM sqlite_schema
            WHERE name = 'source_ledger_no_delete'
         ) WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET sql = zeroblob(8) WHERE name = 'source_ledger_no_update'",
    ] {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(113);
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("compiled owner");
        let mut transaction = store.pool.begin().await.expect("catalog snapshot");
        let version: i64 = sqlx::query_scalar("PRAGMA schema_version")
            .fetch_one(&mut *transaction)
            .await
            .expect("cached schema version");
        sqlx::query("PRAGMA writable_schema = ON")
            .execute(&mut *transaction)
            .await
            .expect("allow fixed catalog-data mutation");
        sqlx::query(mutation)
            .execute(&mut *transaction)
            .await
            .expect("mutate raw catalog data without schema reload");
        let after_version: i64 = sqlx::query_scalar("PRAGMA schema_version")
            .fetch_one(&mut *transaction)
            .await
            .expect("schema version after data-only mutation");
        assert_eq!(after_version, version);
        let expected = &references().await.expect("compiled references")[MIGRATOR.migrations.len()];
        let old_result = schema_metadata(&mut transaction)
            .await
            .and_then(|actual| compare_schema(&actual, expected));
        let old_error = old_result.expect_err("old complete oracle must reject mutation");
        let count = schema_metadata_count(&mut transaction)
            .await
            .expect("bounded variant catalog");
        let query = compiled_catalog_query()
            .await
            .expect("compiled scalar SQL")
            .expect("current compiled SQL fits optimization bound");
        let set_matches: bool = sqlx::query_scalar(sqlx::AssertSqlSafe(Arc::clone(query)))
            .fetch_one(&mut *transaction)
            .await
            .expect("raw catalog set comparison");
        assert!(
            count != expected.len() as i64 || !set_matches,
            "cardinality and all-field sets must reject every old-oracle mismatch"
        );
        if mutation.starts_with("INSERT INTO sqlite_schema")
            && mutation.contains("SELECT type, name")
        {
            // An identical duplicate is invisible to EXCEPT. The cardinality
            // gate is therefore necessary, even with unique compiled names.
            assert!(set_matches);
            assert_eq!(count, expected.len() as i64 + 1);
        }
        if mutation.contains("SET (type, name, tbl_name, rootpage, sql)") {
            // Equal cardinality and actual-subset containment would accept
            // this duplicate/missing pair. Reference containment rejects it.
            assert_eq!(count, expected.len() as i64);
            assert!(!set_matches);
        }
        let error = verify_full_schema(&mut transaction)
            .await
            .expect_err("fast path must retain the original typed refusal");
        assert_eq!(error.to_string(), old_error.to_string());
        sqlx::query("PRAGMA writable_schema = OFF")
            .execute(&mut *transaction)
            .await
            .expect("close raw catalog mutation mode");
        transaction
            .rollback()
            .await
            .expect("restore original compiled catalog");
        let mut clean = store.pool.begin().await.expect("restored snapshot");
        verify_full_schema(&mut clean)
            .await
            .expect("rollback retains clean catalog and immutable reference");
        clean.rollback().await.expect("close restored snapshot");
        store.pool.close().await;
    }
}

#[tokio::test]
async fn full_schema_catalog_byte_bounds_still_precede_scalar_or_typed_comparison() {
    for mutation in [
        "UPDATE sqlite_schema SET sql = zeroblob(1048577) WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET name = NULL, sql = zeroblob(1048577) WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET type = NULL, sql = zeroblob(1048577) WHERE name = 'source_ledger_no_update'",
        "UPDATE sqlite_schema SET tbl_name = NULL, sql = zeroblob(1048577) WHERE name = 'source_ledger_no_update'",
    ] {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(114);
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("compiled owner");
        let mut transaction = store.pool.begin().await.expect("catalog snapshot");
        sqlx::query("PRAGMA writable_schema = ON")
            .execute(&mut *transaction)
            .await
            .expect("allow raw catalog mutation");
        sqlx::query(mutation)
            .execute(&mut *transaction)
            .await
            .expect("catalog exceeds original byte bound even with a NULL field");
        // NULL in a different field must not null out this row's byte total.
        // The typed fetch would reject NULL or BLOB storage differently, so
        // the original Invalid result proves admission refuses it first.
        assert!(matches!(
            verify_full_schema(&mut transaction).await,
            Err(CognitiveStoreError::Invalid(message))
                if message == "cognitive compiled schema metadata exceeds bounds"
        ));
        sqlx::query("PRAGMA writable_schema = OFF")
            .execute(&mut *transaction)
            .await
            .expect("close raw mutation mode");
        transaction.rollback().await.expect("restore catalog");
        store.pool.close().await;
    }
}

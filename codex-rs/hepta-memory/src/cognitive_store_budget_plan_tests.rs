use pretty_assertions::assert_eq;
use sqlx::SqliteConnection;

use super::*;

#[expect(
    clippy::disallowed_methods,
    reason = "fixed in-memory expression equivalence fixture never opens an owner path"
)]
#[tokio::test]
async fn declared_type_hints_preserve_budget_for_every_actual_sqlite_type() {
    let pool = SqlitePoolOptions::new()
        .max_connections(/*max*/ 1)
        .connect("sqlite::memory:")
        .await
        .expect("equivalence fixture");
    let mut connection = pool.acquire().await.expect("fixture connection");
    // Include storage-class violations of every hint, Unicode/NUL text, raw
    // invalid UTF-8 text, signed integer bounds, infinities and the real row
    // byte ceiling. Declarations must never become trusted data assumptions.
    for declared_type in ["TEXT", "INTEGER", "REAL", "BLOB", ""] {
        for not_null in [false, true] {
            verify_actual_types(&mut connection, declared_type, not_null).await;
        }
    }
    drop(connection);
    pool.close().await;
}

async fn verify_actual_types(
    connection: &mut SqliteConnection,
    declared_type: &str,
    not_null: bool,
) {
    let hinted = value_bytes("v", declared_type, not_null);
    let query = format!(
        "WITH values_to_check(v) AS (VALUES
           (NULL), (0), (-9223372036854775808), (9223372036854775807),
           (0.0), (1.25), (1e999), (-1e999), (''), ('é中🦀'),
           (X''), (X'00ff01'), (CAST(X'ff00fe' AS TEXT)), (?), (?), (?))
         SELECT COUNT(*), SUM(({hinted}) IS NOT (
           CASE typeof(v) WHEN 'null' THEN 16 WHEN 'integer' THEN 64
           WHEN 'real' THEN 64 ELSE 24 + octet_length(v) END))
         FROM values_to_check"
    );
    let (count, mismatches): (i64, i64) = sqlx::query_as(sqlx::AssertSqlSafe(query))
        .bind("nul\0trailer")
        .bind(vec![
            0xff_u8;
            usize::try_from(super::super::MAX_ROW_BYTES)
                .expect("positive bound")
        ])
        .bind("é".repeat(1_048_576))
        .fetch_one(connection)
        .await
        .expect("exact SQLite type comparison");
    assert_eq!(count, 16);
    assert_eq!(mismatches, 0, "{declared_type}, not_null={not_null}");
}

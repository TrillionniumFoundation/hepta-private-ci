//! Immutable SQL plans for the complete compiled owner schema, never usage.

use std::sync::Arc;

use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::sqlite::SqlitePoolOptions;
use tokio::sync::OnceCell;

use super::super::CognitiveStoreError;
use super::super::MIGRATOR;
use super::super::REQUIRED_SCHEMA_OBJECTS;
use super::super::classify_migrate_error;
use super::super::unavailable;

static QUERIES: OnceCell<Vec<Arc<str>>> = OnceCell::const_new();
const MAX_TABLES: usize = 256;

#[expect(
    clippy::disallowed_methods,
    reason = "fixed in-memory query plan runs only compiled migrations and never opens an owner path"
)]
pub(super) async fn queries() -> Result<&'static Vec<Arc<str>>, CognitiveStoreError> {
    QUERIES
        .get_or_try_init(|| async {
            let pool = SqlitePoolOptions::new()
                .max_connections(/*max*/ 1)
                .connect("sqlite::memory:")
                .await
                .map_err(unavailable)?;
            let result = async {
                MIGRATOR.run(&pool).await.map_err(classify_migrate_error)?;
                let mut connection = pool.acquire().await.map_err(unavailable)?;
                build(&mut connection).await
            }
            .await;
            pool.close().await;
            result
        })
        .await
}

async fn build(connection: &mut SqliteConnection) -> Result<Vec<Arc<str>>, CognitiveStoreError> {
    let mut tables: Vec<String> = sqlx::query_scalar(
        "SELECT name FROM pragma_table_list
         WHERE schema = 'main' AND type IN ('table', 'virtual')
           AND name <> 'sqlite_schema' ORDER BY name LIMIT 257",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    if tables.len() > MAX_TABLES {
        return Err(CognitiveStoreError::Corrupt(
            "compiled cognitive budget table inventory exceeds bounds".to_string(),
        ));
    }
    tables.push("sqlite_schema".to_string());
    let mut queries = Vec::with_capacity(tables.len());
    for table in tables {
        if !matches!(table.as_str(), "sqlite_schema" | "_sqlx_migrations")
            && !REQUIRED_SCHEMA_OBJECTS.contains(&(table.as_str(), "table"))
        {
            return Err(CognitiveStoreError::Corrupt(
                "unregistered compiled cognitive budget table".to_string(),
            ));
        }
        let columns: Vec<(String, String, bool)> = if table == "sqlite_schema" {
            ["type", "name", "tbl_name", "sql"]
                .into_iter()
                .map(|name| (name.to_string(), "TEXT".to_string(), false))
                .collect()
        } else {
            let rows = sqlx::query(
                "SELECT name, type, \"notnull\" FROM pragma_table_info(?) ORDER BY cid LIMIT 65",
            )
            .bind(&table)
            .fetch_all(&mut *connection)
            .await
            .map_err(unavailable)?;
            if rows.is_empty() || rows.len() > 64 {
                return Err(CognitiveStoreError::Corrupt(
                    "compiled cognitive budget table columns invalid".to_string(),
                ));
            }
            rows.iter()
                .map(|row| {
                    Ok((
                        row.try_get("name")?,
                        row.try_get("type")?,
                        row.try_get("notnull")?,
                    ))
                })
                .collect::<Result<_, sqlx::Error>>()
                .map_err(unavailable)?
        };
        let row_bytes = columns
            .iter()
            .map(|(name, declared_type, not_null)| value_bytes(name, declared_type, *not_null))
            .collect::<Vec<_>>()
            .join(" + ");
        let table = table.replace('"', "\"\"");
        queries.push(Arc::from(format!(
            "SELECT COUNT(*), COALESCE(SUM(row_size), 0), COALESCE(MAX(row_size), 0) FROM \
             (SELECT {row_bytes} AS row_size FROM \"{table}\" LIMIT ?)"
        )));
    }
    Ok(queries)
}

fn value_bytes(name: &str, declared_type: &str, not_null: bool) -> String {
    let column = format!("\"{}\"", name.replace('"', "\"\""));
    // Declarations only choose the CASE order. All five actual SQLite types
    // retain the identical null/numeric/text/blob framing, including values
    // whose actual type violates their declaration or NOT NULL constraint.
    let preferred = match declared_type.to_ascii_uppercase().as_str() {
        "TEXT" => Some(("text", format!("24 + octet_length({column})"))),
        "INTEGER" => Some(("integer", "64".to_string())),
        "REAL" => Some(("real", "64".to_string())),
        "BLOB" => Some(("blob", format!("24 + octet_length({column})"))),
        _ => None,
    };
    let mut branches = Vec::with_capacity(4);
    if !not_null {
        branches.push(("null", "16".to_string()));
    }
    if let Some(preferred) = preferred {
        branches.push(preferred);
    }
    for (kind, bytes) in [("null", "16"), ("integer", "64"), ("real", "64")] {
        if !branches.iter().any(|(existing, _)| *existing == kind) {
            branches.push((kind, bytes.to_string()));
        }
    }
    let branches = branches
        .iter()
        .map(|(kind, bytes)| format!(" WHEN '{kind}' THEN {bytes}"))
        .collect::<String>();
    format!("CASE typeof({column}){branches} ELSE 24 + octet_length({column}) END")
}

#[cfg(test)]
#[path = "cognitive_store_budget_plan_tests.rs"]
mod tests;

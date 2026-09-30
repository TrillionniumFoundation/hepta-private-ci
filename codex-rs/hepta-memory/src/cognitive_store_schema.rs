//! Validate executable schema before any SQLite integrity scan evaluates it.

use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqliteConnection;

use super::CognitiveStoreError;
use super::REQUIRED_SCHEMA_OBJECTS;
use super::REQUIRED_SCHEMA_ORACLE_SHA256;
use super::unavailable;
use crate::framing::frame_part;

#[path = "cognitive_store_schema_admission.rs"]
mod admission;
pub(super) use admission::admit_before_migration;

const MAX_SCHEMA_BYTES: i64 = 1024 * 1024;
// Exact sqlite_schema SQL produced by the pinned SQLx migrator. A separate
// migration-backed test checks this oracle rather than deriving it from owner
// bytes. Defaults, CHECKs and generated columns are not accepted as equivalent.
const MIGRATIONS_SCHEMA: &str = "CREATE TABLE _sqlx_migrations (
    version BIGINT PRIMARY KEY,
    description TEXT NOT NULL,
    installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN NOT NULL,
    checksum BLOB NOT NULL,
    execution_time BIGINT NOT NULL
)";

pub(super) struct VerifiedSchema {
    pub digest: Sha256Digest,
    pub tables: Vec<&'static str>,
}

pub(super) async fn verify_existing_migrations_schema(
    connection: &mut SqliteConnection,
) -> Result<bool, CognitiveStoreError> {
    let object = sqlx::query(
        "SELECT type, length(CAST(sql AS BLOB)) AS length FROM sqlite_schema
         WHERE name = '_sqlx_migrations'",
    )
    .fetch_optional(&mut *connection)
    .await
    .map_err(unavailable)?;
    let Some(object) = object else {
        // A new store has no migration ledger yet. SQLx creates the fixed
        // compiled definition. Reject an existing view before SQLx can read it.
        return Ok(false);
    };
    let kind: String = object.try_get("type").map_err(unavailable)?;
    let length: Option<i64> = object.try_get("length").map_err(unavailable)?;
    if kind != "table" || length != Some(MIGRATIONS_SCHEMA.len() as i64) {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger schema mismatch".to_string(),
        ));
    }
    let sql: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = '_sqlx_migrations' AND type = 'table'",
    )
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if sql != MIGRATIONS_SCHEMA {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger schema mismatch".to_string(),
        ));
    }
    if sqlx::query(
        "SELECT 1 FROM sqlite_schema WHERE tbl_name = '_sqlx_migrations'
         AND type IN ('index', 'trigger') AND sql IS NOT NULL LIMIT 1",
    )
    .fetch_optional(&mut *connection)
    .await
    .map_err(unavailable)?
    .is_some()
    {
        return Err(CognitiveStoreError::Corrupt(
            "unregistered cognitive migration ledger executable schema".to_string(),
        ));
    }
    Ok(true)
}

pub(super) async fn verify_schema(
    connection: &mut SqliteConnection,
) -> Result<VerifiedSchema, CognitiveStoreError> {
    let mut schema = REQUIRED_SCHEMA_OBJECTS.to_vec();
    schema.sort_unstable_by_key(|(name, _)| *name);
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:cognitive:required-schema-oracle:v1");
    frame_part(&mut hasher, &(schema.len() as u64).to_be_bytes());
    let mut schema_bytes = 0_i64;
    for (name, kind) in &schema {
        let length: Option<i64> = sqlx::query_scalar(
            "SELECT length(CAST(sql AS BLOB)) FROM sqlite_schema WHERE name = ? AND type = ?",
        )
        .bind(name)
        .bind(kind)
        .fetch_optional(&mut *connection)
        .await
        .map_err(unavailable)?
        .flatten();
        let length = length.filter(|value| *value > 0).ok_or_else(|| {
            CognitiveStoreError::Corrupt(format!("required cognitive schema object `{name}` is missing or has the wrong definition class"))
        })?;
        schema_bytes = schema_bytes
            .checked_add(length)
            .filter(|value| *value <= MAX_SCHEMA_BYTES)
            .ok_or_else(|| {
                CognitiveStoreError::Invalid("cognitive schema exceeds bounds".to_string())
            })?;
        let sql: String = sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
            .bind(name)
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        frame_part(&mut hasher, name.as_bytes());
        frame_part(&mut hasher, kind.as_bytes());
        frame_part(&mut hasher, sql.as_bytes());
    }
    let digest = Sha256Digest::from_sha256_output(hasher.finalize());
    if digest.as_str() != REQUIRED_SCHEMA_ORACLE_SHA256 {
        return Err(CognitiveStoreError::Corrupt(format!(
            "required cognitive schema definition oracle mismatch: {}",
            digest.as_str()
        )));
    }
    verify_existing_migrations_schema(connection).await?;
    let mut tables: Vec<&str> = schema
        .iter()
        .filter_map(|(name, kind)| (*kind == "table").then_some(*name))
        .collect();
    tables.push("_sqlx_migrations");
    tables.sort_unstable();
    // Only SQLite's actual catalog is excluded; LIKE 'sqlite_%' would also
    // hide user tables because '_' is a wildcard. Compiled shadow definitions
    // are separately checked below; the logical anchor still excludes their
    // physical contents. Extra
    // logical tables may contain arbitrary CHECK expressions; reject them
    // before quick_check/integrity_check can evaluate any owner SQL.
    let actual: Vec<String> = sqlx::query_scalar(
        "SELECT substr(name, 1, 129) FROM pragma_table_list
         WHERE schema = 'main' AND type IN ('table', 'virtual')
           AND name <> 'sqlite_schema' ORDER BY name LIMIT 256",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    if actual != tables {
        return Err(CognitiveStoreError::Corrupt(
            "unregistered cognitive table".to_string(),
        ));
    }
    let actual_executable: Vec<(String, String)> = sqlx::query_as(
        "SELECT substr(name, 1, 129), type FROM sqlite_schema
         WHERE type IN ('trigger', 'index', 'view') AND sql IS NOT NULL
         ORDER BY name LIMIT 256",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    let expected_executable: Vec<(&str, &str)> = schema
        .iter()
        .copied()
        .filter(|(_, kind)| *kind != "table")
        .collect();
    if actual_executable
        .iter()
        .map(|(name, kind)| (name.as_str(), kind.as_str()))
        .collect::<Vec<_>>()
        != expected_executable
    {
        return Err(CognitiveStoreError::Corrupt(
            "unregistered cognitive executable schema".to_string(),
        ));
    }
    admission::verify_full_schema(connection).await?;
    Ok(VerifiedSchema { digest, tables })
}

#[cfg(test)]
#[path = "cognitive_store_schema_tests.rs"]
mod tests;

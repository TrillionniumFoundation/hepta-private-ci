//! Version-aware admission of owner schema before compiled migrations execute.

use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::sqlite::SqlitePoolOptions;
use tokio::sync::OnceCell;

use super::super::CognitiveStoreError;
use super::super::MIGRATOR;
use super::super::classify_migrate_error;
use super::super::unavailable;
use super::MAX_SCHEMA_BYTES;
use super::verify_existing_migrations_schema;

const MAX_SCHEMA_OBJECTS: i64 = 1024;
const MAX_MIGRATIONS: usize = 64;
type SchemaObject = (String, String, String, Option<String>);
static REFERENCES: OnceCell<Vec<Vec<SchemaObject>>> = OnceCell::const_new();

pub(in super::super) async fn admit_before_migration(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    let has_ledger = verify_existing_migrations_schema(connection).await?;
    let prefix = if has_ledger {
        migration_prefix(connection).await?
    } else {
        0
    };
    let references = references().await?;
    let actual = schema_metadata(connection).await?;
    let expected = &references[prefix];
    if has_ledger {
        compare_schema(&actual, expected)
    } else {
        // An interrupted initialization may retain an empty compiled SQLx
        // ledger; a genuinely new database has no schema objects at all.
        compare_schema(&actual, &[])
    }
}

pub(super) async fn verify_full_schema(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    if migration_prefix(connection).await? != MIGRATOR.migrations.len() {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger is incomplete or has unknown entries".to_string(),
        ));
    }
    let references = references().await?;
    let actual = schema_metadata(connection).await?;
    compare_schema(&actual, &references[MIGRATOR.migrations.len()])
}

async fn migration_prefix(connection: &mut SqliteConnection) -> Result<usize, CognitiveStoreError> {
    if MIGRATOR.migrations.len() > MAX_MIGRATIONS {
        return Err(CognitiveStoreError::Invalid(
            "compiled cognitive migration count exceeds admission bounds".to_string(),
        ));
    }
    // These bounds run within SQLite before SQLx can materialize a checksum or
    // description from owner-controlled rows. The fixed SQLx table definition
    // was authenticated by the caller before this query.
    let mut bounds = sqlx::QueryBuilder::<sqlx::Sqlite>::new(
        "SELECT COUNT(*), COALESCE(MAX(
            typeof(version) != 'integer' OR typeof(description) != 'text' OR
            typeof(installed_on) != 'text' OR typeof(success) != 'integer' OR
            typeof(checksum) != 'blob' OR typeof(execution_time) != 'integer'
         ), 0), COALESCE(MAX(
            length(CAST(description AS BLOB)) > 1024 OR
            length(CAST(installed_on AS BLOB)) > 128 OR length(checksum) > 64
         ), 0)
         FROM (SELECT version, description, installed_on, success, checksum,
                      execution_time FROM _sqlx_migrations LIMIT ",
    );
    bounds
        .push_bind(MIGRATOR.migrations.len() as i64 + 1)
        .push(")");
    let (count, invalid_type, oversized): (i64, i64, i64) = bounds
        .build_query_as()
        .fetch_one(&mut *connection)
        .await
        .map_err(unavailable)?;
    if count > MIGRATOR.migrations.len() as i64 {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger is incomplete or has unknown entries".to_string(),
        ));
    }
    if oversized != 0 {
        return Err(CognitiveStoreError::Invalid(
            "cognitive migration ledger exceeds bounds".to_string(),
        ));
    }
    if invalid_type != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger has invalid storage types".to_string(),
        ));
    }
    let rows = sqlx::query(
        "SELECT version, description, success, checksum FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    for (row, migration) in rows.iter().zip(MIGRATOR.migrations.iter()) {
        let version: i64 = row.try_get("version").map_err(unavailable)?;
        let description: String = row.try_get("description").map_err(unavailable)?;
        let success: i64 = row.try_get("success").map_err(unavailable)?;
        let checksum: Vec<u8> = row.try_get("checksum").map_err(unavailable)?;
        if version != migration.version || description != migration.description.as_ref() {
            return Err(CognitiveStoreError::Corrupt(
                "cognitive migration ledger is not a continuous compiled prefix".to_string(),
            ));
        }
        if success != 1 {
            return Err(classify_migrate_error(sqlx::migrate::MigrateError::Dirty(
                version,
            )));
        }
        if checksum.as_slice() != migration.checksum.as_ref() {
            return Err(classify_migrate_error(
                sqlx::migrate::MigrateError::VersionMismatch(version),
            ));
        }
    }
    Ok(rows.len())
}

async fn schema_metadata(
    connection: &mut SqliteConnection,
) -> Result<Vec<SchemaObject>, CognitiveStoreError> {
    let (count, bytes): (i64, i64) = sqlx::query_as(
        "SELECT COUNT(*), COALESCE(SUM(object_bytes), 0) FROM (
            SELECT length(CAST(name AS BLOB)) + length(CAST(type AS BLOB)) +
                   length(CAST(tbl_name AS BLOB)) + COALESCE(length(CAST(sql AS BLOB)), 0)
                   AS object_bytes FROM sqlite_schema LIMIT 1025
         )",
    )
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if count > MAX_SCHEMA_OBJECTS || bytes > MAX_SCHEMA_BYTES {
        return Err(CognitiveStoreError::Invalid(
            "cognitive compiled schema metadata exceeds bounds".to_string(),
        ));
    }
    // Include ALL application objects, FTS shadow definitions and autoindexes.
    // Page numbers and contents are not schema authority. SQLite's own catalog
    // has no row in sqlite_schema, so no name-prefix exclusion is necessary.
    sqlx::query_as("SELECT name, type, tbl_name, sql FROM sqlite_schema ORDER BY name")
        .fetch_all(&mut *connection)
        .await
        .map_err(unavailable)
}

fn compare_schema(
    actual: &[SchemaObject],
    expected: &[SchemaObject],
) -> Result<(), CognitiveStoreError> {
    if actual == expected {
        return Ok(());
    }
    if let Some((_, kind, _, _)) = actual
        .iter()
        .find(|object| !expected.iter().any(|reference| reference.0 == object.0))
    {
        let label = if kind == "table" {
            "table"
        } else {
            "executable schema"
        };
        return Err(CognitiveStoreError::Corrupt(format!(
            "unregistered cognitive {label}"
        )));
    }
    Err(CognitiveStoreError::Corrupt(
        "compiled cognitive schema definition oracle mismatch".to_string(),
    ))
}

#[expect(
    clippy::disallowed_methods,
    reason = "fixed in-memory schema oracle runs only compiled migrations and never opens an owner path"
)]
async fn references() -> Result<&'static Vec<Vec<SchemaObject>>, CognitiveStoreError> {
    REFERENCES
        .get_or_try_init(|| async {
            if MIGRATOR.migrations.len() > MAX_MIGRATIONS {
                return Err(CognitiveStoreError::Invalid(
                    "compiled cognitive migration count exceeds admission bounds".to_string(),
                ));
            }
            let pool = SqlitePoolOptions::new()
                .max_connections(/*max*/ 1)
                .connect("sqlite::memory:")
                .await
                .map_err(unavailable)?;
            let result = async {
                MIGRATOR
                    .run_to(/*target*/ 0, &pool)
                    .await
                    .map_err(classify_migrate_error)?;
                let mut schemas = Vec::with_capacity(MIGRATOR.migrations.len() + 1);
                {
                    let mut connection = pool.acquire().await.map_err(unavailable)?;
                    schemas.push(schema_metadata(&mut connection).await?);
                }
                for migration in MIGRATOR.migrations.iter() {
                    MIGRATOR
                        .run_to(migration.version, &pool)
                        .await
                        .map_err(classify_migrate_error)?;
                    let mut connection = pool.acquire().await.map_err(unavailable)?;
                    schemas.push(schema_metadata(&mut connection).await?);
                }
                Ok(schemas)
            }
            .await;
            pool.close().await;
            result
        })
        .await
}

#[cfg(test)]
#[path = "cognitive_store_schema_admission_tests.rs"]
mod tests;

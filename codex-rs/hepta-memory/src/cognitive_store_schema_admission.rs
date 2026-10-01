//! Version-aware admission of owner schema before compiled migrations execute.

use std::collections::BTreeSet;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
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
use crate::cognitive_model::COGNITIVE_SCHEMA_VERSION;

const MAX_SCHEMA_OBJECTS: i64 = 1024;
const MAX_MIGRATIONS: usize = 64;
type SchemaObject = (String, String, String, Option<String>);
static REFERENCES: OnceCell<Vec<Vec<SchemaObject>>> = OnceCell::const_new();
static CATALOG_QUERY: OnceCell<Option<Arc<str>>> = OnceCell::const_new();

pub(in super::super) enum MigrationAdmission {
    AlreadyCurrentOwned,
    NeedsInitialization,
}

pub(in super::super) async fn admit_before_migration(
    connection: &mut SqliteConnection,
    owner: &AgentId,
) -> Result<MigrationAdmission, CognitiveStoreError> {
    // This fixed SQLite header scalar does not evaluate owner schema. Check it
    // before byte-bounding any TEXT metadata: public digests and text limits
    // use UTF-8, whereas CAST(TEXT AS BLOB) in UTF-16 uses different bytes.
    let encoding: String = sqlx::query_scalar("PRAGMA encoding")
        .fetch_one(&mut *connection)
        .await
        .map_err(unavailable)?;
    if encoding != "UTF-8" {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive owner database encoding must be UTF-8".to_string(),
        ));
    }
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
        compare_schema(&actual, expected)?;
    } else {
        // An interrupted initialization may retain an empty compiled SQLx
        // ledger; a genuinely new database has no schema objects at all.
        compare_schema(&actual, &[])?;
    }
    // Names and columns now match the compiled historical schema. Exclude
    // physical FTS shadow rows, including the defaults for an empty index.
    // Admit this same locked snapshot before ownership scans or migrations.
    let tables: Vec<String> = sqlx::query_scalar(
        "SELECT name FROM pragma_table_list
         WHERE schema = 'main' AND type IN ('table', 'virtual')
           AND name <> 'sqlite_schema' ORDER BY name LIMIT 1025",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    if tables.len() > MAX_SCHEMA_OBJECTS as usize {
        return Err(CognitiveStoreError::Invalid(
            "cognitive logical table inventory exceeds bounds".to_string(),
        ));
    }
    let table_names = tables.iter().map(String::as_str).collect::<Vec<_>>();
    super::super::budget::verify(connection, &table_names).await?;
    // Authenticate existing ownership before pending migrations can revoke or
    // replace old projections. Schema 0 has no metadata table; an empty
    // admitted table is an interrupted initialization only if all application
    // logical state is empty, rather than an invitation to adopt orphan facts.
    if actual.iter().any(|object| object.0 == "cognitive_meta") {
        // Keep identity and storage checks inside SQLite: no unbounded owner
        // string is materialized, even if an attacker bypassed row CHECKs.
        // Two rows are enough to reject a forged multi-row singleton table.
        let (count, invalid_meta, wrong_owner): (i64, bool, bool) = sqlx::query_as(
            "SELECT COUNT(*), COALESCE(MAX(
                 singleton != 1 OR typeof(singleton) != 'integer'
                 OR typeof(schema_version) != 'integer' OR schema_version != ?
                 OR typeof(owner_agent_id) != 'text'
                 OR length(CAST(owner_agent_id AS BLOB)) != 36
             ), 0), COALESCE(MAX(owner_agent_id != ?), 0)
             FROM (SELECT singleton, schema_version, owner_agent_id
                   FROM cognitive_meta LIMIT 2)",
        )
        .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
        .bind(owner.as_str())
        .fetch_one(&mut *connection)
        .await
        .map_err(unavailable)?;
        if count > 1 || invalid_meta {
            return Err(CognitiveStoreError::Corrupt(
                "cognitive owner metadata is invalid before migration".to_string(),
            ));
        }
        if wrong_owner {
            return Err(CognitiveStoreError::AccessDenied(
                "cognitive database belongs to a different agent".to_string(),
            ));
        }
        for table in tables {
            if table == "_sqlx_migrations" {
                continue;
            }
            let identifier = format!("\"{}\"", table.replace('"', "\"\""));
            if count == 0 {
                let mut query =
                    sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT EXISTS(SELECT 1 FROM ");
                query.push(&identifier).push(" LIMIT 1)");
                let has_state: bool = query
                    .build_query_scalar()
                    .fetch_one(&mut *connection)
                    .await
                    .map_err(unavailable)?;
                if has_state {
                    return Err(CognitiveStoreError::Corrupt(
                        "cognitive owner metadata is missing while application state remains"
                            .to_string(),
                    ));
                }
                continue;
            }
            // owner_agent_id consistently identifies the local producer/owner.
            // Federation consumer IDs intentionally remain external identities.
            let has_owner: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM pragma_table_info(?)
                 WHERE name = 'owner_agent_id')",
            )
            .bind(&table)
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
            if !has_owner {
                continue;
            }
            let mut query = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT EXISTS(SELECT 1 FROM ");
            query
                .push(&identifier)
                .push(" WHERE typeof(owner_agent_id) != 'text' OR owner_agent_id IS NOT ")
                .push_bind(owner.as_str());
            if table == "cognitive_operation_ledger" {
                query
                    .push(" OR typeof(subject_id) != 'text' OR subject_id IS NOT ")
                    .push_bind(owner.as_str());
            }
            query.push(" LIMIT 1)");
            let foreign_owner: bool = query
                .build_query_scalar()
                .fetch_one(&mut *connection)
                .await
                .map_err(unavailable)?;
            if foreign_owner {
                let message = if table == "source_ledger" || table == "memory_revisions" {
                    "agent-local cognitive store contains foreign-owned source or memory rows"
                        .to_string()
                } else {
                    format!("agent-local cognitive store contains foreign-owned {table} rows")
                };
                return Err(CognitiveStoreError::Corrupt(message));
            }
        }
        if count == 1 && prefix == MIGRATOR.migrations.len() {
            // This already-owned current database needs no initialization.
            // The caller closes this fence without writes and independently
            // verifies every current data contract in fresh admitted cuts.
            return Ok(MigrationAdmission::AlreadyCurrentOwned);
        }
    }
    if prefix > 0 {
        // Check the admitted historical constraints in this same locked cut.
        // A dangling citation or memory head can retain valid content hashes
        // and FTS rows, yet must not let migrations revoke old KG state first.
        if sqlx::query("SELECT 1 FROM pragma_foreign_key_check LIMIT 1")
            .fetch_optional(&mut *connection)
            .await
            .map_err(unavailable)?
            .is_some()
        {
            return Err(CognitiveStoreError::Corrupt(
                "SQLite foreign_key_check rejected the cognitive store".to_string(),
            ));
        }
        // Stable evidence and memory-search checks precede pending migrations
        // that revoke or replace old KG projections. A known-invalid ledger
        // must leave the authenticated historical state untouched on refusal.
        super::super::integrity::verify_admitted_ledger_contents(connection).await?;
        // CHECK constraints can be bypassed by a data-adversary writer while
        // hashes, references and FTS remain valid. Authenticate their compiled
        // definitions first, then accept only the single bounded success row.
        let quick_check: Vec<String> = sqlx::query_scalar("PRAGMA quick_check(1)")
            .fetch_all(&mut *connection)
            .await
            .map_err(unavailable)?;
        if quick_check != ["ok"] {
            return Err(CognitiveStoreError::Corrupt(
                "SQLite quick_check rejected the cognitive store".to_string(),
            ));
        }
    }
    Ok(MigrationAdmission::NeedsInitialization)
}

pub(in super::super) async fn verify_full_schema(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    if migration_prefix(connection).await? != MIGRATOR.migrations.len() {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger is incomplete or has unknown entries".to_string(),
        ));
    }
    let references = references().await?;
    let expected = &references[MIGRATOR.migrations.len()];
    let count = schema_metadata_count(connection).await?;
    // EXCEPT compares sets, so matching cardinality is required as well: a
    // duplicated catalog row must not disappear from the equality proof.
    if count == expected.len() as i64
        && let Some(query) = compiled_catalog_query().await?
    {
        // Every literal comes only from the fresh compiled migration oracle,
        // never owner catalog bytes. The bounded owner catalog is data here;
        // this query does not evaluate its stored SQL definitions.
        let matches: bool = sqlx::query_scalar(sqlx::AssertSqlSafe(Arc::clone(query)))
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        if matches {
            return Ok(());
        }
    }
    // Preserve the original typed fetch and mismatch classifications. This
    // also retains its bounds if an internal caller violated the snapshot
    // precondition. Historical/startup admission keeps this generic path.
    let actual = schema_metadata(connection).await?;
    compare_schema(&actual, expected)
}

async fn compiled_catalog_query() -> Result<Option<&'static Arc<str>>, CognitiveStoreError> {
    let query = CATALOG_QUERY
        .get_or_try_init(|| async {
            let references = references().await?;
            let expected = &references[MIGRATOR.migrations.len()];
            let mut names = BTreeSet::new();
            if expected.is_empty()
                || expected
                    .iter()
                    .any(|object| !names.insert(object.0.as_str()))
            {
                return Err(CognitiveStoreError::Corrupt(
                    "compiled cognitive schema reference names invalid".to_string(),
                ));
            }
            let mut query =
                String::from("WITH expected(name, type, tbl_name, sql) AS MATERIALIZED (VALUES ");
            for (index, (name, kind, table, sql)) in expected.iter().enumerate() {
                if index > 0 {
                    query.push(',');
                }
                query.push('(');
                for (field_index, value) in [
                    Some(name.as_str()),
                    Some(kind.as_str()),
                    Some(table.as_str()),
                    sql.as_deref(),
                ]
                .into_iter()
                .enumerate()
                {
                    if field_index > 0 {
                        query.push(',');
                    }
                    if let Some(value) = value {
                        if value.contains('\0') {
                            return Err(CognitiveStoreError::Corrupt(
                                "compiled cognitive schema reference contains NUL".to_string(),
                            ));
                        }
                        query.push('\'');
                        query.push_str(&value.replace('\'', "''"));
                        query.push('\'');
                    } else {
                        query.push_str("NULL");
                    }
                }
                query.push(')');
            }
            query.push_str(
                ") SELECT NOT EXISTS (
                    SELECT name, type, tbl_name, sql FROM sqlite_schema
                    EXCEPT SELECT name, type, tbl_name, sql FROM expected
                 ) AND NOT EXISTS (
                    SELECT name, type, tbl_name, sql FROM expected
                    EXCEPT SELECT name, type, tbl_name, sql FROM sqlite_schema
                 )",
            );
            if query.len() > MAX_SCHEMA_BYTES as usize {
                // Escaped SQL can be larger than its valid metadata. This is
                // an optimization bound, not a new owner admission policy.
                return Ok(None);
            }
            Ok(Some(Arc::<str>::from(query)))
        })
        .await?;
    Ok(query.as_ref())
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
    schema_metadata_count(connection).await?;
    // Include ALL application objects, FTS shadow definitions and autoindexes.
    // Page numbers and contents are not schema authority. SQLite's own catalog
    // has no row in sqlite_schema, so no name-prefix exclusion is necessary.
    sqlx::query_as("SELECT name, type, tbl_name, sql FROM sqlite_schema ORDER BY name")
        .fetch_all(&mut *connection)
        .await
        .map_err(unavailable)
}

async fn schema_metadata_count(
    connection: &mut SqliteConnection,
) -> Result<i64, CognitiveStoreError> {
    let (count, bytes): (i64, i64) = sqlx::query_as(
        "SELECT COUNT(*), COALESCE(SUM(object_bytes), 0) FROM (
            SELECT COALESCE(length(CAST(name AS BLOB)), 0) +
                   COALESCE(length(CAST(type AS BLOB)), 0) +
                   COALESCE(length(CAST(tbl_name AS BLOB)), 0) +
                   COALESCE(length(CAST(sql AS BLOB)), 0)
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
    Ok(count)
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

#[cfg(test)]
#[path = "cognitive_store_schema_ownership_tests.rs"]
mod ownership_tests;

#[cfg(test)]
#[path = "cognitive_store_schema_catalog_tests.rs"]
mod catalog_tests;

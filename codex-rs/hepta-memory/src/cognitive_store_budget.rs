//! Logical owner-state admission before startup and durable owner commits.
//!
//! Callers admit the compiled schema first. Journal verifiers repeat the check
//! inside their own read transaction so concurrent normal appends cannot move
//! their fetches beyond an earlier startup snapshot's admission. These are
//! logical value budgets, not physical file limits or latency qualifications.

use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqliteConnection;
use sqlx::Transaction;

use super::CognitiveStoreError;
use super::REQUIRED_SCHEMA_OBJECTS;
use super::unavailable;

pub(super) const MAX_ROWS: i64 = 262_144;
pub(super) const MAX_BYTES: i64 = 128 * 1024 * 1024;
pub(super) const MAX_ROW_BYTES: i64 = 2 * 1024 * 1024;

const JOURNAL_TABLES: &[&str] = &[
    "cognitive_local_leases",
    "cognitive_local_events",
    "cognitive_local_outbox",
    "cognitive_logical_turns",
    "cognitive_logical_turn_attempts",
    "cognitive_operation_ledger",
    "cognitive_operation_dispatch_claims",
    "cognitive_compact_events",
    "cognitive_h7_trajectory_events",
];

struct Budget {
    remaining_rows: i64,
    remaining_bytes: i64,
}

impl Budget {
    fn admit(&mut self, count: i64, bytes: i64, largest: i64) -> Result<(), CognitiveStoreError> {
        if count > self.remaining_rows || bytes > self.remaining_bytes || largest > MAX_ROW_BYTES {
            return Err(CognitiveStoreError::Invalid(
                "cognitive logical state exceeds startup row/byte bounds".to_string(),
            ));
        }
        self.remaining_rows -= count;
        self.remaining_bytes -= bytes;
        Ok(())
    }
}

impl Default for Budget {
    fn default() -> Self {
        Self {
            remaining_rows: MAX_ROWS,
            remaining_bytes: MAX_BYTES,
        }
    }
}

/// Commit only a final owner state that ordinary startup can admit.
///
/// Use the writer's own transaction: a different pool connection cannot see
/// its uncommitted changes, and process-local usage counters cannot account for
/// other store instances. SQLite serializes writers, so admission stays valid
/// until this transaction commits. An admission error drops and rolls back the
/// transaction before the caller can return a successful durable receipt.
///
/// The full compiled-schema check supplies every logical table, including the
/// FTS virtual contents, and authenticates their physical shadow definitions.
/// Shadows remain excluded from the existing logical startup budget. This
/// deliberately scans retained state on every commit; no cached usage or new
/// durable counter can silently weaken the startup policy.
pub(crate) async fn commit_admitted(
    mut transaction: Transaction<'_, Sqlite>,
) -> Result<(), CognitiveStoreError> {
    admit_commit_state(&mut transaction).await?;
    transaction.commit().await.map_err(unavailable)
}

/// Admit uncommitted owner state inside the caller's existing write fence.
///
/// Callers with a synchronous final authority check run that check after this
/// admission and immediately before committing the same transaction. Any
/// admission or authority failure must discard the transaction and its writes.
pub(crate) async fn admit_commit_state(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    // Full-schema admission reads the migration ledger after its executable
    // definition has been authenticated. Retain that precondition here so an
    // owner-supplied generated column cannot execute before ledger bounds.
    if !super::schema::verify_existing_migrations_schema(connection).await? {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger is missing".to_string(),
        ));
    }
    // Compare all bounded catalog objects directly against the immutable
    // migration-built oracle. This includes the required objects, migration
    // ledger, extra objects and FTS shadows, without separately fetching and
    // hashing each required definition as startup's public verifier does.
    super::schema::verify_full_schema(connection).await?;
    // The admitted schema equals the complete compiled schema. Reuse only its
    // immutable query text and column metadata, built from a separate fresh
    // in-memory database. Every aggregate still reads actual owner state in
    // this same transaction; no data or usage totals survive between commits.
    let mut budget = Budget::default();
    for query in plan::queries().await? {
        // This plan contains only quoted compiled-schema identifiers and SQL
        // expressions; the changing row limit remains a bound parameter.
        let (count, bytes, largest): (i64, i64, i64) =
            sqlx::query_as(sqlx::AssertSqlSafe(std::sync::Arc::clone(query)))
                .bind(budget.remaining_rows + 1)
                .fetch_one(&mut *connection)
                .await
                .map_err(unavailable)?;
        budget.admit(count, bytes, largest)?;
    }
    Ok(())
}

/// Admit all registered logical owner tables with the recovery profile's
/// limits. `tables` comes from exact compiled-schema admission, including when
/// the admitted schema is an earlier compiled migration prefix.
pub(super) async fn verify(
    connection: &mut SqliteConnection,
    tables: &[&str],
) -> Result<(), CognitiveStoreError> {
    let mut tables = tables.to_vec();
    tables.push("sqlite_schema");
    verify_tables(connection, &tables, Budget::default()).await
}

/// Call inside the same already-admitted snapshot used by journal fetches.
pub(crate) async fn verify_journal_snapshot(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    verify_tables(connection, JOURNAL_TABLES, Budget::default()).await
}

async fn verify_tables(
    connection: &mut SqliteConnection,
    tables: &[&str],
    mut budget: Budget,
) -> Result<(), CognitiveStoreError> {
    for table in tables {
        if !matches!(*table, "sqlite_schema" | "_sqlx_migrations")
            && !REQUIRED_SCHEMA_OBJECTS.contains(&(*table, "table"))
        {
            return Err(CognitiveStoreError::Corrupt(
                "unregistered cognitive budget table".to_string(),
            ));
        }
        let columns: Vec<String> = if *table == "sqlite_schema" {
            ["type", "name", "tbl_name", "sql"]
                .into_iter()
                .map(str::to_string)
                .collect()
        } else {
            // Schema has already been authenticated. The bound also keeps the
            // metadata fetch small if this internal precondition is violated.
            let columns = sqlx::query(
                "SELECT substr(name, 1, 256) AS name FROM pragma_table_info(?) ORDER BY cid LIMIT 65",
            )
            .bind(table)
            .fetch_all(&mut *connection)
            .await
            .map_err(unavailable)?;
            if columns.is_empty() || columns.len() > 64 {
                return Err(CognitiveStoreError::Corrupt(
                    "cognitive budget table columns invalid".to_string(),
                ));
            }
            columns
                .iter()
                .map(|row| row.try_get("name"))
                .collect::<Result<_, _>>()
                .map_err(unavailable)?
        };
        let row_bytes = columns
            .iter()
            .map(|column| {
                let column = format!("\"{}\"", column.replace('"', "\"\""));
                // A conservative bound includes per-value type/length framing;
                // fixed 64 bytes for numbers covers their canonical encodings
                // without relying on SQLite CAST's floating-point formatting.
                // octet_length preserves encoded Text/Blob byte lengths while
                // reading column metadata rather than large overflow payloads.
                format!(
                    "CASE typeof({column}) WHEN 'null' THEN 16 WHEN 'integer' THEN 64 WHEN 'real' THEN 64 ELSE 24 + octet_length({column}) END"
                )
            })
            .collect::<Vec<_>>()
            .join(" + ");
        // Limit the input before aggregation. An overfull table is rejected
        // after at most the remaining row budget plus one, and no payload is
        // returned to Rust before aggregate row/byte admission succeeds.
        // Names are compiled-table allowlisted and authenticated schema columns
        // are quoted, so dynamic SQL never contains caller-supplied values.
        let mut query = sqlx::QueryBuilder::<sqlx::Sqlite>::new(
            "SELECT COUNT(*), COALESCE(SUM(row_size), 0), COALESCE(MAX(row_size), 0) FROM (SELECT ",
        );
        query
            .push(row_bytes)
            .push(" AS row_size FROM \"")
            .push(table)
            .push("\" LIMIT ")
            .push_bind(budget.remaining_rows + 1)
            .push(")");
        let (count, bytes, largest): (i64, i64, i64) = query
            .build_query_as()
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        budget.admit(count, bytes, largest)?;
    }
    Ok(())
}

#[path = "cognitive_store_budget_plan.rs"]
mod plan;

#[cfg(test)]
#[path = "cognitive_store_budget_tests.rs"]
mod tests;

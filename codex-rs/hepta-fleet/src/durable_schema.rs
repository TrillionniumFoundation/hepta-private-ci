use codex_hepta_contracts::AuthorityClock;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::DURABLE_FLEET_LINEAGE;
use crate::DURABLE_FLEET_SCHEMA_VERSION;
use crate::DurableFleetError;
use crate::durable_rows::to_i64;

pub(crate) async fn initialize_schema(
    pool: &SqlitePool,
    clock: &dyn AuthorityClock,
) -> Result<u64, DurableFleetError> {
    let mut tx = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(sqlx_error)?;
    let now_ms = clock
        .now_unix_ms()
        .map_err(|_| DurableFleetError::ClockUnavailable)?;
    let now_i64 = to_i64(now_ms)?;
    let checks: Vec<String> = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_all(&mut *tx)
        .await
        .map_err(sqlx_error)?;
    if checks != ["ok"] {
        return Err(DurableFleetError::Corrupt(format!(
            "SQLite quick_check returned {checks:?}"
        )));
    }
    // Installation, migration and clock publication share one writer transaction.
    for statement in include_str!("durable_schema.sql").split(';') {
        if !statement.trim().is_empty() {
            sqlx::query(statement)
                .execute(&mut *tx)
                .await
                .map_err(sqlx_error)?;
        }
    }
    let existing =
        sqlx::query("SELECT schema_version, lineage FROM fleet_schema WHERE singleton = 1")
            .fetch_optional(&mut *tx)
            .await
            .map_err(sqlx_error)?;
    let existing_version = existing
        .as_ref()
        .map(|row| row.try_get::<i64, _>("schema_version").map_err(sqlx_error))
        .transpose()?;
    if let Some(row) = existing {
        let version: i64 = row.try_get("schema_version").map_err(sqlx_error)?;
        let lineage: String = row.try_get("lineage").map_err(sqlx_error)?;
        if lineage != DURABLE_FLEET_LINEAGE
            || ![1, 2, DURABLE_FLEET_SCHEMA_VERSION].contains(&version)
        {
            return Err(DurableFleetError::Corrupt(format!(
                "unsupported supervisor fleet schema {version}/{lineage}"
            )));
        }
        if version == 1 {
            let active: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM fleet_grants")
                .fetch_one(&mut *tx)
                .await
                .map_err(sqlx_error)?;
            if active != 0 {
                return Err(DurableFleetError::Conflict(
                    "v1 migration requires quiescent owners and no active grants; prove stop before migration".into(),
                ));
            }
            // The product owner must establish quiescence before opening for
            // migration. Zero ledger rows alone are NOT native stop evidence.
        }
    } else {
        sqlx::query(
            "INSERT INTO fleet_schema(singleton, schema_version, lineage, created_at_ms)
             VALUES(1, ?, ?, ?)",
        )
        .bind(DURABLE_FLEET_SCHEMA_VERSION)
        .bind(DURABLE_FLEET_LINEAGE)
        .bind(now_i64)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query("INSERT INTO fleet_clock(singleton, last_now_ms) VALUES(1, ?)")
            .bind(now_i64)
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?;
    }
    for statement in include_str!("durable_execution_schema.sql").split(';') {
        if !statement.trim().is_empty() {
            sqlx::query(statement)
                .execute(&mut *tx)
                .await
                .map_err(sqlx_error)?;
        }
    }
    // Additive local-maintenance obligations preserve active v2 holds and all
    // original receipts. This is not the v1 execution-identity migration.
    let columns: Vec<String> =
        sqlx::query_scalar("SELECT name FROM pragma_table_info('fleet_execution_holds')")
            .fetch_all(&mut *tx)
            .await
            .map_err(sqlx_error)?;
    for (name, statement) in [
        (
            "local_renewal_pending_operation_id",
            "ALTER TABLE fleet_execution_holds ADD COLUMN local_renewal_pending_operation_id TEXT",
        ),
        (
            "local_renewal_confirmed_operation_id",
            "ALTER TABLE fleet_execution_holds ADD COLUMN local_renewal_confirmed_operation_id TEXT",
        ),
    ] {
        if !columns.iter().any(|column| column == name) {
            if existing_version == Some(DURABLE_FLEET_SCHEMA_VERSION) {
                return Err(DurableFleetError::Corrupt(format!(
                    "missing local renewal column {name}"
                )));
            }
            sqlx::query(statement)
                .execute(&mut *tx)
                .await
                .map_err(sqlx_error)?;
        }
    }
    sqlx::query("UPDATE fleet_schema SET schema_version = ? WHERE singleton = 1")
        .bind(DURABLE_FLEET_SCHEMA_VERSION)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
    let persisted: i64 =
        sqlx::query_scalar("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1")
            .fetch_one(&mut *tx)
            .await
            .map_err(sqlx_error)?;
    if now_i64 < persisted {
        return Err(DurableFleetError::ClockRollback);
    }
    sqlx::query("UPDATE fleet_clock SET last_now_ms = ? WHERE singleton = 1")
        .bind(now_i64)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
    tx.commit().await.map_err(sqlx_error)?;
    Ok(now_ms)
}

pub(crate) fn sqlx_error(error: sqlx::Error) -> DurableFleetError {
    DurableFleetError::Unavailable(error.to_string())
}

use sqlx::Row;
use sqlx::SqlitePool;

use crate::DURABLE_FLEET_LINEAGE;
use crate::DURABLE_FLEET_SCHEMA_VERSION;
use crate::DurableFleetError;

pub(crate) async fn initialize_schema(
    pool: &SqlitePool,
    now_ms: i64,
) -> Result<(), DurableFleetError> {
    let mut tx = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(sqlx_error)?;
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
    if let Some(row) = existing {
        let version: i64 = row.try_get("schema_version").map_err(sqlx_error)?;
        let lineage: String = row.try_get("lineage").map_err(sqlx_error)?;
        if lineage != DURABLE_FLEET_LINEAGE || ![1, DURABLE_FLEET_SCHEMA_VERSION].contains(&version)
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
        .bind(now_ms)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query("INSERT INTO fleet_clock(singleton, last_now_ms) VALUES(1, ?)")
            .bind(now_ms)
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
    if now_ms < persisted {
        return Err(DurableFleetError::ClockRollback);
    }
    sqlx::query("UPDATE fleet_clock SET last_now_ms = ? WHERE singleton = 1")
        .bind(now_ms)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
    tx.commit().await.map_err(sqlx_error)
}

pub(crate) fn sqlx_error(error: sqlx::Error) -> DurableFleetError {
    DurableFleetError::Unavailable(error.to_string())
}

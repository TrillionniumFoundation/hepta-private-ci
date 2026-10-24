//! Test-only measurements after the original bounded product request failed.
//!
//! These calls do not replace its result, extend its deadline, cache authority,
//! or admit transport. Fresh discovery always executes the unchanged original
//! path. Only SQLx/SQLite owns database descriptors and their close lifecycle.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaAgentLayout;
use futures::StreamExt;
use futures::stream;
use serde_json::Value;
use serde_json::json;
use sqlx::Row;
use sqlx::SqliteConnection;

use super::COGNITIVE_DB_FILENAME;
use super::FederatedMemoryReader;
use super::open_read_only_pool;
use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;

pub(crate) async fn failed_product_attempt(
    owner_layouts: &[HeptaAgentLayout],
    consumer_agent_id: &AgentId,
    now_unix_seconds: i64,
) {
    for width in [1, 2, 4, 17] {
        let started = Instant::now();
        let owners = stream::iter(owner_layouts.iter())
            .map(|layout| profile_owner(layout, consumer_agent_id, now_unix_seconds))
            .buffered(width)
            .collect::<Vec<_>>()
            .await;
        emit(json!({
            "phase": "fresh_vfs_full_discovery",
            "width": width,
            "owner_count": owner_layouts.len(),
            "elapsed_us_including_readonly_pool_close": started.elapsed().as_micros(),
            "owners": owners,
        }));
    }

    if let Some(layout) = owner_layouts.first() {
        // The first query in each new original readonly connection has not
        // previously run quick_check. The filesystem cache is not claimed cold.
        let same_connection = profile_connection(layout, 2).await;
        emit(json!({
            "phase": "same_original_connection",
            "owner": layout.agent_id().as_str(),
            "measurement": same_connection,
        }));
        let fresh_connection = profile_connection(layout, 1).await;
        emit(json!({
            "phase": "fresh_original_connection_control",
            "owner": layout.agent_id().as_str(),
            "measurement": fresh_connection,
        }));
    }
}

async fn profile_owner(
    layout: &HeptaAgentLayout,
    consumer_agent_id: &AgentId,
    now_unix_seconds: i64,
) -> Value {
    let started = Instant::now();
    let result = FederatedMemoryReader::discover(layout, consumer_agent_id, now_unix_seconds).await;
    let elapsed_us = started.elapsed().as_micros();
    match result {
        Ok(readers) => {
            let close_started = Instant::now();
            // All readers from this discover share its one fresh readonly
            // pool. Close that SQLx owner explicitly so asynchronous teardown
            // from one profiling width does not leak into the next width.
            // The fixture's original writer pool is separate and stays live.
            if let Some(reader) = readers.first() {
                reader.owner.pool.close().await;
            }
            json!({
                "owner": layout.agent_id().as_str(),
                "discover_elapsed_us": elapsed_us,
                "readers": readers.len(),
                "readonly_pool_close_us": close_started.elapsed().as_micros(),
                "error": Value::Null,
            })
        }
        Err(error) => json!({
            "owner": layout.agent_id().as_str(),
            "discover_elapsed_us": elapsed_us,
            "readers": Value::Null,
            "readonly_pool_close_us": Value::Null,
            "error": error.to_string(),
        }),
    }
}

async fn profile_connection(layout: &HeptaAgentLayout, query_count: usize) -> Value {
    let path = layout.cognitive_root().join(COGNITIVE_DB_FILENAME);
    let open_started = Instant::now();
    let pool = match open_read_only_pool(&path).await {
        Ok(pool) => pool,
        Err(error) => {
            return json!({
                "open_elapsed_us": open_started.elapsed().as_micros(),
                "quick_checks": [],
                "metadata": Value::Null,
                "error": error.to_string(),
            });
        }
    };
    let open_elapsed_us = open_started.elapsed().as_micros();
    let mut quick_checks = Vec::new();
    let result = async {
        // Retain this actual SQLx connection for both queries. No independent
        // raw file descriptor, path-stat identity claim, or SQLite handle API.
        let mut connection = pool.acquire().await.map_err(unavailable)?;
        for ordinal in 1..=query_count {
            let started = Instant::now();
            let result = sqlx::query_scalar::<_, String>("PRAGMA quick_check(1)")
                .fetch_all(&mut *connection)
                .await;
            let elapsed_us = started.elapsed().as_micros();
            quick_checks.push(match result {
                Ok(rows) => json!({
                    "ordinal": ordinal,
                    "elapsed_us": elapsed_us,
                    "exact_ok": rows == ["ok"],
                    "row_count": rows.len(),
                    "error": Value::Null,
                }),
                Err(error) => json!({
                    "ordinal": ordinal,
                    "elapsed_us": elapsed_us,
                    "exact_ok": false,
                    "row_count": Value::Null,
                    "error": error.to_string(),
                }),
            });
        }
        // Read metadata after the measured queries, so collecting schema size
        // cannot warm the first measured quick_check on this connection.
        connection_metadata(&mut connection).await
    }
    .await;
    let close_started = Instant::now();
    pool.close().await;
    let (metadata, error) = match result {
        Ok(metadata) => (metadata, Value::Null),
        Err(error) => (Value::Null, json!(error.to_string())),
    };
    json!({
        "open_elapsed_us": open_elapsed_us,
        "quick_checks": quick_checks,
        "metadata": metadata,
        "readonly_pool_close_us": close_started.elapsed().as_micros(),
        "error": error,
    })
}

async fn connection_metadata(
    connection: &mut SqliteConnection,
) -> Result<Value, CognitiveStoreError> {
    let page_count = scalar(connection, "PRAGMA page_count").await?;
    let page_size = scalar(connection, "PRAGMA page_size").await?;
    let freelist_count = scalar(connection, "PRAGMA freelist_count").await?;
    let schema_sql_bytes = scalar(
        connection,
        "SELECT COALESCE(SUM(length(CAST(sql AS BLOB))), 0) FROM sqlite_schema",
    )
    .await?;
    let schema_rows = sqlx::query(
        "SELECT type, COUNT(*) AS object_count FROM sqlite_schema GROUP BY type ORDER BY type",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    let mut schema_objects = Vec::new();
    for row in schema_rows {
        let kind: String = row.try_get("type").map_err(unavailable)?;
        let count: i64 = row.try_get("object_count").map_err(unavailable)?;
        schema_objects.push(json!({"type": kind, "count": count}));
    }
    let sqlite_version: String = sqlx::query_scalar("SELECT sqlite_version()")
        .fetch_one(&mut *connection)
        .await
        .map_err(unavailable)?;
    let compile_options = sqlx::query_scalar::<_, String>("PRAGMA compile_options")
        .fetch_all(&mut *connection)
        .await
        .map_err(unavailable)?;
    Ok(json!({
        "page_count": page_count,
        "page_size": page_size,
        "freelist_count": freelist_count,
        "schema_sql_bytes": schema_sql_bytes,
        "schema_objects": schema_objects,
        "sqlite_version": sqlite_version,
        "compile_options": compile_options,
    }))
}

async fn scalar(
    connection: &mut SqliteConnection,
    sql: &'static str,
) -> Result<i64, CognitiveStoreError> {
    sqlx::query_scalar(sql)
        .fetch_one(connection)
        .await
        .map_err(unavailable)
}

fn emit(value: Value) {
    eprintln!("HEPTA_FEDERATION_SQLITE_PROFILE_V1 {value}");
}

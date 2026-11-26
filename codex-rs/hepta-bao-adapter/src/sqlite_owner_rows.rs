//! Existing durable owner rows implementation.

use super::*;

pub(super) async fn checkpoint_tx(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<BaoOwnerCheckpointV1, SqliteBaoOwnerErrorV1> {
    let generation = meta_revision(tx).await?;
    let time_frontier_unix_ms = meta_time_frontier(tx).await?;
    let mut bytes = Digest32Builder::default();
    bytes.update(b"hepta.bao.sqlite-owner-checkpoint.v1\0");
    bytes.update(&generation.to_be_bytes());
    bytes.update(&time_frontier_unix_ms.to_be_bytes());
    append_query_rows_tx(
        tx,
        "SELECT operation_id, domain, kind, semantic_sha256, updated_at_unix_ms, terminal
         FROM bao_operation ORDER BY operation_id",
        &mut bytes,
    )
    .await?;
    append_query_rows_tx(
        tx,
        "SELECT operation_id, owner_revision, state, row_json
         FROM bao_consumption ORDER BY operation_id",
        &mut bytes,
    )
    .await?;
    append_query_rows_tx(
        tx,
        "SELECT lease_id, generation, state, row_json FROM bao_lease ORDER BY lease_id",
        &mut bytes,
    )
    .await?;
    append_query_rows_tx(
        tx,
        "SELECT operation_id, operation_kind, COALESCE(lease_id, ''),
                COALESCE(expected_generation, x''),
                COALESCE(resulting_generation, x''), state, row_json,
                COALESCE(terminal_result_sha256, x'')
         FROM bao_lease_operation ORDER BY operation_id",
        &mut bytes,
    )
    .await?;
    append_query_rows_tx(
        tx,
        "SELECT operation_id, reason, next_attempt_at_unix_ms, attempt_count,
                COALESCE(last_error_sha256, x'')
         FROM bao_reconciliation_queue ORDER BY operation_id",
        &mut bytes,
    )
    .await?;
    append_query_rows_tx(
        tx,
        "SELECT operation_id, owner_revision, row_json, archived_at_unix_ms
         FROM bao_terminal_archive ORDER BY operation_id",
        &mut bytes,
    )
    .await?;
    append_query_rows_tx(
        tx,
        "SELECT singleton, source_schema_version, source_revision,
                source_time_frontier_unix_ms, source_sha256, imported_at_unix_ms
         FROM bao_reference_import ORDER BY singleton",
        &mut bytes,
    )
    .await?;
    append_query_rows_tx(
        tx,
        "SELECT sequence, revision, operation_id, COALESCE(from_state, ''),
                to_state, evidence_sha256, observed_at_unix_ms
         FROM bao_transition ORDER BY sequence",
        &mut bytes,
    )
    .await?;
    Ok(BaoOwnerCheckpointV1 {
        generation,
        state_sha256: bytes.finish().into_array(),
    })
}

pub(super) async fn verify_schema(pool: &SqlitePool) -> Result<(), SqliteBaoOwnerErrorV1> {
    let reference = codex_state::SqliteConfig::from_sqlite_home(
        codex_utils_absolute_path::AbsolutePathBuf::try_from(std::env::temp_dir())
            .map_err(storage)?,
    )
    .open_durable_evidence_pool(Path::new(":memory:"))
    .await
    .map_err(storage)?;
    let result = async {
        let mut reference_connection = reference.acquire().await.map_err(storage)?;
        MIGRATOR
            .run(&mut *reference_connection)
            .await
            .map_err(storage)?;
        let query = "SELECT type, name, tbl_name, sql FROM sqlite_schema
                     WHERE name NOT GLOB 'sqlite_*' AND sql IS NOT NULL
                     ORDER BY type, name";
        let expected = sqlx::query_as::<_, (String, String, String, String)>(query)
            .fetch_all(&mut *reference_connection)
            .await
            .map_err(storage)?;
        let actual = sqlx::query_as::<_, (String, String, String, String)>(query)
            .fetch_all(pool)
            .await
            .map_err(storage)?;
        if actual != expected {
            return Err(SqliteBaoOwnerErrorV1::CorruptState(
                "live owner schema differs from compiled migrations",
            ));
        }
        Ok(())
    }
    .await;
    reference.close().await;
    result
}

pub(super) async fn advance_time(
    tx: &mut Transaction<'_, Sqlite>,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    if now_unix_ms == 0 {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    let frontier: Vec<u8> =
        sqlx::query_scalar("SELECT time_frontier_unix_ms FROM bao_owner_meta WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(storage)?;
    if now_unix_ms < fixed_u64_allow_zero(&frontier)? {
        return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
    }
    Ok(())
}

pub(super) async fn meta_revision(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> =
        sqlx::query_scalar("SELECT revision FROM bao_owner_meta WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(storage)?;
    fixed_u64(&value)
}

pub(super) async fn meta_time_frontier(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> =
        sqlx::query_scalar("SELECT time_frontier_unix_ms FROM bao_owner_meta WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(storage)?;
    fixed_u64_allow_zero(&value)
}

pub(super) async fn next_revision(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    meta_revision(tx)
        .await?
        .checked_add(1)
        .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)
}

pub(super) async fn write_meta(
    tx: &mut Transaction<'_, Sqlite>,
    revision: u64,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    sqlx::query(
        "UPDATE bao_owner_meta SET revision = ?, time_frontier_unix_ms = ?
         WHERE singleton = 1",
    )
    .bind(u64_bytes(revision).as_slice())
    .bind(u64_bytes(now_unix_ms).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

pub(super) async fn operation_identity_exists(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<bool, SqliteBaoOwnerErrorV1> {
    sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM bao_operation WHERE operation_id = ?)")
        .bind(operation_id)
        .fetch_one(&mut **tx)
        .await
        .map_err(storage)
}

pub(super) async fn insert_consumption(
    tx: &mut Transaction<'_, Sqlite>,
    operation: &BaoConsumptionOperationV1,
    revision: u64,
    created_at_unix_ms: u64,
    updated_at_unix_ms: u64,
    row_json: &[u8],
) -> Result<(), SqliteBaoOwnerErrorV1> {
    sqlx::query(
        "INSERT INTO bao_consumption
         (operation_id, semantic_sha256, effect_sha256, request_sha256,
          consumer_id, consumer_configuration_sha256, amount, state,
          reservation_id, terminal_kind, terminal_code, terminal_evidence_sha256,
          terminal_observed_cost, row_json, owner_revision,
          created_at_unix_ms, updated_at_unix_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&operation.operation_id)
    .bind(operation.semantic_sha256.as_slice())
    .bind(operation.effect_sha256.as_slice())
    .bind(operation.request_sha256.as_slice())
    .bind(&operation.consumer_id)
    .bind(operation.consumer_configuration_sha256.as_slice())
    .bind(u64_bytes(operation.amount).as_slice())
    .bind(state_text(operation.state))
    .bind(operation.reservation_id.as_deref())
    .bind(operation.terminal_kind.as_deref())
    .bind(operation.terminal_code.as_deref())
    .bind(
        operation
            .terminal_evidence_sha256
            .map(|value| value.to_vec()),
    )
    .bind(
        operation
            .terminal_observed_cost
            .map(|value| u64_bytes(value).to_vec()),
    )
    .bind(row_json)
    .bind(u64_bytes(revision).as_slice())
    .bind(u64_bytes(created_at_unix_ms).as_slice())
    .bind(u64_bytes(updated_at_unix_ms).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

pub(super) async fn load_consumption_current_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    let row = sqlx::query(
        "SELECT *
         FROM bao_consumption WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

pub(super) async fn load_consumption_current_pool(
    pool: &SqlitePool,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    let row = sqlx::query(
        "SELECT *
         FROM bao_consumption WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(pool)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

pub(super) async fn load_consumption_any_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    if let Some(current) = load_consumption_current_tx(tx, operation_id).await? {
        return Ok(Some(current));
    }
    let row = sqlx::query(
        "SELECT *
         FROM bao_terminal_archive WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

pub(super) async fn load_consumption_any_pool(
    pool: &SqlitePool,
    operation_id: &str,
) -> Result<Option<SqliteConsumptionRecordV1>, SqliteBaoOwnerErrorV1> {
    if let Some(current) = load_consumption_current_pool(pool, operation_id).await? {
        return Ok(Some(current));
    }
    let row = sqlx::query(
        "SELECT *
         FROM bao_terminal_archive WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(pool)
    .await
    .map_err(storage)?;
    row.map(consumption_record).transpose()
}

pub(super) fn consumption_record(
    row: sqlx::sqlite::SqliteRow,
) -> Result<SqliteConsumptionRecordV1, SqliteBaoOwnerErrorV1> {
    let bytes: Vec<u8> = row.try_get("row_json").map_err(storage)?;
    let operation: BaoConsumptionOperationV1 = decode_row(&bytes)?;
    validate_consumption_stored(&operation)?;
    if operation.operation_id != row.try_get::<String, _>("operation_id").map_err(storage)?
        || operation.semantic_sha256.as_slice()
            != row
                .try_get::<Vec<u8>, _>("semantic_sha256")
                .map_err(storage)?
        || operation.terminal_kind
            != row
                .try_get::<Option<String>, _>("terminal_kind")
                .map_err(storage)?
        || operation.terminal_code
            != row
                .try_get::<Option<String>, _>("terminal_code")
                .map_err(storage)?
        || operation.terminal_evidence_sha256.map(Vec::from)
            != row
                .try_get::<Option<Vec<u8>>, _>("terminal_evidence_sha256")
                .map_err(storage)?
        || operation
            .terminal_observed_cost
            .map(|value| u64_bytes(value).to_vec())
            != row
                .try_get::<Option<Vec<u8>>, _>("terminal_observed_cost")
                .map_err(storage)?
    {
        return Err(SqliteBaoOwnerErrorV1::CorruptState(
            "consumption JSON differs from immutable projection",
        ));
    }
    match row.try_get::<String, _>("state") {
        Ok(state) => {
            if state_text(operation.state) != state
                || operation.effect_sha256.as_slice()
                    != row
                        .try_get::<Vec<u8>, _>("effect_sha256")
                        .map_err(storage)?
                || operation.request_sha256.as_slice()
                    != row
                        .try_get::<Vec<u8>, _>("request_sha256")
                        .map_err(storage)?
                || operation.consumer_id
                    != row.try_get::<String, _>("consumer_id").map_err(storage)?
                || operation.consumer_configuration_sha256.as_slice()
                    != row
                        .try_get::<Vec<u8>, _>("consumer_configuration_sha256")
                        .map_err(storage)?
                || operation.amount
                    != fixed_u64(&row.try_get::<Vec<u8>, _>("amount").map_err(storage)?)?
                || operation.reservation_id
                    != row
                        .try_get::<Option<String>, _>("reservation_id")
                        .map_err(storage)?
            {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "consumption JSON differs from indexed projection",
                ));
            }
        }
        Err(sqlx::Error::ColumnNotFound(_)) if operation.state.is_terminal() => {}
        Err(sqlx::Error::ColumnNotFound(_)) => {
            return Err(SqliteBaoOwnerErrorV1::CorruptState(
                "archive contains a nonterminal operation",
            ));
        }
        Err(error) => return Err(storage(error)),
    }
    let revision = fixed_u64(
        &row.try_get::<Vec<u8>, _>("owner_revision")
            .map_err(storage)?,
    )?;
    if operation.created_revision == 0
        || operation.updated_revision != revision
        || operation.created_revision > operation.updated_revision
    {
        return Err(SqliteBaoOwnerErrorV1::CorruptState(
            "consumption revision lineage is invalid",
        ));
    }
    Ok(SqliteConsumptionRecordV1 {
        operation,
        revision,
        created_at_unix_ms: fixed_u64(
            &row.try_get::<Vec<u8>, _>("created_at_unix_ms")
                .map_err(storage)?,
        )?,
        updated_at_unix_ms: fixed_u64(
            &row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                .map_err(storage)?,
        )?,
    })
}

//! Existing durable owner archive implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn archive_terminal_before(
        &self,
        cutoff_unix_ms: u64,
        limit: u32,
        archived_at_unix_ms: u64,
    ) -> Result<u32, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        if cutoff_unix_ms == 0 || archived_at_unix_ms < cutoff_unix_ms || limit == 0 || limit > 4096
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.begin().await?;
        advance_time(&mut tx, archived_at_unix_ms).await?;
        let archived: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_terminal_archive")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if archived >= MAX_ARCHIVED_TERMINALS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let operation_ids: Vec<String> = sqlx::query_scalar(
            "SELECT operation_id
             FROM bao_consumption
             WHERE state IN ('succeeded', 'failed') AND updated_at_unix_ms < ?
             ORDER BY updated_at_unix_ms, operation_id LIMIT ?",
        )
        .bind(u64_bytes(cutoff_unix_ms).as_slice())
        .bind(i64::from(limit))
        .fetch_all(&mut *tx)
        .await
        .map_err(storage)?;
        let mut count = 0_u32;
        let mut latest_revision = meta_revision(&mut tx).await?;
        for operation_id in operation_ids {
            if archived + i64::from(count) >= MAX_ARCHIVED_TERMINALS {
                return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
            }
            let row = sqlx::query(
                "SELECT row_json, owner_revision, created_at_unix_ms, updated_at_unix_ms
                 FROM bao_consumption WHERE operation_id = ?",
            )
            .bind(&operation_id)
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
            let row_json: Vec<u8> = row.try_get("row_json").map_err(storage)?;
            let decoded: BaoConsumptionOperationV1 = decode_row(&row_json)?;
            validate_consumption_stored(&decoded)?;
            if decoded.operation_id != operation_id || !decoded.state.is_terminal() {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "invalid terminal archive source",
                ));
            }
            let kind = decoded
                .terminal_kind
                .as_deref()
                .ok_or(SqliteBaoOwnerErrorV1::CorruptState("terminal kind missing"))?;
            let evidence =
                decoded
                    .terminal_evidence_sha256
                    .ok_or(SqliteBaoOwnerErrorV1::CorruptState(
                        "terminal evidence missing",
                    ))?;
            let cost = decoded
                .terminal_observed_cost
                .ok_or(SqliteBaoOwnerErrorV1::CorruptState("terminal cost missing"))?;
            sqlx::query(
                "INSERT INTO bao_terminal_archive
                 (operation_id, semantic_sha256, terminal_kind, terminal_code,
                  terminal_evidence_sha256, terminal_observed_cost, row_json,
                  owner_revision, created_at_unix_ms, updated_at_unix_ms,
                  archived_at_unix_ms)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(&operation_id)
            .bind(decoded.semantic_sha256.as_slice())
            .bind(kind)
            .bind(decoded.terminal_code.as_deref())
            .bind(evidence.as_slice())
            .bind(u64_bytes(cost).as_slice())
            .bind(&row_json)
            .bind(
                row.try_get::<Vec<u8>, _>("owner_revision")
                    .map_err(storage)?,
            )
            .bind(
                row.try_get::<Vec<u8>, _>("created_at_unix_ms")
                    .map_err(storage)?,
            )
            .bind(
                row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                    .map_err(storage)?,
            )
            .bind(u64_bytes(archived_at_unix_ms).as_slice())
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
            sqlx::query("DELETE FROM bao_reconciliation_queue WHERE operation_id = ?")
                .bind(&operation_id)
                .execute(&mut *tx)
                .await
                .map_err(map_write_error)?;
            sqlx::query("DELETE FROM bao_consumption WHERE operation_id = ?")
                .bind(&operation_id)
                .execute(&mut *tx)
                .await
                .map_err(map_write_error)?;
            latest_revision = latest_revision
                .checked_add(1)
                .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
            insert_transition(
                &mut tx,
                latest_revision,
                &operation_id,
                Some(state_text(decoded.state)),
                "archived",
                evidence,
                archived_at_unix_ms,
            )
            .await?;
            count += 1;
        }
        if count != 0 {
            write_meta(&mut tx, latest_revision, archived_at_unix_ms).await?;
        }
        self.commit(tx).await?;
        Ok(count)
    }
}

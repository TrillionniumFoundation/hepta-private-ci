//! Existing durable owner import implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn import_reference_snapshot(
        &self,
        snapshot: &LeaseRegistryMigrationSnapshotV1,
        imported_at_unix_ms: u64,
    ) -> Result<SqliteBaoOwnerImportReceiptV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        if snapshot.schema_version != 4
            || snapshot.revision == 0
            || imported_at_unix_ms == 0
            || imported_at_unix_ms < snapshot.time_frontier_unix_ms
            || snapshot.operations.len()
                > usize::try_from(MAX_ACTIVE_OPERATIONS).unwrap_or(usize::MAX)
            || snapshot.consumptions.len()
                > usize::try_from(MAX_ACTIVE_OPERATIONS).unwrap_or(usize::MAX)
            || snapshot.leases.len() > usize::try_from(MAX_ACTIVE_OPERATIONS).unwrap_or(usize::MAX)
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let source_bytes =
            serde_json::to_vec(snapshot).map_err(|_| SqliteBaoOwnerErrorV1::InvalidInput)?;
        let source_sha256 = Digest32::of_bytes(&source_bytes).into_array();
        let mut identities = BTreeSet::new();
        for operation in &snapshot.operations {
            validate_lease_operation(operation)?;
            if !identities.insert(operation.operation_id.as_str()) {
                return Err(SqliteBaoOwnerErrorV1::OperationConflict);
            }
        }
        for operation in &snapshot.consumptions {
            validate_consumption_input(operation)?;
            if !identities.insert(operation.operation_id.as_str()) {
                return Err(SqliteBaoOwnerErrorV1::OperationConflict);
            }
        }
        let mut lease_ids = BTreeSet::new();
        for lease in &snapshot.leases {
            validate_lease(lease)?;
            if !lease_ids.insert(lease.lease_id.as_str()) {
                return Err(SqliteBaoOwnerErrorV1::OperationConflict);
            }
        }

        let mut tx = self.begin().await?;
        if let Some(existing) = sqlx::query(
            "SELECT source_revision, source_sha256, imported_at_unix_ms
             FROM bao_reference_import WHERE singleton = 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?
        {
            let existing_revision = fixed_u64(
                &existing
                    .try_get::<Vec<u8>, _>("source_revision")
                    .map_err(storage)?,
            )?;
            let existing_sha: [u8; 32] = existing
                .try_get::<Vec<u8>, _>("source_sha256")
                .map_err(storage)?
                .try_into()
                .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid import source digest"))?;
            let existing_imported_at = fixed_u64(
                &existing
                    .try_get::<Vec<u8>, _>("imported_at_unix_ms")
                    .map_err(storage)?,
            )?;
            tx.rollback().await.map_err(storage)?;
            if existing_revision != snapshot.revision || existing_sha != source_sha256 {
                return Err(SqliteBaoOwnerErrorV1::MigrationConflict);
            }
            return Ok(SqliteBaoOwnerImportReceiptV1 {
                source_revision: existing_revision,
                source_sha256: existing_sha,
                imported_at_unix_ms: existing_imported_at,
                checkpoint: self.checkpoint().await?,
            });
        }
        let operation_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_operation")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        let lease_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_lease")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if operation_count != 0 || lease_count != 0 {
            return Err(SqliteBaoOwnerErrorV1::MigrationConflict);
        }
        advance_time(&mut tx, imported_at_unix_ms).await?;
        let mut revision = meta_revision(&mut tx).await?;

        for lease in &snapshot.leases {
            let row_json = encode_row(lease)?;
            sqlx::query(
                "INSERT INTO bao_lease
                 (lease_id, generation, state, row_json, updated_at_unix_ms)
                 VALUES (?, ?, ?, ?, ?)",
            )
            .bind(&lease.lease_id)
            .bind(u64_bytes(lease.generation).as_slice())
            .bind(lease_state_text(lease.state))
            .bind(&row_json)
            .bind(u64_bytes(imported_at_unix_ms).as_slice())
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
        }

        for operation in &snapshot.operations {
            revision = revision
                .checked_add(1)
                .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
            let row_json = encode_row(operation)?;
            let terminal = matches!(
                operation.state,
                LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
            );
            let terminal_result = terminal.then(|| Digest32::of_bytes(&row_json).into_array());
            sqlx::query(
                "INSERT INTO bao_operation
                 (operation_id, domain, kind, semantic_sha256, created_at_unix_ms,
                  updated_at_unix_ms, terminal)
                 VALUES (?, 'lease', ?, ?, ?, ?, ?)",
            )
            .bind(&operation.operation_id)
            .bind(lease_operation_kind_text(operation.kind))
            .bind(operation.semantic_sha256.as_slice())
            .bind(u64_bytes(imported_at_unix_ms).as_slice())
            .bind(u64_bytes(imported_at_unix_ms).as_slice())
            .bind(if terminal { 1_i64 } else { 0_i64 })
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
            sqlx::query(
                "INSERT INTO bao_lease_operation
                 (operation_id, operation_kind, lease_id, expected_generation,
                  resulting_generation, state, row_json, terminal_result_sha256)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(&operation.operation_id)
            .bind(lease_operation_kind_text(operation.kind))
            .bind(operation.lease_id.as_deref())
            .bind(
                operation
                    .expected_generation
                    .map(|value| u64_bytes(value).to_vec()),
            )
            .bind(
                operation
                    .resulting_generation
                    .map(|value| u64_bytes(value).to_vec()),
            )
            .bind(lease_operation_state_text(operation.state))
            .bind(&row_json)
            .bind(terminal_result.map(|value| value.to_vec()))
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
            insert_transition(
                &mut tx,
                revision,
                &operation.operation_id,
                None,
                lease_operation_state_text(operation.state),
                Digest32::of_bytes(&row_json).into_array(),
                imported_at_unix_ms,
            )
            .await?;
        }

        for operation in &snapshot.consumptions {
            revision = revision
                .checked_add(1)
                .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?;
            let mut operation = operation.clone();
            operation.created_revision = revision;
            operation.updated_revision = revision;
            validate_consumption_input(&operation)?;
            let row_json = encode_row(&operation)?;
            sqlx::query(
                "INSERT INTO bao_operation
                 (operation_id, domain, kind, semantic_sha256, created_at_unix_ms,
                  updated_at_unix_ms, terminal)
                 VALUES (?, 'consumption', 'read', ?, ?, ?, ?)",
            )
            .bind(&operation.operation_id)
            .bind(operation.semantic_sha256.as_slice())
            .bind(u64_bytes(imported_at_unix_ms).as_slice())
            .bind(u64_bytes(imported_at_unix_ms).as_slice())
            .bind(if operation.state.is_terminal() {
                1_i64
            } else {
                0_i64
            })
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
            insert_consumption(
                &mut tx,
                &operation,
                revision,
                imported_at_unix_ms,
                imported_at_unix_ms,
                &row_json,
            )
            .await?;
            insert_transition(
                &mut tx,
                revision,
                &operation.operation_id,
                None,
                state_text(operation.state),
                Digest32::of_bytes(&row_json).into_array(),
                imported_at_unix_ms,
            )
            .await?;
            if !operation.state.is_terminal() {
                upsert_reconciliation(
                    &mut tx,
                    &operation.operation_id,
                    operation.state,
                    imported_at_unix_ms,
                )
                .await?;
            }
        }

        sqlx::query(
            "INSERT INTO bao_reference_import
             (singleton, source_schema_version, source_revision,
              source_time_frontier_unix_ms, source_sha256, imported_at_unix_ms)
             VALUES (1, 4, ?, ?, ?, ?)",
        )
        .bind(u64_bytes(snapshot.revision).as_slice())
        .bind(u64_bytes(snapshot.time_frontier_unix_ms).as_slice())
        .bind(source_sha256.as_slice())
        .bind(u64_bytes(imported_at_unix_ms).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        write_meta(&mut tx, revision, imported_at_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteBaoOwnerImportReceiptV1 {
            source_revision: snapshot.revision,
            source_sha256,
            imported_at_unix_ms,
            checkpoint: self.checkpoint().await?,
        })
    }
}

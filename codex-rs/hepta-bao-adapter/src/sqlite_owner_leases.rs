//! Existing durable owner leases implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn claim_lease_operation(
        &self,
        operation: LeaseOperationV1,
        now_unix_ms: u64,
    ) -> Result<SqliteLeaseOperationRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_lease_operation(&operation)?;
        if operation.state != LeaseOperationStateV1::Prepared
            || operation.legacy_binding_incomplete
            || now_unix_ms == 0
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.begin().await?;
        advance_time(&mut tx, now_unix_ms).await?;
        if let Some(existing) = load_lease_operation_tx(&mut tx, &operation.operation_id).await? {
            if same_lease_operation_claim_identity(&existing.operation, &operation) {
                tx.rollback().await.map_err(storage)?;
                return Ok(existing);
            }
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if operation_identity_exists(&mut tx, &operation.operation_id).await? {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_lease_operation")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if count >= MAX_ACTIVE_OPERATIONS {
            return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
        }
        let revision = next_revision(&mut tx).await?;
        let row_json = encode_row(&operation)?;
        sqlx::query(
            "INSERT INTO bao_operation
             (operation_id, domain, kind, semantic_sha256, created_at_unix_ms,
              updated_at_unix_ms, terminal)
             VALUES (?, 'lease', ?, ?, ?, ?, 0)",
        )
        .bind(&operation.operation_id)
        .bind(format!("{:?}", operation.kind).to_ascii_lowercase())
        .bind(operation.semantic_sha256.as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(u64_bytes(now_unix_ms).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        sqlx::query(
            "INSERT INTO bao_lease_operation
             (operation_id, operation_kind, lease_id, expected_generation,
              resulting_generation, state, row_json, terminal_result_sha256)
             VALUES (?, ?, ?, ?, NULL, 'prepared', ?, NULL)",
        )
        .bind(&operation.operation_id)
        .bind(lease_operation_kind_text(operation.kind))
        .bind(operation.lease_id.as_deref())
        .bind(
            operation
                .expected_generation
                .map(|value| u64_bytes(value).to_vec()),
        )
        .bind(&row_json)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            &operation.operation_id,
            None,
            "prepared",
            Digest32::of_bytes(&row_json).into_array(),
            now_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision,
            created_at_unix_ms: now_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }

    pub async fn mark_lease_operation_unknown(
        &self,
        operation_id: &str,
        expected_revision: u64,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteLeaseOperationRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_identifier(operation_id)?;
        if expected_revision == 0 || evidence_sha256 == [0; 32] || now_unix_ms == 0 {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.begin().await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let current = load_lease_operation_tx(&mut tx, operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.operation.state == LeaseOperationStateV1::Unknown {
            let existing_evidence = latest_transition_evidence_tx(&mut tx, operation_id).await?;
            tx.rollback().await.map_err(storage)?;
            return if existing_evidence == evidence_sha256 {
                Ok(current)
            } else {
                Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
            };
        }
        if current.revision != expected_revision {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        if current.operation.legacy_binding_incomplete {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        if current.operation.state != LeaseOperationStateV1::Prepared {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        let mut operation = current.operation.clone();
        operation.state = LeaseOperationStateV1::Unknown;
        let row_json = encode_row(&operation)?;
        let revision = next_revision(&mut tx).await?;
        let changed = sqlx::query(
            "UPDATE bao_lease_operation SET state = 'unknown', row_json = ?
             WHERE operation_id = ? AND state = 'prepared' AND terminal_result_sha256 IS NULL",
        )
        .bind(&row_json)
        .bind(operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query("UPDATE bao_operation SET updated_at_unix_ms = ? WHERE operation_id = ?")
            .bind(u64_bytes(now_unix_ms).as_slice())
            .bind(operation_id)
            .execute(&mut *tx)
            .await
            .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            operation_id,
            Some("prepared"),
            "unknown",
            evidence_sha256,
            now_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }

    pub async fn apply_lease_operation(
        &self,
        operation: LeaseOperationV1,
        lease: Option<SecretLeaseMetadataV1>,
        expected_revision: u64,
        evidence_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<SqliteLeaseOperationRecordV1, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        validate_lease_operation(&operation)?;
        if !matches!(
            operation.state,
            LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
        ) || operation.legacy_binding_incomplete
            || expected_revision == 0
            || evidence_sha256 == [0; 32]
            || now_unix_ms == 0
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        if operation.result_lease != lease {
            return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
        }
        if operation
            .observed_at_unix_ms
            .is_some_and(|observed| observed > now_unix_ms)
        {
            return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
        }
        if operation.state == LeaseOperationStateV1::Applied && lease.is_none() {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        let mut tx = self.begin().await?;
        advance_time(&mut tx, now_unix_ms).await?;
        let current = load_lease_operation_tx(&mut tx, &operation.operation_id)
            .await?
            .ok_or(SqliteBaoOwnerErrorV1::OperationNotFound)?;
        if current.operation == operation {
            let existing_evidence =
                latest_transition_evidence_tx(&mut tx, &operation.operation_id).await?;
            tx.rollback().await.map_err(storage)?;
            return if existing_evidence == evidence_sha256 {
                Ok(current)
            } else {
                Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
            };
        }
        if current.revision != expected_revision {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        let lease_identity_matches = match current.operation.kind {
            crate::LeaseOperationKindV1::Issue => {
                current.operation.lease_id.is_none()
                    && match operation.state {
                        LeaseOperationStateV1::Applied => operation.lease_id.is_some(),
                        LeaseOperationStateV1::Denied => operation.lease_id.is_none(),
                        LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown => false,
                    }
            }
            crate::LeaseOperationKindV1::Renew | crate::LeaseOperationKindV1::Revoke => {
                current.operation.lease_id == operation.lease_id
            }
        };
        if current.operation.semantic_sha256 != operation.semantic_sha256
            || current.operation.kind != operation.kind
            || current.operation.expected_generation != operation.expected_generation
            || !lease_identity_matches
        {
            return Err(SqliteBaoOwnerErrorV1::OperationConflict);
        }
        if matches!(
            current.operation.state,
            LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
        ) {
            return Err(SqliteBaoOwnerErrorV1::InvalidTransition);
        }
        if let Some(lease) = lease.as_ref() {
            validate_lease(lease)?;
            apply_lease_projection(&mut tx, &operation, lease, now_unix_ms).await?;
        }
        let revision = next_revision(&mut tx).await?;
        let row_json = encode_row(&operation)?;
        let terminal_result = Digest32::of_bytes(&row_json).into_array();
        let changed = sqlx::query(
            "UPDATE bao_lease_operation
             SET state = ?, resulting_generation = ?, row_json = ?,
                 terminal_result_sha256 = ?
             WHERE operation_id = ? AND terminal_result_sha256 IS NULL",
        )
        .bind(lease_operation_state_text(operation.state))
        .bind(
            operation
                .resulting_generation
                .map(|value| u64_bytes(value).to_vec()),
        )
        .bind(&row_json)
        .bind(terminal_result.as_slice())
        .bind(&operation.operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?
        .rows_affected();
        if changed != 1 {
            return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
        }
        sqlx::query(
            "UPDATE bao_operation SET terminal = 1, updated_at_unix_ms = ?
             WHERE operation_id = ?",
        )
        .bind(u64_bytes(now_unix_ms).as_slice())
        .bind(&operation.operation_id)
        .execute(&mut *tx)
        .await
        .map_err(map_write_error)?;
        insert_transition(
            &mut tx,
            revision,
            &operation.operation_id,
            Some(lease_operation_state_text(current.operation.state)),
            lease_operation_state_text(operation.state),
            evidence_sha256,
            now_unix_ms,
        )
        .await?;
        write_meta(&mut tx, revision, now_unix_ms).await?;
        self.commit(tx).await?;
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision,
            created_at_unix_ms: current.created_at_unix_ms,
            updated_at_unix_ms: now_unix_ms,
        })
    }

    pub async fn lease(
        &self,
        lease_id: &str,
    ) -> Result<Option<SecretLeaseMetadataV1>, SqliteBaoOwnerErrorV1> {
        validate_identifier(lease_id)?;
        let row = sqlx::query(
            "SELECT lease_id, generation, state, row_json FROM bao_lease WHERE lease_id = ?",
        )
        .bind(lease_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        row.map(|row| {
            let lease: SecretLeaseMetadataV1 =
                decode_row(&row.try_get::<Vec<u8>, _>("row_json").map_err(storage)?)?;
            validate_lease(&lease).map_err(|_| {
                SqliteBaoOwnerErrorV1::CorruptState("invalid persisted lease projection")
            })?;
            if lease.lease_id != row.try_get::<String, _>("lease_id").map_err(storage)?
                || lease.generation
                    != fixed_u64(&row.try_get::<Vec<u8>, _>("generation").map_err(storage)?)?
                || lease_state_text(lease.state)
                    != row.try_get::<String, _>("state").map_err(storage)?
            {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "lease JSON differs from immutable projection",
                ));
            }
            Ok(lease)
        })
        .transpose()
    }
}

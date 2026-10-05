//! Existing durable owner rows implementation.

use super::*;

pub(super) async fn load_lease_operation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<SqliteLeaseOperationRecordV1>, SqliteBaoOwnerErrorV1> {
    let row = sqlx::query(
        "SELECT l.operation_id, l.operation_kind, l.lease_id,
                l.expected_generation, l.resulting_generation, l.state,
                l.row_json, l.terminal_result_sha256, o.domain, o.kind,
                o.semantic_sha256, o.terminal, o.created_at_unix_ms,
                o.updated_at_unix_ms, t.to_state,
                t.revision AS owner_revision
         FROM bao_lease_operation l
         JOIN bao_operation o ON o.operation_id = l.operation_id
         JOIN bao_transition t ON t.operation_id = l.operation_id
         WHERE l.operation_id = ? ORDER BY t.sequence DESC LIMIT 1",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    row.map(|row| {
        let bytes: Vec<u8> = row.try_get("row_json").map_err(storage)?;
        let operation = decode_row::<LeaseOperationV1>(&bytes)?;
        validate_lease_operation(&operation).map_err(|_| {
            SqliteBaoOwnerErrorV1::CorruptState("invalid persisted lease operation")
        })?;
        let projected_lease_id: Option<String> = row.try_get("lease_id").map_err(storage)?;
        // For an issued result, the immutable SQL input has no lease ID. The
        // result ID is bound by the provider observation and terminal digest.
        let issue_result_id = operation.kind == crate::LeaseOperationKindV1::Issue
            && operation.state == LeaseOperationStateV1::Applied
            && projected_lease_id.is_none();
        let terminal = matches!(
            operation.state,
            LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
        );
        let result_digest = terminal.then(|| Digest32::of_bytes(&bytes).into_array().to_vec());
        if operation.operation_id != operation_id
            || operation.operation_id
                != row.try_get::<String, _>("operation_id").map_err(storage)?
            || row.try_get::<String, _>("domain").map_err(storage)? != "lease"
            || lease_operation_kind_text(operation.kind)
                != row.try_get::<String, _>("kind").map_err(storage)?
            || lease_operation_kind_text(operation.kind)
                != row
                    .try_get::<String, _>("operation_kind")
                    .map_err(storage)?
            || operation.semantic_sha256.as_slice()
                != row
                    .try_get::<Vec<u8>, _>("semantic_sha256")
                    .map_err(storage)?
            || (!issue_result_id && operation.lease_id != projected_lease_id)
            || operation
                .expected_generation
                .map(|value| u64_bytes(value).to_vec())
                != row
                    .try_get::<Option<Vec<u8>>, _>("expected_generation")
                    .map_err(storage)?
            || operation
                .resulting_generation
                .map(|value| u64_bytes(value).to_vec())
                != row
                    .try_get::<Option<Vec<u8>>, _>("resulting_generation")
                    .map_err(storage)?
            || lease_operation_state_text(operation.state)
                != row.try_get::<String, _>("state").map_err(storage)?
            || lease_operation_state_text(operation.state)
                != row.try_get::<String, _>("to_state").map_err(storage)?
            || i64::from(terminal) != row.try_get::<i64, _>("terminal").map_err(storage)?
            || result_digest
                != row
                    .try_get::<Option<Vec<u8>>, _>("terminal_result_sha256")
                    .map_err(storage)?
        {
            return Err(SqliteBaoOwnerErrorV1::CorruptState(
                "lease operation JSON differs from immutable projection",
            ));
        }
        Ok(SqliteLeaseOperationRecordV1 {
            operation,
            revision: fixed_u64(
                &row.try_get::<Vec<u8>, _>("owner_revision")
                    .map_err(storage)?,
            )?,
            created_at_unix_ms: fixed_u64(
                &row.try_get::<Vec<u8>, _>("created_at_unix_ms")
                    .map_err(storage)?,
            )?,
            updated_at_unix_ms: fixed_u64(
                &row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                    .map_err(storage)?,
            )?,
        })
    })
    .transpose()
}

pub(super) async fn apply_lease_projection(
    tx: &mut Transaction<'_, Sqlite>,
    current_operation: &LeaseOperationV1,
    lease: &SecretLeaseMetadataV1,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    let existing = sqlx::query(
        "SELECT generation, state, row_json, updated_at_unix_ms FROM bao_lease WHERE lease_id = ?",
    )
    .bind(&lease.lease_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    let row_json = encode_row(lease)?;
    match existing {
        None => {
            if current_operation.expected_generation.is_some() || lease.generation != 1 {
                return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
            }
            sqlx::query(
                "INSERT INTO bao_lease (lease_id, generation, state, row_json, updated_at_unix_ms)
                 VALUES (?, ?, ?, ?, ?)",
            )
            .bind(&lease.lease_id)
            .bind(u64_bytes(lease.generation).as_slice())
            .bind(lease_state_text(lease.state))
            .bind(&row_json)
            .bind(u64_bytes(now_unix_ms).as_slice())
            .execute(&mut **tx)
            .await
            .map_err(map_write_error)?;
        }
        Some(row) => {
            let generation = fixed_u64(&row.try_get::<Vec<u8>, _>("generation").map_err(storage)?)?;
            let state: String = row.try_get("state").map_err(storage)?;
            let previous: SecretLeaseMetadataV1 =
                decode_row(&row.try_get::<Vec<u8>, _>("row_json").map_err(storage)?)?;
            validate_lease(&previous)?;
            let previous_updated_at = fixed_u64(
                &row.try_get::<Vec<u8>, _>("updated_at_unix_ms")
                    .map_err(storage)?,
            )?;
            if current_operation.expected_generation != Some(generation)
                || lease.generation
                    != generation
                        .checked_add(1)
                        .ok_or(SqliteBaoOwnerErrorV1::CapacityExceeded)?
                || previous.generation != generation
                || lease_state_text(previous.state) != state
                || lease.secret_reference_id != previous.secret_reference_id
                || lease.consumer_id != previous.consumer_id
                || lease.scope_sha256 != previous.scope_sha256
                || lease.issued_at_unix_ms != previous.issued_at_unix_ms
                || current_operation
                    .observed_at_unix_ms
                    .is_none_or(|observed| observed < previous_updated_at)
                || (matches!(state.as_str(), "revoked" | "expired")
                    && lease_state_text(lease.state) != state)
            {
                return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
            }
            match current_operation.kind {
                crate::LeaseOperationKindV1::Issue => {
                    return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
                }
                crate::LeaseOperationKindV1::Renew => {
                    let pending_revoke: bool = sqlx::query_scalar(
                        "SELECT EXISTS(SELECT 1 FROM bao_lease_operation
                         WHERE lease_id = ? AND operation_kind = 'revoke'
                           AND state IN ('prepared', 'unknown'))",
                    )
                    .bind(&lease.lease_id)
                    .fetch_one(&mut **tx)
                    .await
                    .map_err(storage)?;
                    if !previous.renewable
                        || !matches!(
                            previous.state,
                            SecretLeaseStateV1::Active | SecretLeaseStateV1::RenewUnknown
                        )
                        || pending_revoke
                    {
                        return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
                    }
                }
                crate::LeaseOperationKindV1::Revoke => {
                    if matches!(
                        previous.state,
                        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                    ) || lease.expires_at_unix_ms != previous.expires_at_unix_ms
                    {
                        return Err(SqliteBaoOwnerErrorV1::ObservationMismatch);
                    }
                }
            }
            let changed = sqlx::query(
                "UPDATE bao_lease SET generation = ?, state = ?, row_json = ?,
                 updated_at_unix_ms = ? WHERE lease_id = ? AND generation = ?",
            )
            .bind(u64_bytes(lease.generation).as_slice())
            .bind(lease_state_text(lease.state))
            .bind(&row_json)
            .bind(u64_bytes(now_unix_ms).as_slice())
            .bind(&lease.lease_id)
            .bind(u64_bytes(generation).as_slice())
            .execute(&mut **tx)
            .await
            .map_err(map_write_error)?
            .rows_affected();
            if changed != 1 {
                return Err(SqliteBaoOwnerErrorV1::RevisionConflict);
            }
        }
    }
    Ok(())
}

pub(super) async fn establishing_transition_evidence_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    state: &str,
) -> Result<[u8; 32], SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> = sqlx::query_scalar(
        "SELECT evidence_sha256 FROM bao_transition
         WHERE operation_id = ? AND to_state = ?
           AND (from_state IS NULL OR from_state != to_state)
         ORDER BY sequence DESC LIMIT 1",
    )
    .bind(operation_id)
    .bind(state)
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    value
        .try_into()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid transition evidence"))
}

pub(super) async fn latest_transition_evidence_tx(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<[u8; 32], SqliteBaoOwnerErrorV1> {
    let value: Vec<u8> = sqlx::query_scalar(
        "SELECT evidence_sha256 FROM bao_transition
         WHERE operation_id = ? ORDER BY sequence DESC LIMIT 1",
    )
    .bind(operation_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    value
        .try_into()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid transition evidence"))
}

pub(super) async fn insert_transition(
    tx: &mut Transaction<'_, Sqlite>,
    revision: u64,
    operation_id: &str,
    from_state: Option<&str>,
    to_state: &str,
    evidence_sha256: [u8; 32],
    observed_at_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    sqlx::query(
        "INSERT INTO bao_transition
         (revision, operation_id, from_state, to_state, evidence_sha256, observed_at_unix_ms)
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(u64_bytes(revision).as_slice())
    .bind(operation_id)
    .bind(from_state)
    .bind(to_state)
    .bind(evidence_sha256.as_slice())
    .bind(u64_bytes(observed_at_unix_ms).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

pub(super) async fn upsert_reconciliation(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    state: BaoConsumptionStateV1,
    now_unix_ms: u64,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bao_reconciliation_queue")
        .fetch_one(&mut **tx)
        .await
        .map_err(storage)?;
    let exists: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM bao_reconciliation_queue WHERE operation_id = ?)",
    )
    .bind(operation_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(storage)?;
    if !exists && count >= MAX_RECONCILIATION_ROWS {
        return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
    }
    sqlx::query(
        "INSERT INTO bao_reconciliation_queue
         (operation_id, reason, next_attempt_at_unix_ms, attempt_count, last_error_sha256)
         VALUES (?, ?, ?, ?, NULL)
         ON CONFLICT(operation_id) DO UPDATE SET
         reason = excluded.reason,
         next_attempt_at_unix_ms = excluded.next_attempt_at_unix_ms,
         attempt_count = excluded.attempt_count,
         last_error_sha256 = NULL",
    )
    .bind(operation_id)
    .bind(state_text(state))
    .bind(u64_bytes(now_unix_ms).as_slice())
    .bind(u64_bytes(0).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(map_write_error)?;
    Ok(())
}

pub(super) async fn reconciliation_attempts(
    tx: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value: Option<Vec<u8>> = sqlx::query_scalar(
        "SELECT attempt_count FROM bao_reconciliation_queue WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    value
        .map(|value| fixed_u64_allow_zero(&value))
        .transpose()
        .map(|value| value.unwrap_or(0))
}

pub(super) async fn count_tx(
    tx: &mut Transaction<'_, Sqlite>,
    table: &str,
) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let query = match table {
        "bao_operation" => "SELECT COUNT(*) FROM bao_operation",
        "bao_consumption" => "SELECT COUNT(*) FROM bao_consumption",
        "bao_terminal_archive" => "SELECT COUNT(*) FROM bao_terminal_archive",
        "bao_transition" => "SELECT COUNT(*) FROM bao_transition",
        "bao_reconciliation_queue" => "SELECT COUNT(*) FROM bao_reconciliation_queue",
        _ => return Err(SqliteBaoOwnerErrorV1::InvalidInput),
    };
    let value: i64 = sqlx::query_scalar(query)
        .fetch_one(&mut **tx)
        .await
        .map_err(storage)?;
    u64::try_from(value).map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("negative count"))
}

pub(super) async fn append_query_rows_tx(
    tx: &mut Transaction<'_, Sqlite>,
    query: &'static str,
    bytes: &mut Digest32Builder,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    let mut rows = sqlx::Executor::fetch(&mut **tx, query);
    while let Some(row) = std::future::poll_fn(|context| rows.as_mut().poll_next(context)).await {
        let row = row.map_err(storage)?;
        bytes.update(&u64::try_from(row.len()).unwrap_or(u64::MAX).to_be_bytes());
        for index in 0..row.len() {
            if let Ok(value) = row.try_get::<Vec<u8>, _>(index) {
                append_value(bytes, &value);
            } else if let Ok(value) = row.try_get::<String, _>(index) {
                append_value(bytes, value.as_bytes());
            } else if let Ok(value) = row.try_get::<i64, _>(index) {
                append_value(bytes, &value.to_be_bytes());
            } else {
                return Err(SqliteBaoOwnerErrorV1::CorruptState(
                    "unsupported checkpoint column",
                ));
            }
        }
    }
    Ok(())
}

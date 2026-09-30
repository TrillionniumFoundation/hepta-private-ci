pub(crate) async fn verify_frontier_repair_storage(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    verify_repair_schema(pool).await?;
    let capacity = sqlx::query(
        "SELECT COUNT(*) AS row_count,
                COALESCE(SUM(
                    length(CAST(current_frontier_json AS BLOB))
                    + length(CAST(target_frontier_json AS BLOB))
                    + length(CAST(authorization_json AS BLOB))
                    + length(CAST(authority_json AS BLOB))
                ), 0) AS canonical_bytes
         FROM evidence_frontier_repairs",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let row_count: i64 = capacity.try_get("row_count").map_err(classify_sqlx_error)?;
    let canonical_bytes: i64 = capacity
        .try_get("canonical_bytes")
        .map_err(classify_sqlx_error)?;
    if row_count < 0 || canonical_bytes < 0 {
        return Err(corrupt("frontier repair capacity accounting is negative"));
    }
    if row_count > EVIDENCE_FRONTIER_REPAIR_MAX_ROWS
        || canonical_bytes > EVIDENCE_FRONTIER_REPAIR_MAX_CANONICAL_BYTES
    {
        return Err(EvidenceError::Unavailable(
            "frontier repair startup verification exceeds its row or byte budget".to_string(),
        ));
    }

    let repair_rows = sqlx::query(
        "SELECT * FROM evidence_frontier_repairs ORDER BY created_at_ms, repair_id",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in &repair_rows {
        let operation = decode_repair_row(row)?;
        verify_repair_events(pool, &operation).await?;
    }
    Ok(())
}

async fn verify_repair_schema(pool: &SqlitePool) -> Result<(), EvidenceError> {
    const OBJECTS: &[(&str, &str, &str, &[&str])] = &[
        (
            "evidence_frontier_repairs",
            "table",
            "evidence_frontier_repairs",
            &[
                "create table",
                "unique(authority_key_id, authority_key_epoch, nonce_hex)",
                "'prepared', 'dispatching', 'indeterminate', 'acknowledged', 'conflicted'",
                "authorization_json text not null",
                "authority_json text not null",
            ],
        ),
        (
            "evidence_frontier_repairs_one_open_per_store",
            "index",
            "evidence_frontier_repairs",
            &[
                "create unique index",
                "where state in ('prepared', 'dispatching', 'indeterminate')",
            ],
        ),
        (
            "evidence_frontier_repairs_transition",
            "trigger",
            "evidence_frontier_repairs",
            &[
                "before update",
                "invalid evidence frontier repair transition",
            ],
        ),
        (
            "evidence_frontier_repairs_no_delete",
            "trigger",
            "evidence_frontier_repairs",
            &[
                "before delete",
                "evidence frontier repairs cannot be deleted",
            ],
        ),
        (
            "evidence_frontier_repair_events",
            "table",
            "evidence_frontier_repair_events",
            &[
                "create table",
                "unique(repair_id, event_index)",
                "event_sha256 text not null unique",
            ],
        ),
        (
            "evidence_frontier_repair_events_no_update",
            "trigger",
            "evidence_frontier_repair_events",
            &[
                "before update",
                "evidence frontier repair events are immutable",
            ],
        ),
        (
            "evidence_frontier_repair_events_no_delete",
            "trigger",
            "evidence_frontier_repair_events",
            &[
                "before delete",
                "evidence frontier repair events cannot be deleted",
            ],
        ),
    ];
    for (name, kind, table, fragments) in OBJECTS {
        let row = sqlx::query("SELECT type, tbl_name, sql FROM sqlite_schema WHERE name = ?")
            .bind(name)
            .fetch_optional(pool)
            .await
            .map_err(classify_sqlx_error)?
            .ok_or_else(|| {
                corrupt(&format!(
                    "required frontier repair schema object {name} is missing"
                ))
            })?;
        let actual_kind: String = row.try_get("type").map_err(classify_sqlx_error)?;
        let actual_table: String = row.try_get("tbl_name").map_err(classify_sqlx_error)?;
        let sql: String = row
            .try_get::<Option<String>, _>("sql")
            .map_err(classify_sqlx_error)?
            .ok_or(corrupt("frontier repair schema object has no SQL"))?;
        let normalized = sql
            .to_ascii_lowercase()
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
        if actual_kind != *kind
            || actual_table != *table
            || fragments.iter().any(|fragment| !normalized.contains(fragment))
        {
            return Err(corrupt(&format!(
                "frontier repair schema object {name} has an invalid definition"
            )));
        }
    }
    Ok(())
}

async fn verify_repair_events(
    pool: &SqlitePool,
    operation: &EvidenceFrontierRepairOperationV1,
) -> Result<(), EvidenceError> {
    let rows = sqlx::query(
        "SELECT event_index, event_kind, event_json, event_sha256,
                previous_event_sha256, observed_at_ms
         FROM evidence_frontier_repair_events
         WHERE repair_id = ? ORDER BY event_index",
    )
    .bind(&operation.repair_id)
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.is_empty() || rows.len() > 4 {
        return Err(corrupt(
            "frontier repair event history has an invalid bounded length",
        ));
    }
    let mut previous: Option<Sha256Digest> = None;
    let mut previous_time = 0;
    let mut kinds = Vec::with_capacity(rows.len());
    for (offset, row) in rows.iter().enumerate() {
        let event_json: String = row.try_get("event_json").map_err(classify_sqlx_error)?;
        let event: EvidenceFrontierRepairEventV1 =
            serde_json::from_str(&event_json).map_err(|error| corrupt(&error.to_string()))?;
        let bytes = canonical_json(&event)?;
        let canonical = String::from_utf8(bytes.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let digest = Sha256Digest::for_bytes(&bytes);
        let projected_digest = parse_digest(row, "event_sha256")?;
        let projected_previous = optional_digest(row, "previous_event_sha256")?;
        let projected_kind = EvidenceFrontierRepairStateV1::parse(
            &row.try_get::<String, _>("event_kind")
                .map_err(classify_sqlx_error)?,
        )?;
        let projected_index = positive_u64(
            row.try_get("event_index").map_err(classify_sqlx_error)?,
            "frontier repair event index",
        )?;
        let projected_time = positive_u64(
            row.try_get("observed_at_ms").map_err(classify_sqlx_error)?,
            "frontier repair event timestamp",
        )?;
        if event_json != canonical
            || digest != projected_digest
            || event.previous_event_sha256 != previous
            || projected_previous != previous
            || event.event_index != (offset as u64) + 1
            || projected_index != event.event_index
            || event.event_kind != projected_kind
            || event.observed_at_unix_ms != projected_time
            || event.repair_id != operation.repair_id
            || event.store_id != operation.store_id
            || event.nonce_hex != operation.nonce_hex
            || event.current_frontier_sha256
                != operation.authorization.current_frontier_sha256
            || event.target_frontier_sha256
                != operation.authorization.target_frontier_sha256
            || event.observed_at_unix_ms < previous_time
            || event.observed_at_unix_ms > operation.updated_at_unix_ms
        {
            return Err(corrupt(
                "frontier repair event chain does not match its canonical projections",
            ));
        }
        let event_projection_matches = match event.event_kind {
            EvidenceFrontierRepairStateV1::Prepared => {
                event.event_index == 1
                    && event.observed_at_unix_ms == operation.created_at_unix_ms
                    && event.dispatch_token.is_none()
                    && event.backend_identity_sha256.is_none()
                    && event.durable_audit_sequence.is_none()
                    && event.conflict_generation.is_none()
                    && event.conflict_frontier_sha256.is_none()
            }
            EvidenceFrontierRepairStateV1::Dispatching
            | EvidenceFrontierRepairStateV1::Indeterminate => {
                event.dispatch_token == operation.dispatch_token
                    && event.backend_identity_sha256 == operation.backend_identity_sha256
                    && event.durable_audit_sequence.is_none()
                    && event.conflict_generation.is_none()
                    && event.conflict_frontier_sha256.is_none()
            }
            EvidenceFrontierRepairStateV1::Acknowledged => {
                event.dispatch_token == operation.dispatch_token
                    && event.backend_identity_sha256 == operation.backend_identity_sha256
                    && event.durable_audit_sequence == operation.durable_audit_sequence
                    && event.conflict_generation.is_none()
                    && event.conflict_frontier_sha256.is_none()
            }
            EvidenceFrontierRepairStateV1::Conflicted => {
                event.dispatch_token == operation.dispatch_token
                    && event.backend_identity_sha256 == operation.backend_identity_sha256
                    && event.durable_audit_sequence.is_none()
                    && event.conflict_generation == operation.conflict_generation
                    && event.conflict_frontier_sha256 == operation.conflict_frontier_sha256
            }
        };
        if !event_projection_matches {
            return Err(corrupt(
                "frontier repair event does not match the exact operation fence or terminal observation",
            ));
        }
        previous_time = event.observed_at_unix_ms;
        previous = Some(digest);
        kinds.push(event.event_kind);
    }
    let valid = match operation.state {
        EvidenceFrontierRepairStateV1::Prepared => {
            kinds == [EvidenceFrontierRepairStateV1::Prepared]
        }
        EvidenceFrontierRepairStateV1::Dispatching => {
            kinds
                == [
                    EvidenceFrontierRepairStateV1::Prepared,
                    EvidenceFrontierRepairStateV1::Dispatching,
                ]
        }
        EvidenceFrontierRepairStateV1::Indeterminate => {
            kinds
                == [
                    EvidenceFrontierRepairStateV1::Prepared,
                    EvidenceFrontierRepairStateV1::Dispatching,
                    EvidenceFrontierRepairStateV1::Indeterminate,
                ]
        }
        EvidenceFrontierRepairStateV1::Acknowledged => {
            kinds
                == [
                    EvidenceFrontierRepairStateV1::Prepared,
                    EvidenceFrontierRepairStateV1::Dispatching,
                    EvidenceFrontierRepairStateV1::Acknowledged,
                ]
                || kinds
                    == [
                        EvidenceFrontierRepairStateV1::Prepared,
                        EvidenceFrontierRepairStateV1::Dispatching,
                        EvidenceFrontierRepairStateV1::Indeterminate,
                        EvidenceFrontierRepairStateV1::Acknowledged,
                    ]
        }
        EvidenceFrontierRepairStateV1::Conflicted => {
            kinds
                == [
                    EvidenceFrontierRepairStateV1::Prepared,
                    EvidenceFrontierRepairStateV1::Dispatching,
                    EvidenceFrontierRepairStateV1::Conflicted,
                ]
                || kinds
                    == [
                        EvidenceFrontierRepairStateV1::Prepared,
                        EvidenceFrontierRepairStateV1::Dispatching,
                        EvidenceFrontierRepairStateV1::Indeterminate,
                        EvidenceFrontierRepairStateV1::Conflicted,
                    ]
        }
    };
    if !valid {
        return Err(corrupt(
            "frontier repair terminal state is inconsistent with its event history",
        ));
    }
    let last_row = rows
        .last()
        .ok_or(corrupt("frontier repair event history is unexpectedly empty"))?;
    let last: EvidenceFrontierRepairEventV1 = serde_json::from_str(
        &last_row
            .try_get::<String, _>("event_json")
            .map_err(classify_sqlx_error)?,
    )
    .map_err(|error| corrupt(&error.to_string()))?;
    if last.dispatch_token != operation.dispatch_token
        || last.backend_identity_sha256 != operation.backend_identity_sha256
        || last.durable_audit_sequence != operation.durable_audit_sequence
        || last.conflict_generation != operation.conflict_generation
        || last.conflict_frontier_sha256 != operation.conflict_frontier_sha256
        || last.event_kind != operation.state
    {
        return Err(corrupt(
            "frontier repair latest event differs from the operation projection",
        ));
    }
    Ok(())
}

fn reason_code_str(reason: FrontierRepairReasonV1) -> &'static str {
    match reason {
        FrontierRepairReasonV1::BackendMigration => "backend_migration",
        FrontierRepairReasonV1::StoreRecovery => "store_recovery",
        FrontierRepairReasonV1::TrustRootRotation => "trust_root_rotation",
        FrontierRepairReasonV1::SchemaMigration => "schema_migration",
        FrontierRepairReasonV1::OperatorDisasterRecovery => "operator_disaster_recovery",
    }
}

fn parse_reason_code(value: &str) -> Result<FrontierRepairReasonV1, EvidenceError> {
    match value {
        "backend_migration" => Ok(FrontierRepairReasonV1::BackendMigration),
        "store_recovery" => Ok(FrontierRepairReasonV1::StoreRecovery),
        "trust_root_rotation" => Ok(FrontierRepairReasonV1::TrustRootRotation),
        "schema_migration" => Ok(FrontierRepairReasonV1::SchemaMigration),
        "operator_disaster_recovery" => Ok(FrontierRepairReasonV1::OperatorDisasterRecovery),
        _ => Err(corrupt("unknown frontier repair reason code")),
    }
}

fn parse_digest(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Sha256Digest, EvidenceError> {
    Sha256Digest::parse(
        row.try_get::<String, _>(column)
            .map_err(classify_sqlx_error)?,
    )
    .map_err(EvidenceError::Corrupt)
}

fn optional_digest(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Option<Sha256Digest>, EvidenceError> {
    row.try_get::<Option<String>, _>(column)
        .map_err(classify_sqlx_error)?
        .map(Sha256Digest::parse)
        .transpose()
        .map_err(EvidenceError::Corrupt)
}

fn optional_positive_u64(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Option<u64>, EvidenceError> {
    row.try_get::<Option<i64>, _>(column)
        .map_err(classify_sqlx_error)?
        .map(|value| positive_u64(value, column))
        .transpose()
}

fn positive_u64(value: i64, label: &str) -> Result<u64, EvidenceError> {
    if value <= 0 {
        return Err(corrupt(&format!("{label} must be positive")));
    }
    u64::try_from(value).map_err(|_| corrupt(&format!("{label} is outside the numeric domain")))
}

fn to_i64(value: u64, label: &str) -> Result<i64, EvidenceError> {
    i64::try_from(value).map_err(|_| invalid(&format!("{label} exceeds SQLite INTEGER")))
}

fn invalid(message: &str) -> EvidenceError {
    EvidenceError::InvalidRecord(message.to_string())
}

fn corrupt(message: &str) -> EvidenceError {
    EvidenceError::Corrupt(message.to_string())
}

#[cfg(test)]
#[path = "frontier_repair_tests.rs"]
mod tests;

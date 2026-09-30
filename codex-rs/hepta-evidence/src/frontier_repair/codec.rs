struct CanonicalRepair {
    current_json: String,
    current_json_sha256: Sha256Digest,
    target_json: String,
    target_json_sha256: Sha256Digest,
    authorization_json: String,
    authorization_sha256: Sha256Digest,
    authority_json: String,
    authority_sha256: Sha256Digest,
}

impl CanonicalRepair {
    fn new(
        authorization: &FrontierRepairAuthorizationV1,
        authority: &FrontierRepairAuthorityV1,
        current: &EvidenceRecoveryFrontierV2,
        target: &EvidenceRecoveryFrontierV2,
    ) -> Result<Self, EvidenceError> {
        let current_bytes = canonical_json(current)?;
        let target_bytes = canonical_json(target)?;
        let authorization_bytes = canonical_json(authorization)?;
        let authority_bytes = canonical_json(authority)?;
        Ok(Self {
            current_json_sha256: Sha256Digest::for_bytes(&current_bytes),
            current_json: String::from_utf8(current_bytes)
                .map_err(|error| EvidenceError::Serialization(error.to_string()))?,
            target_json_sha256: Sha256Digest::for_bytes(&target_bytes),
            target_json: String::from_utf8(target_bytes)
                .map_err(|error| EvidenceError::Serialization(error.to_string()))?,
            authorization_sha256: Sha256Digest::for_bytes(&authorization_bytes),
            authorization_json: String::from_utf8(authorization_bytes)
                .map_err(|error| EvidenceError::Serialization(error.to_string()))?,
            authority_sha256: Sha256Digest::for_bytes(&authority_bytes),
            authority_json: String::from_utf8(authority_bytes)
                .map_err(|error| EvidenceError::Serialization(error.to_string()))?,
        })
    }
}

fn repair_id(authorization_sha256: &Sha256Digest) -> String {
    format!("repair:{}", authorization_sha256.as_str())
}

fn operation_matches_canonical(
    operation: &EvidenceFrontierRepairOperationV1,
    canonical: &CanonicalRepair,
) -> Result<bool, EvidenceError> {
    let existing = CanonicalRepair::new(
        &operation.authorization,
        &operation.authority,
        &operation.current_frontier,
        &operation.target_frontier,
    )?;
    Ok(repair_id(&canonical.authorization_sha256) == operation.repair_id
        && existing.current_json == canonical.current_json
        && existing.target_json == canonical.target_json
        && existing.authorization_json == canonical.authorization_json
        && existing.authority_json == canonical.authority_json
        && existing.current_json_sha256 == canonical.current_json_sha256
        && existing.target_json_sha256 == canonical.target_json_sha256
        && existing.authorization_sha256 == canonical.authorization_sha256
        && existing.authority_sha256 == canonical.authority_sha256)
}

async fn enrolled_store_id(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<String, EvidenceError> {
    sqlx::query_scalar("SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1")
        .fetch_optional(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(EvidenceError::Unavailable(
            "frontier repair requires an enrolled recovery store identity".to_string(),
        ))
}

async fn load_repair_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    repair_id: &str,
) -> Result<EvidenceFrontierRepairOperationV1, EvidenceError> {
    let row = sqlx::query("SELECT * FROM evidence_frontier_repairs WHERE repair_id = ?")
        .bind(repair_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or(invalid("frontier repair operation does not exist"))?;
    decode_repair_row(&row)
}

fn decode_repair_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<EvidenceFrontierRepairOperationV1, EvidenceError> {
    let current_json: String = row.try_get("current_frontier_json").map_err(classify_sqlx_error)?;
    let target_json: String = row.try_get("target_frontier_json").map_err(classify_sqlx_error)?;
    let authorization_json: String = row.try_get("authorization_json").map_err(classify_sqlx_error)?;
    let authority_json: String = row.try_get("authority_json").map_err(classify_sqlx_error)?;
    let current_frontier: EvidenceRecoveryFrontierV2 =
        serde_json::from_str(&current_json).map_err(|error| corrupt(&error.to_string()))?;
    let target_frontier: EvidenceRecoveryFrontierV2 =
        serde_json::from_str(&target_json).map_err(|error| corrupt(&error.to_string()))?;
    let authorization: FrontierRepairAuthorizationV1 =
        serde_json::from_str(&authorization_json).map_err(|error| corrupt(&error.to_string()))?;
    let authority: FrontierRepairAuthorityV1 =
        serde_json::from_str(&authority_json).map_err(|error| corrupt(&error.to_string()))?;
    let operation = EvidenceFrontierRepairOperationV1 {
        repair_id: row.try_get("repair_id").map_err(classify_sqlx_error)?,
        store_id: row.try_get("store_id").map_err(classify_sqlx_error)?,
        state: EvidenceFrontierRepairStateV1::parse(
            &row.try_get::<String, _>("state").map_err(classify_sqlx_error)?,
        )?,
        nonce_hex: row.try_get("nonce_hex").map_err(classify_sqlx_error)?,
        operator_principal_id: row
            .try_get("operator_principal_id")
            .map_err(classify_sqlx_error)?,
        reason_code: parse_reason_code(
            &row.try_get::<String, _>("reason_code")
                .map_err(classify_sqlx_error)?,
        )?,
        authority_key_id: row.try_get("authority_key_id").map_err(classify_sqlx_error)?,
        authority_key_epoch: positive_u64(
            row.try_get("authority_key_epoch").map_err(classify_sqlx_error)?,
            "frontier repair authority key epoch",
        )?,
        trust_root_generation: positive_u64(
            row.try_get("trust_root_generation").map_err(classify_sqlx_error)?,
            "frontier repair trust-root generation",
        )?,
        current_frontier,
        target_frontier,
        authorization,
        authority,
        dispatch_token: row.try_get("dispatch_token").map_err(classify_sqlx_error)?,
        backend_identity_sha256: optional_digest(row, "backend_identity_sha256")?,
        durable_audit_sequence: optional_positive_u64(row, "durable_audit_sequence")?,
        conflict_generation: optional_positive_u64(row, "conflict_generation")?,
        conflict_frontier_sha256: optional_digest(row, "conflict_frontier_sha256")?,
        created_at_unix_ms: positive_u64(
            row.try_get("created_at_ms").map_err(classify_sqlx_error)?,
            "frontier repair creation timestamp",
        )?,
        updated_at_unix_ms: positive_u64(
            row.try_get("updated_at_ms").map_err(classify_sqlx_error)?,
            "frontier repair update timestamp",
        )?,
    };
    verify_decoded_projection(row, &operation, &current_json, &target_json, &authorization_json, &authority_json)?;
    Ok(operation)
}

fn verify_decoded_projection(
    row: &sqlx::sqlite::SqliteRow,
    operation: &EvidenceFrontierRepairOperationV1,
    current_json: &str,
    target_json: &str,
    authorization_json: &str,
    authority_json: &str,
) -> Result<(), EvidenceError> {
    let canonical = CanonicalRepair::new(
        &operation.authorization,
        &operation.authority,
        &operation.current_frontier,
        &operation.target_frontier,
    )?;
    let projected_operator: String = row
        .try_get("operator_principal_id")
        .map_err(classify_sqlx_error)?;
    let projected_reason = parse_reason_code(
        &row.try_get::<String, _>("reason_code")
            .map_err(classify_sqlx_error)?,
    )?;
    let projected_authority_key_id: String = row
        .try_get("authority_key_id")
        .map_err(classify_sqlx_error)?;
    let projected_authority_key_epoch = positive_u64(
        row.try_get("authority_key_epoch")
            .map_err(classify_sqlx_error)?,
        "frontier repair authority key epoch",
    )?;
    let projected_trust_root_generation = positive_u64(
        row.try_get("trust_root_generation")
            .map_err(classify_sqlx_error)?,
        "frontier repair trust-root generation",
    )?;
    let projected_current_generation = positive_u64(
        row.try_get("current_generation")
            .map_err(classify_sqlx_error)?,
        "frontier repair current generation",
    )?;
    let projected_target_generation = positive_u64(
        row.try_get("target_generation")
            .map_err(classify_sqlx_error)?,
        "frontier repair target generation",
    )?;
    if canonical.current_json != current_json
        || canonical.target_json != target_json
        || canonical.authorization_json != authorization_json
        || canonical.authority_json != authority_json
        || parse_digest(row, "current_frontier_json_sha256")? != canonical.current_json_sha256
        || parse_digest(row, "target_frontier_json_sha256")? != canonical.target_json_sha256
        || parse_digest(row, "authorization_sha256")? != canonical.authorization_sha256
        || parse_digest(row, "authority_sha256")? != canonical.authority_sha256
        || parse_digest(row, "current_frontier_sha256")?
            != evidence_recovery_frontier_v2_sha256(&operation.current_frontier)
                .map_err(EvidenceError::Corrupt)?
        || parse_digest(row, "target_frontier_sha256")?
            != evidence_recovery_frontier_v2_sha256(&operation.target_frontier)
                .map_err(EvidenceError::Corrupt)?
        || projected_operator != operation.operator_principal_id
        || projected_reason != operation.reason_code
        || projected_authority_key_id != operation.authority_key_id
        || projected_authority_key_epoch != operation.authority_key_epoch
        || projected_trust_root_generation != operation.trust_root_generation
        || projected_current_generation != operation.current_frontier.frontier_generation
        || projected_target_generation != operation.target_frontier.frontier_generation
        || operation.authorization.store_id != operation.store_id
        || operation.current_frontier.store_id != operation.store_id
        || operation.target_frontier.store_id != operation.store_id
        || operation.authorization.nonce_hex != operation.nonce_hex
        || operation.authorization.operator_principal_id != operation.operator_principal_id
        || operation.authorization.reason_code != operation.reason_code
        || operation.authorization.authority_key_id != operation.authority_key_id
        || operation.authorization.authority_key_epoch != operation.authority_key_epoch
        || operation.authorization.trust_root_generation != operation.trust_root_generation
        || operation.authorization.current_generation
            != operation.current_frontier.frontier_generation
        || operation.authorization.target_generation
            != operation.target_frontier.frontier_generation
        || repair_id(&canonical.authorization_sha256) != operation.repair_id
    {
        return Err(corrupt(
            "frontier repair row does not reconstruct its exact canonical authorization",
        ));
    }
    verify_frontier_repair_authorization(
        &operation.authorization,
        &operation.authority,
        &operation.current_frontier,
        &operation.target_frontier,
        operation.created_at_unix_ms,
    )
    .map_err(EvidenceError::Corrupt)?;
    if classify_frontier_merge(&operation.current_frontier, &operation.target_frontier)
        != FrontierMergeDecision::RepairRequired
    {
        return Err(corrupt(
            "frontier repair row contains a transition that ordinary CAS could accept",
        ));
    }
    Ok(())
}

#[expect(
    clippy::too_many_arguments,
    reason = "the durable event binds every terminal observation field explicitly"
)]
async fn append_transition_event(
    transaction: &mut Transaction<'_, Sqlite>,
    current: &EvidenceFrontierRepairOperationV1,
    event_kind: EvidenceFrontierRepairStateV1,
    dispatch_token: Option<String>,
    backend_identity_sha256: Option<Sha256Digest>,
    durable_audit_sequence: Option<u64>,
    conflict_generation: Option<u64>,
    conflict_frontier_sha256: Option<Sha256Digest>,
    observed_at_unix_ms: u64,
) -> Result<(), EvidenceError> {
    let row = sqlx::query(
        "SELECT event_index, event_sha256 FROM evidence_frontier_repair_events
         WHERE repair_id = ? ORDER BY event_index DESC LIMIT 1",
    )
    .bind(&current.repair_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let previous_index = positive_u64(
        row.try_get("event_index").map_err(classify_sqlx_error)?,
        "frontier repair event index",
    )?;
    let previous_digest = Sha256Digest::parse(
        row.try_get::<String, _>("event_sha256")
            .map_err(classify_sqlx_error)?,
    )
    .map_err(EvidenceError::Corrupt)?;
    let event = EvidenceFrontierRepairEventV1 {
        schema_version: EVIDENCE_FRONTIER_REPAIR_EVENT_SCHEMA_VERSION,
        repair_id: current.repair_id.clone(),
        event_index: previous_index
            .checked_add(1)
            .ok_or(invalid("frontier repair event index exhausted"))?,
        event_kind,
        store_id: current.store_id.clone(),
        nonce_hex: current.nonce_hex.clone(),
        current_frontier_sha256: current.authorization.current_frontier_sha256.clone(),
        target_frontier_sha256: current.authorization.target_frontier_sha256.clone(),
        dispatch_token,
        backend_identity_sha256,
        durable_audit_sequence,
        conflict_generation,
        conflict_frontier_sha256,
        observed_at_unix_ms,
        previous_event_sha256: Some(previous_digest),
    };
    append_event(transaction, &event).await
}

async fn append_event(
    transaction: &mut Transaction<'_, Sqlite>,
    event: &EvidenceFrontierRepairEventV1,
) -> Result<(), EvidenceError> {
    let bytes = canonical_json(event)?;
    let json = String::from_utf8(bytes.clone())
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(&bytes);
    sqlx::query(
        "INSERT INTO evidence_frontier_repair_events (
            repair_id, event_index, event_kind, event_json, event_sha256,
            previous_event_sha256, observed_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&event.repair_id)
    .bind(to_i64(event.event_index, "frontier repair event index")?)
    .bind(event.event_kind.as_str())
    .bind(json)
    .bind(digest.as_str())
    .bind(event.previous_event_sha256.as_ref().map(Sha256Digest::as_str))
    .bind(to_i64(
        event.observed_at_unix_ms,
        "frontier repair event timestamp",
    )?)
    .execute(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

fn require_dispatch_fence(
    operation: &EvidenceFrontierRepairOperationV1,
    dispatch_token: &str,
) -> Result<(), EvidenceError> {
    if operation.dispatch_token.as_deref() != Some(dispatch_token) {
        return Err(invalid("frontier repair dispatch token is stale or mismatched"));
    }
    Ok(())
}

fn validate_repair_acknowledgement(
    operation: &EvidenceFrontierRepairOperationV1,
    acknowledgement: &EvidenceFrontierDurableAckV1,
) -> Result<(), EvidenceError> {
    if acknowledgement.store_id != operation.store_id
        || acknowledgement.frontier_generation != operation.target_frontier.frontier_generation
        || acknowledgement.frontier_sha256
            != operation.authorization.target_frontier_sha256
        || operation.backend_identity_sha256.as_ref()
            != Some(&acknowledgement.backend_identity_sha256)
        || acknowledgement.backend_identity_sha256
            != operation.target_frontier.backend_identity_sha256
        || acknowledgement.audit_sequence == 0
    {
        return Err(invalid(
            "frontier repair acknowledgement is not the exact authorized target",
        ));
    }
    Ok(())
}

fn validate_transition_input(
    repair_id: &str,
    dispatch_token: &str,
    now_unix_ms: u64,
) -> Result<(), EvidenceError> {
    StableId::new(repair_id.to_string())
        .map_err(|error| invalid(&format!("invalid frontier repair id: {error}")))?;
    StableId::new(dispatch_token.to_string())
        .map_err(|error| invalid(&format!("invalid frontier repair dispatch token: {error}")))?;
    if now_unix_ms == 0 {
        return Err(invalid("frontier repair transition timestamp must be positive"));
    }
    Ok(())
}


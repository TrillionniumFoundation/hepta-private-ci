impl HeptaEvidenceStore {
    /// Persist one exact signed repair transition and consume its authority
    /// nonce durably. Exact retries are idempotent; reusing the nonce for any
    /// different semantic object is an identity conflict.
    pub async fn prepare_frontier_repair(
        &self,
        authorization: &FrontierRepairAuthorizationV1,
        authority: &FrontierRepairAuthorityV1,
        current: &EvidenceRecoveryFrontierV2,
        target: &EvidenceRecoveryFrontierV2,
        now_unix_ms: u64,
    ) -> Result<EvidenceFrontierRepairOperationV1, EvidenceError> {
        if now_unix_ms == 0 {
            return Err(invalid("frontier repair preparation timestamp must be positive"));
        }
        if classify_frontier_merge(current, target) != FrontierMergeDecision::RepairRequired {
            return Err(invalid(
                "frontier repair ledger accepts only transitions classified RepairRequired",
            ));
        }
        verify_frontier_repair_authorization(
            authorization,
            authority,
            current,
            target,
            now_unix_ms,
        )?;

        let canonical = CanonicalRepair::new(authorization, authority, current, target)?;
        let repair_id = repair_id(&canonical.authorization_sha256);
        StableId::new(repair_id.clone()).map_err(|error| {
            invalid(&format!("invalid derived frontier repair id: {error}"))
        })?;
        let now = to_i64(now_unix_ms, "frontier repair preparation timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let enrolled_store = enrolled_store_id(&mut transaction).await?;
        if enrolled_store != authorization.store_id || current.store_id != enrolled_store {
            return Err(invalid(
                "frontier repair is not bound to the enrolled evidence store",
            ));
        }

        if let Some(row) = sqlx::query(
            "SELECT * FROM evidence_frontier_repairs
             WHERE authority_key_id = ? AND authority_key_epoch = ? AND nonce_hex = ?",
        )
        .bind(&authorization.authority_key_id)
        .bind(to_i64(
            authorization.authority_key_epoch,
            "frontier repair authority key epoch",
        )?)
        .bind(&authorization.nonce_hex)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?
        {
            let existing = decode_repair_row(&row)?;
            if existing.repair_id != repair_id
                || !operation_matches_canonical(&existing, &canonical)?
            {
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: format!(
                        "frontier-repair-nonce:{}:{}:{}",
                        authorization.authority_key_id,
                        authorization.authority_key_epoch,
                        authorization.nonce_hex
                    ),
                });
            }
            transaction.commit().await.map_err(classify_sqlx_error)?;
            return Ok(existing);
        }

        let unresolved: Option<String> = sqlx::query_scalar(
            "SELECT repair_id FROM evidence_frontier_repairs
             WHERE store_id = ? AND state IN ('prepared', 'dispatching', 'indeterminate')
             LIMIT 1",
        )
        .bind(&enrolled_store)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        if let Some(unresolved) = unresolved {
            return Err(EvidenceError::Unavailable(format!(
                "frontier repair {unresolved} must reach a terminal state before another repair is prepared"
            )));
        }

        sqlx::query(
            "INSERT INTO evidence_frontier_repairs (
                repair_id, store_id, state, nonce_hex, operator_principal_id,
                reason_code, authority_key_id, authority_key_epoch,
                trust_root_generation, current_generation, target_generation,
                current_frontier_sha256, target_frontier_sha256,
                current_frontier_json, current_frontier_json_sha256,
                target_frontier_json, target_frontier_json_sha256,
                authorization_json, authorization_sha256,
                authority_json, authority_sha256,
                dispatch_token, backend_identity_sha256, durable_audit_sequence,
                conflict_generation, conflict_frontier_sha256,
                created_at_ms, updated_at_ms
             ) VALUES (?, ?, 'prepared', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       NULL, NULL, NULL, NULL, NULL, ?, ?)",
        )
        .bind(&repair_id)
        .bind(&enrolled_store)
        .bind(&authorization.nonce_hex)
        .bind(&authorization.operator_principal_id)
        .bind(reason_code_str(authorization.reason_code))
        .bind(&authorization.authority_key_id)
        .bind(to_i64(
            authorization.authority_key_epoch,
            "frontier repair authority key epoch",
        )?)
        .bind(to_i64(
            authorization.trust_root_generation,
            "frontier repair trust-root generation",
        )?)
        .bind(to_i64(
            authorization.current_generation,
            "frontier repair current generation",
        )?)
        .bind(to_i64(
            authorization.target_generation,
            "frontier repair target generation",
        )?)
        .bind(authorization.current_frontier_sha256.as_str())
        .bind(authorization.target_frontier_sha256.as_str())
        .bind(&canonical.current_json)
        .bind(canonical.current_json_sha256.as_str())
        .bind(&canonical.target_json)
        .bind(canonical.target_json_sha256.as_str())
        .bind(&canonical.authorization_json)
        .bind(canonical.authorization_sha256.as_str())
        .bind(&canonical.authority_json)
        .bind(canonical.authority_sha256.as_str())
        .bind(now)
        .bind(now)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;

        append_event(
            &mut transaction,
            &EvidenceFrontierRepairEventV1 {
                schema_version: EVIDENCE_FRONTIER_REPAIR_EVENT_SCHEMA_VERSION,
                repair_id: repair_id.clone(),
                event_index: 1,
                event_kind: EvidenceFrontierRepairStateV1::Prepared,
                store_id: enrolled_store,
                nonce_hex: authorization.nonce_hex.clone(),
                current_frontier_sha256: authorization.current_frontier_sha256.clone(),
                target_frontier_sha256: authorization.target_frontier_sha256.clone(),
                dispatch_token: None,
                backend_identity_sha256: None,
                durable_audit_sequence: None,
                conflict_generation: None,
                conflict_frontier_sha256: None,
                observed_at_unix_ms: now_unix_ms,
                previous_event_sha256: None,
            },
        )
        .await?;
        let operation = load_repair_in_transaction(&mut transaction, &repair_id).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(operation)
    }

    /// Fence the sole external repair dispatch with one caller-generated stable
    /// token and one pinned backend identity. No later caller can substitute a
    /// different token or backend for the same operation.
    pub async fn begin_frontier_repair_dispatch(
        &self,
        repair_id: &str,
        dispatch_token: &str,
        backend_identity_sha256: &Sha256Digest,
        now_unix_ms: u64,
    ) -> Result<EvidenceFrontierRepairOperationV1, EvidenceError> {
        validate_transition_input(repair_id, dispatch_token, now_unix_ms)?;
        let now = to_i64(now_unix_ms, "frontier repair dispatch timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_repair_in_transaction(&mut transaction, repair_id).await?;
        if current.target_frontier.backend_identity_sha256 != *backend_identity_sha256 {
            return Err(invalid(
                "frontier repair dispatch backend is not the exact authorized target backend",
            ));
        }
        match current.state {
            EvidenceFrontierRepairStateV1::Prepared => {
                sqlx::query(
                    "UPDATE evidence_frontier_repairs
                     SET state = 'dispatching', dispatch_token = ?,
                         backend_identity_sha256 = ?, updated_at_ms = ?
                     WHERE repair_id = ? AND state = 'prepared'",
                )
                .bind(dispatch_token)
                .bind(backend_identity_sha256.as_str())
                .bind(now)
                .bind(repair_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
                append_transition_event(
                    &mut transaction,
                    &current,
                    EvidenceFrontierRepairStateV1::Dispatching,
                    Some(dispatch_token.to_string()),
                    Some(backend_identity_sha256.clone()),
                    None,
                    None,
                    None,
                    now_unix_ms,
                )
                .await?;
            }
            EvidenceFrontierRepairStateV1::Dispatching
                if current.dispatch_token.as_deref() == Some(dispatch_token)
                    && current.backend_identity_sha256.as_ref()
                        == Some(backend_identity_sha256) => {}
            _ => {
                return Err(invalid(
                    "frontier repair dispatch cannot replace an existing fence or terminal state",
                ));
            }
        }
        let result = load_repair_in_transaction(&mut transaction, repair_id).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn mark_frontier_repair_indeterminate(
        &self,
        repair_id: &str,
        dispatch_token: &str,
        now_unix_ms: u64,
    ) -> Result<EvidenceFrontierRepairOperationV1, EvidenceError> {
        validate_transition_input(repair_id, dispatch_token, now_unix_ms)?;
        let now = to_i64(now_unix_ms, "frontier repair indeterminate timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_repair_in_transaction(&mut transaction, repair_id).await?;
        require_dispatch_fence(&current, dispatch_token)?;
        match current.state {
            EvidenceFrontierRepairStateV1::Dispatching => {
                sqlx::query(
                    "UPDATE evidence_frontier_repairs
                     SET state = 'indeterminate', updated_at_ms = ?
                     WHERE repair_id = ? AND state = 'dispatching'",
                )
                .bind(now)
                .bind(repair_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
                append_transition_event(
                    &mut transaction,
                    &current,
                    EvidenceFrontierRepairStateV1::Indeterminate,
                    current.dispatch_token.clone(),
                    current.backend_identity_sha256.clone(),
                    None,
                    None,
                    None,
                    now_unix_ms,
                )
                .await?;
            }
            EvidenceFrontierRepairStateV1::Indeterminate => {}
            _ => return Err(invalid("only a dispatching repair may become indeterminate")),
        }
        let result = load_repair_in_transaction(&mut transaction, repair_id).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn acknowledge_frontier_repair(
        &self,
        repair_id: &str,
        dispatch_token: &str,
        acknowledgement: &EvidenceFrontierDurableAckV1,
        now_unix_ms: u64,
    ) -> Result<EvidenceFrontierRepairOperationV1, EvidenceError> {
        validate_transition_input(repair_id, dispatch_token, now_unix_ms)?;
        let now = to_i64(now_unix_ms, "frontier repair acknowledgement timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_repair_in_transaction(&mut transaction, repair_id).await?;
        require_dispatch_fence(&current, dispatch_token)?;
        validate_repair_acknowledgement(&current, acknowledgement)?;
        match current.state {
            EvidenceFrontierRepairStateV1::Dispatching
            | EvidenceFrontierRepairStateV1::Indeterminate => {
                sqlx::query(
                    "UPDATE evidence_frontier_repairs
                     SET state = 'acknowledged', durable_audit_sequence = ?, updated_at_ms = ?
                     WHERE repair_id = ? AND state IN ('dispatching', 'indeterminate')",
                )
                .bind(to_i64(
                    acknowledgement.audit_sequence,
                    "frontier repair durable audit sequence",
                )?)
                .bind(now)
                .bind(repair_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
                append_transition_event(
                    &mut transaction,
                    &current,
                    EvidenceFrontierRepairStateV1::Acknowledged,
                    current.dispatch_token.clone(),
                    current.backend_identity_sha256.clone(),
                    Some(acknowledgement.audit_sequence),
                    None,
                    None,
                    now_unix_ms,
                )
                .await?;
            }
            EvidenceFrontierRepairStateV1::Acknowledged
                if current.durable_audit_sequence == Some(acknowledgement.audit_sequence) => {}
            _ => return Err(invalid("frontier repair acknowledgement conflicts with terminal state")),
        }
        let result = load_repair_in_transaction(&mut transaction, repair_id).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn conflict_frontier_repair(
        &self,
        repair_id: &str,
        dispatch_token: &str,
        actual_generation: u64,
        actual_frontier_sha256: &Sha256Digest,
        now_unix_ms: u64,
    ) -> Result<EvidenceFrontierRepairOperationV1, EvidenceError> {
        validate_transition_input(repair_id, dispatch_token, now_unix_ms)?;
        if actual_generation == 0 {
            return Err(invalid("frontier repair conflict generation must be positive"));
        }
        let now = to_i64(now_unix_ms, "frontier repair conflict timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = load_repair_in_transaction(&mut transaction, repair_id).await?;
        require_dispatch_fence(&current, dispatch_token)?;
        match current.state {
            EvidenceFrontierRepairStateV1::Dispatching
            | EvidenceFrontierRepairStateV1::Indeterminate => {
                sqlx::query(
                    "UPDATE evidence_frontier_repairs
                     SET state = 'conflicted', conflict_generation = ?,
                         conflict_frontier_sha256 = ?, updated_at_ms = ?
                     WHERE repair_id = ? AND state IN ('dispatching', 'indeterminate')",
                )
                .bind(to_i64(actual_generation, "frontier repair conflict generation")?)
                .bind(actual_frontier_sha256.as_str())
                .bind(now)
                .bind(repair_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
                append_transition_event(
                    &mut transaction,
                    &current,
                    EvidenceFrontierRepairStateV1::Conflicted,
                    current.dispatch_token.clone(),
                    current.backend_identity_sha256.clone(),
                    None,
                    Some(actual_generation),
                    Some(actual_frontier_sha256.clone()),
                    now_unix_ms,
                )
                .await?;
            }
            EvidenceFrontierRepairStateV1::Conflicted
                if current.conflict_generation == Some(actual_generation)
                    && current.conflict_frontier_sha256.as_ref()
                        == Some(actual_frontier_sha256) => {}
            _ => return Err(invalid("frontier repair conflict differs from terminal state")),
        }
        let result = load_repair_in_transaction(&mut transaction, repair_id).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub async fn get_frontier_repair(
        &self,
        repair_id: &str,
    ) -> Result<Option<EvidenceFrontierRepairOperationV1>, EvidenceError> {
        StableId::new(repair_id.to_string())
            .map_err(|error| invalid(&format!("invalid frontier repair id: {error}")))?;
        let row = sqlx::query("SELECT * FROM evidence_frontier_repairs WHERE repair_id = ?")
            .bind(repair_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?;
        row.map(|row| decode_repair_row(&row)).transpose()
    }
}


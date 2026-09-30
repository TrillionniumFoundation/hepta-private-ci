use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;

use crate::ChangeKind;
use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::rand::random;

use super::sql::*;
use super::*;

impl MatrixDurableStore {
    /// Claim a bounded outbox batch and mint one random capability per record.
    ///
    /// The queue transition precedes capability publication. The second writer
    /// transaction rechecks the exact queue attempt and lease before minting a
    /// usable handle. A crash between transactions cannot enter the transport;
    /// the queue lease expires normally without resetting its attempt identity.
    pub async fn claim_outbox_fenced(
        &self,
        now_ms: u64,
        lease_ms: u64,
        limit: usize,
    ) -> Result<Vec<MatrixFencedOutboxClaim>, MatrixDurableError> {
        let records = self.claim_outbox(now_ms, lease_ms, limit).await?;
        if records.is_empty() {
            return Ok(Vec::new());
        }
        let mut claims = Vec::with_capacity(records.len());
        for record in records {
            let token = random::<[u8; CLAIM_TOKEN_BYTES]>();
            let token_sha256 = Sha256Digest::for_bytes(&token).as_str().to_string();
            let lease_until_ms = record.lease_until_ms.ok_or(MatrixDurableError::Corrupt)?;
            claims.push(MatrixFencedOutboxClaim {
                lease_epoch: record.attempts,
                claimed_at_ms: record.updated_at_ms,
                lease_until_ms,
                record,
                token,
                token_sha256,
            });
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        for claim in &claims {
            let identity = claim.identity();
            let current: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM outbox_messages
                 WHERE stable_txn_id = ? AND state = 'in_flight'
                   AND attempts = ? AND lease_until_ms = ? AND updated_at_ms = ?",
            )
            .bind(identity.stable_txn_id.as_str())
            .bind(to_i64(identity.attempt)?)
            .bind(to_i64(claim.lease_until_ms)?)
            .bind(to_i64(claim.claimed_at_ms)?)
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if current != 1 {
                return Err(MatrixDurableError::Conflict);
            }
            if let Some(previous) =
                active_claim_tx(&mut transaction, identity.stable_txn_id).await?
            {
                if previous.attempt >= identity.attempt
                    || previous.lease_until_ms > claim.claimed_at_ms
                {
                    return Err(MatrixDurableError::Conflict);
                }
                append_attempt_event_tx(
                    &mut transaction,
                    &previous.identity(),
                    MatrixDispatchAttemptEventKind::Expired,
                    /*failure_class*/ None,
                    /*retry_after_ms*/ None,
                    /*event_id*/ None,
                    claim.claimed_at_ms,
                )
                .await?;
                delete_active_claim_tx(&mut transaction, &previous.identity()).await?;
            }
            sqlx::query(
                "INSERT INTO matrix_dispatch_attempt_claims (
                    stable_txn_id, attempt, lease_epoch, claim_token_sha256,
                    claimed_at_ms, lease_until_ms
                 ) VALUES (?, ?, ?, ?, ?, ?)",
            )
            .bind(identity.stable_txn_id.as_str())
            .bind(to_i64(identity.attempt)?)
            .bind(to_i64(identity.lease_epoch)?)
            .bind(identity.token_sha256)
            .bind(to_i64(claim.claimed_at_ms)?)
            .bind(to_i64(claim.lease_until_ms)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            sqlx::query(
                "INSERT INTO matrix_dispatch_active_claims (
                    stable_txn_id, attempt, lease_epoch, claim_token_sha256,
                    phase, claimed_at_ms, lease_until_ms
                 ) VALUES (?, ?, ?, ?, 'claimed', ?, ?)",
            )
            .bind(identity.stable_txn_id.as_str())
            .bind(to_i64(identity.attempt)?)
            .bind(to_i64(identity.lease_epoch)?)
            .bind(identity.token_sha256)
            .bind(to_i64(claim.claimed_at_ms)?)
            .bind(to_i64(claim.lease_until_ms)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            append_attempt_event_tx(
                &mut transaction,
                &identity,
                MatrixDispatchAttemptEventKind::Claimed,
                /*failure_class*/ None,
                /*retry_after_ms*/ None,
                /*event_id*/ None,
                claim.claimed_at_ms,
            )
            .await?;
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(claims)
    }

    pub async fn record_outbox_prepared(
        &self,
        claim: &MatrixFencedOutboxClaim,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = claim.identity();
        require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        if attempt_event_exists_tx(
            &mut transaction,
            &identity,
            MatrixDispatchAttemptEventKind::Prepared,
        )
        .await?
        {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(());
        }
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            MatrixDispatchAttemptEventKind::Prepared,
            /*failure_class*/ None,
            /*retry_after_ms*/ None,
            /*event_id*/ None,
            recorded_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn record_outbox_authorized(
        &self,
        claim: &MatrixFencedOutboxClaim,
        witness: &MatrixOutboxAuthorityWitness,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        validate_witness(witness)?;
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = claim.identity();
        let active =
            require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        if active.phase == "dispatching" {
            return Err(MatrixDurableError::Conflict);
        }
        if active.phase == "authorized" {
            let existing = authority_witness_tx(&mut transaction, &identity).await?;
            if existing.as_ref() == Some(witness) {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(());
            }
            return Err(MatrixDurableError::Conflict);
        }
        sqlx::query(
            "INSERT INTO matrix_dispatch_authority_witnesses (
                stable_txn_id, attempt, lease_epoch, claim_token_sha256,
                authority_epoch, revocation_revision, grant_id,
                verified_use_witness_sha256, revocation_head_sha256,
                recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .bind(to_i64(identity.lease_epoch)?)
        .bind(identity.token_sha256)
        .bind(to_i64(witness.authority_epoch)?)
        .bind(to_i64(witness.revocation_revision)?)
        .bind(&witness.grant_id)
        .bind(&witness.verified_use_witness_sha256)
        .bind(&witness.revocation_head_sha256)
        .bind(to_i64(recorded_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let updated = sqlx::query(
            "UPDATE matrix_dispatch_active_claims SET phase = 'authorized'
             WHERE stable_txn_id = ? AND attempt = ? AND lease_epoch = ?
               AND claim_token_sha256 = ? AND phase = 'claimed'",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .bind(to_i64(identity.lease_epoch)?)
        .bind(identity.token_sha256)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            MatrixDispatchAttemptEventKind::Authorized,
            /*failure_class*/ None,
            /*retry_after_ms*/ None,
            /*event_id*/ None,
            recorded_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)
    }

    /// Publish dispatch intent under a live lease. The remaining duration is a
    /// pre-commit observation, not a renewed lease: callers must recompute their
    /// absolute deadline and check final-use authority after this await.
    pub async fn record_outbox_dispatching(
        &self,
        claim: &MatrixFencedOutboxClaim,
        recorded_at_ms: u64,
    ) -> Result<u64, MatrixDurableError> {
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = claim.identity();
        let active =
            require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        if active.phase == "claimed" {
            return Err(MatrixDurableError::Conflict);
        }
        if active.phase == "authorized" {
            let updated = sqlx::query(
                "UPDATE matrix_dispatch_active_claims SET phase = 'dispatching'
                 WHERE stable_txn_id = ? AND attempt = ? AND lease_epoch = ?
                   AND claim_token_sha256 = ? AND phase = 'authorized'",
            )
            .bind(identity.stable_txn_id.as_str())
            .bind(to_i64(identity.attempt)?)
            .bind(to_i64(identity.lease_epoch)?)
            .bind(identity.token_sha256)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if updated.rows_affected() != 1 {
                return Err(MatrixDurableError::Conflict);
            }
            append_attempt_event_tx(
                &mut transaction,
                &identity,
                MatrixDispatchAttemptEventKind::Dispatching,
                /*failure_class*/ None,
                /*retry_after_ms*/ None,
                /*event_id*/ None,
                recorded_at_ms,
            )
            .await?;
        }
        let remaining = active.lease_until_ms.saturating_sub(recorded_at_ms);
        transaction.commit().await.map_err(unavailable)?;
        Ok(remaining)
    }

    /// Persist the exact kernel proof that crossed its final revocation and
    /// expiry check before final Matrix adapter authorization entry.
    ///
    /// This API accepts the non-constructible `EnteredUseToken`, rather than a
    /// caller-filled digest, and binds it to the live random claim, canonical
    /// content pin, signed request and durable authority witness. Identical
    /// replay is idempotent; any semantic drift conflicts.
    pub async fn record_outbox_entered_use(
        &self,
        claim: &MatrixFencedOutboxClaim,
        proof: &EnteredUseToken,
        binding: &FinalUseBinding,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        if !proof.matches(binding) || binding.subject_id != self.owner_agent_id().as_str() {
            return Err(MatrixDurableError::AccessDenied);
        }
        let request_sha256 = hex_sha256(binding.request_sha256);
        let scope_sha256 = hex_sha256(binding.scope_sha256);
        let canonical_payload_sha256 = hex_sha256(binding.payload_sha256);
        let entered_use_witness_sha256 = hex_sha256(proof.witness_sha256());
        let identity = claim.identity();
        let operation_id = format!("matrix.send:{}", identity.stable_txn_id.as_str());

        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let active =
            require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        if active.phase != "dispatching" {
            return Err(MatrixDurableError::Conflict);
        }

        let existing: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_use_entries
             WHERE stable_txn_id = ? AND attempt = ?",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if existing != 0 {
            let identical: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM matrix_dispatch_use_entries
                 WHERE stable_txn_id = ? AND attempt = ? AND lease_epoch = ?
                   AND claim_token_sha256 = ? AND operation_id = ?
                   AND subject_id = ? AND destination_id = ?
                   AND request_sha256 = ? AND scope_sha256 = ?
                   AND canonical_payload_sha256 = ?
                   AND entered_use_witness_sha256 = ?",
            )
            .bind(identity.stable_txn_id.as_str())
            .bind(to_i64(identity.attempt)?)
            .bind(to_i64(identity.lease_epoch)?)
            .bind(identity.token_sha256)
            .bind(&operation_id)
            .bind(&binding.subject_id)
            .bind(&binding.destination_id)
            .bind(&request_sha256)
            .bind(&scope_sha256)
            .bind(&canonical_payload_sha256)
            .bind(&entered_use_witness_sha256)
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if identical == 1 {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(());
            }
            return Err(MatrixDurableError::Conflict);
        }

        let qualified: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)
             FROM matrix_dispatch_ledger AS dispatch
             JOIN matrix_dispatch_authority_claims AS authority_claim
               ON authority_claim.stable_txn_id = dispatch.stable_txn_id
              AND authority_claim.attempt = dispatch.attempts
             JOIN matrix_dispatch_authority_witnesses AS authority_witness
               ON authority_witness.stable_txn_id = dispatch.stable_txn_id
              AND authority_witness.attempt = dispatch.attempts
             JOIN matrix_dispatch_content_bindings AS content
               ON content.stable_txn_id = dispatch.stable_txn_id
             WHERE dispatch.stable_txn_id = ? AND dispatch.attempts = ?
               AND dispatch.operation_id = ?
               AND authority_claim.operation_id = dispatch.operation_id
               AND authority_claim.subject_id = ?
               AND authority_claim.destination_id = ?
               AND authority_claim.request_sha256 = ?
               AND authority_claim.scope_sha256 = ?
               AND authority_claim.payload_sha256 = dispatch.payload_sha256
               AND authority_claim.expires_at_ms > ?
               AND authority_witness.lease_epoch = ?
               AND authority_witness.claim_token_sha256 = ?
               AND authority_witness.authority_epoch = authority_claim.authority_epoch
               AND authority_witness.revocation_revision = authority_claim.revocation_revision
               AND authority_witness.grant_id = authority_claim.grant_id
               AND authority_witness.verified_use_witness_sha256 = ?
               AND content.scope_sha256 = ?
               AND content.canonical_content_sha256 = ?",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .bind(&operation_id)
        .bind(&binding.subject_id)
        .bind(&binding.destination_id)
        .bind(&request_sha256)
        .bind(&scope_sha256)
        .bind(to_i64(recorded_at_ms)?)
        .bind(to_i64(identity.lease_epoch)?)
        .bind(identity.token_sha256)
        .bind(&entered_use_witness_sha256)
        .bind(&scope_sha256)
        .bind(&canonical_payload_sha256)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if qualified != 1 {
            return Err(MatrixDurableError::Conflict);
        }

        sqlx::query(
            "INSERT INTO matrix_dispatch_use_entries (
                stable_txn_id, attempt, lease_epoch, claim_token_sha256,
                operation_id, subject_id, destination_id, request_sha256,
                scope_sha256, canonical_payload_sha256,
                entered_use_witness_sha256, entered_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .bind(to_i64(identity.lease_epoch)?)
        .bind(identity.token_sha256)
        .bind(&operation_id)
        .bind(&binding.subject_id)
        .bind(&binding.destination_id)
        .bind(&request_sha256)
        .bind(&scope_sha256)
        .bind(&canonical_payload_sha256)
        .bind(&entered_use_witness_sha256)
        .bind(to_i64(recorded_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn release_outbox_claim_canceled(
        &self,
        claim: &MatrixFencedOutboxClaim,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        self.retry_fenced_claim(
            claim,
            recorded_at_ms,
            recorded_at_ms,
            MatrixDispatchAttemptEventKind::Canceled,
            /*failure_class*/ None,
            /*retry_after_ms*/ None,
            /*event_id*/ None,
            /*require_dispatching*/ false,
        )
        .await
    }

    pub async fn release_outbox_claim_revoked(
        &self,
        claim: &MatrixFencedOutboxClaim,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        self.retry_fenced_claim(
            claim,
            recorded_at_ms,
            recorded_at_ms,
            MatrixDispatchAttemptEventKind::Revoked,
            Some(MatrixAttemptFailureClass::AuthorityDenied),
            /*retry_after_ms*/ None,
            /*event_id*/ None,
            /*require_dispatching*/ false,
        )
        .await
    }

    pub async fn finish_outbox_transport_accepted(
        &self,
        claim: &MatrixFencedOutboxClaim,
        event_id: &MatrixEventId,
        recorded_at_ms: u64,
        next_attempt_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        self.retry_fenced_claim(
            claim,
            recorded_at_ms,
            next_attempt_at_ms,
            MatrixDispatchAttemptEventKind::TransportAccepted,
            /*failure_class*/ None,
            /*retry_after_ms*/ None,
            Some(event_id),
            /*require_dispatching*/ true,
        )
        .await
    }

    pub async fn finish_outbox_indeterminate(
        &self,
        claim: &MatrixFencedOutboxClaim,
        failure_class: MatrixAttemptFailureClass,
        retry_after_ms: Option<u64>,
        recorded_at_ms: u64,
        next_attempt_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        self.retry_fenced_claim(
            claim,
            recorded_at_ms,
            next_attempt_at_ms,
            MatrixDispatchAttemptEventKind::Indeterminate,
            Some(failure_class),
            retry_after_ms,
            /*event_id*/ None,
            /*require_dispatching*/ true,
        )
        .await
    }

    pub async fn finish_outbox_permanently_rejected(
        &self,
        claim: &MatrixFencedOutboxClaim,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = claim.identity();
        // Completing an observation does not exercise send authority. Expiry
        // forbids a new send, but cannot erase an already observed outcome.
        // A superseding attempt still rejects this exact token/epoch below.
        let active = require_active_claim_identity_tx(&mut transaction, &identity).await?;
        if active.phase != "dispatching" || recorded_at_ms < active.claimed_at_ms {
            return Err(MatrixDurableError::Conflict);
        }
        let failed: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE stable_txn_id = ? AND attempts = ? AND state = 'failed'",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if failed != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        let updated = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'permanent_failure', lease_until_ms = NULL,
                 updated_at_ms = ?, sent_event_id = NULL
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(to_i64(recorded_at_ms)?)
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            MatrixDispatchAttemptEventKind::PermanentlyRejected,
            Some(MatrixAttemptFailureClass::Permanent),
            /*retry_after_ms*/ None,
            /*event_id*/ None,
            recorded_at_ms,
        )
        .await?;
        self.append_change(
            &mut transaction,
            ChangeKind::OutboxFailed,
            Some(&claim.record.room_id),
            /*event_id*/ None,
            Some(identity.stable_txn_id),
            recorded_at_ms,
        )
        .await?;
        delete_active_claim_tx(&mut transaction, &identity).await?;
        transaction.commit().await.map_err(unavailable)
    }

    /// Close an exact claim after a concurrently observed terminal ledger fact.
    /// Audit labels alone cannot invent terminality or replace the server event.
    pub async fn close_terminal_outbox_claim(
        &self,
        claim: &MatrixFencedOutboxClaim,
        kind: MatrixDispatchAttemptEventKind,
        event_id: Option<&MatrixEventId>,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        let expected_state = match kind {
            MatrixDispatchAttemptEventKind::Confirmed => "succeeded",
            MatrixDispatchAttemptEventKind::Redacted => "redacted",
            MatrixDispatchAttemptEventKind::PermanentlyRejected => "failed",
            _ => return Err(MatrixDurableError::Invalid),
        };
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = claim.identity();
        let terminal: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_dispatch_ledger
             WHERE stable_txn_id = ? AND terminal_event_id IS ?
               AND (state = ? OR (state = 'observed_unqualified'
                    AND ((? = 'succeeded' AND send_observation_sha256 IS NOT NULL)
                      OR (? = 'redacted' AND redaction_observation_sha256 IS NOT NULL))))",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(event_id.map(MatrixEventId::as_str))
        .bind(expected_state)
        .bind(expected_state)
        .bind(expected_state)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if terminal != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        if active_claim_tx(&mut transaction, identity.stable_txn_id)
            .await?
            .is_none()
        {
            if attempt_event_exists_tx(&mut transaction, &identity, kind).await? {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(());
            }
            return Err(MatrixDurableError::Conflict);
        }
        let active = require_active_claim_identity_tx(&mut transaction, &identity).await?;
        if recorded_at_ms < active.claimed_at_ms {
            return Err(MatrixDurableError::Conflict);
        }
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            kind,
            /*failure_class*/ None,
            /*retry_after_ms*/ None,
            event_id,
            recorded_at_ms,
        )
        .await?;
        delete_active_claim_tx(&mut transaction, &identity).await?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn dispatch_attempt_events(
        &self,
        txn_id: &MatrixTransactionId,
    ) -> Result<Vec<MatrixDispatchAttemptEvent>, MatrixDurableError> {
        let rows = sqlx::query(
            "SELECT event_seq, stable_txn_id, attempt, lease_epoch, event_kind,
                    failure_class, retry_after_ms, event_id, detail_sha256,
                    recorded_at_ms
             FROM matrix_dispatch_attempt_events
             WHERE stable_txn_id = ? ORDER BY event_seq",
        )
        .bind(txn_id.as_str())
        .fetch_all(self.sqlite_pool())
        .await
        .map_err(unavailable)?;
        rows.iter().map(attempt_event_from_row).collect()
    }

    #[allow(clippy::too_many_arguments)]
    async fn retry_fenced_claim(
        &self,
        claim: &MatrixFencedOutboxClaim,
        recorded_at_ms: u64,
        next_attempt_at_ms: u64,
        event_kind: MatrixDispatchAttemptEventKind,
        failure_class: Option<MatrixAttemptFailureClass>,
        retry_after_ms: Option<u64>,
        event_id: Option<&MatrixEventId>,
        require_dispatching: bool,
    ) -> Result<(), MatrixDurableError> {
        if next_attempt_at_ms < recorded_at_ms {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = claim.identity();
        // This is settlement/release, never a new effect admission. Even
        // after expiry, the exact active capability may record its outcome or
        // release an unentered claim. Reclaiming first changes the token and
        // attempt and makes this writer fail without touching the new owner.
        let active = require_active_claim_identity_tx(&mut transaction, &identity).await?;
        if recorded_at_ms < active.claimed_at_ms
            || (require_dispatching && active.phase != "dispatching")
        {
            return Err(MatrixDurableError::Conflict);
        }
        let updated = sqlx::query(
            "UPDATE outbox_messages
             SET state = 'retry_scheduled', next_attempt_at_ms = ?,
                 lease_until_ms = NULL, updated_at_ms = ?, sent_event_id = NULL
             WHERE stable_txn_id = ? AND state = 'in_flight' AND attempts = ?",
        )
        .bind(to_i64(next_attempt_at_ms)?)
        .bind(to_i64(recorded_at_ms)?)
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            event_kind,
            failure_class,
            retry_after_ms,
            event_id,
            recorded_at_ms,
        )
        .await?;
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            MatrixDispatchAttemptEventKind::RetryScheduled,
            failure_class,
            retry_after_ms,
            event_id,
            recorded_at_ms,
        )
        .await?;
        self.append_change(
            &mut transaction,
            ChangeKind::OutboxRetryScheduled,
            Some(&claim.record.room_id),
            event_id,
            Some(identity.stable_txn_id),
            recorded_at_ms,
        )
        .await?;
        delete_active_claim_tx(&mut transaction, &identity).await?;
        transaction.commit().await.map_err(unavailable)
    }
}

fn hex_sha256(value: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";

    let mut output = String::with_capacity(value.len() * 2);
    for byte in value {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

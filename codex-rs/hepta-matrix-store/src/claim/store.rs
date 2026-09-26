use rand::random;

use crate::ChangeKind;
use crate::MatrixDurableError;
use crate::MatrixDurableStore;

use super::sql::*;
use super::*;

impl MatrixDurableStore {
    /// Claim a bounded outbox batch and mint one random capability per record.
    ///
    /// `claim_outbox` performs the queue transition first. A crash before this
    /// function commits the capability rows cannot cross the network boundary;
    /// the ordinary outbox lease simply expires and is adopted by a later call.
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
            let lease_until_ms = record
                .lease_until_ms
                .ok_or(MatrixDurableError::Corrupt)?;
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
            if let Some(previous) = active_claim_tx(&mut transaction, identity.stable_txn_id).await?
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
                    None,
                    None,
                    None,
                    claim.claimed_at_ms,
                )
                .await?;
                let deleted = sqlx::query(
                    "DELETE FROM matrix_dispatch_active_claims
                     WHERE stable_txn_id = ? AND attempt = ?
                       AND lease_epoch = ? AND claim_token_sha256 = ?",
                )
                .bind(previous.stable_txn_id.as_str())
                .bind(to_i64(previous.attempt)?)
                .bind(to_i64(previous.lease_epoch)?)
                .bind(&previous.token_sha256)
                .execute(&mut *transaction)
                .await
                .map_err(unavailable)?;
                if deleted.rows_affected() != 1 {
                    return Err(MatrixDurableError::Conflict);
                }
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
                None,
                None,
                None,
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
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            MatrixDispatchAttemptEventKind::Prepared,
            None,
            None,
            None,
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
        let active = require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
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
            None,
            None,
            None,
            recorded_at_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)
    }

    /// Durably enter the local dispatching phase and return the exact remaining
    /// lease. The caller must refresh/revalidate final-use authority after this
    /// await and immediately before polling its lazy transport future.
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
        let active = require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        if recorded_at_ms >= active.lease_until_ms {
            return Err(MatrixDurableError::Conflict);
        }
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
                None,
                None,
                None,
                recorded_at_ms,
            )
            .await?;
        }
        let remaining = active.lease_until_ms.saturating_sub(recorded_at_ms);
        transaction.commit().await.map_err(unavailable)?;
        Ok(remaining)
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
            None,
            None,
            None,
            false,
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
            None,
            None,
            false,
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
            None,
            None,
            Some(event_id),
            true,
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
            None,
            true,
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
        let active =
            require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        if active.phase != "dispatching" {
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
            None,
            None,
            recorded_at_ms,
        )
        .await?;
        self.append_change(
            &mut transaction,
            ChangeKind::OutboxFailed,
            Some(&claim.record.room_id),
            None,
            Some(identity.stable_txn_id),
            recorded_at_ms,
        )
        .await?;
        delete_active_claim_tx(&mut transaction, &identity).await?;
        transaction.commit().await.map_err(unavailable)
    }

    /// Close a claim whose dispatch ledger became terminal concurrently. This
    /// never invents terminal truth; the supplied event kind is audit-only and
    /// the homeserver observation remains the authoritative ledger transition.
    pub async fn close_terminal_outbox_claim(
        &self,
        claim: &MatrixFencedOutboxClaim,
        kind: MatrixDispatchAttemptEventKind,
        event_id: Option<&MatrixEventId>,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        if !matches!(
            kind,
            MatrixDispatchAttemptEventKind::Confirmed
                | MatrixDispatchAttemptEventKind::Redacted
                | MatrixDispatchAttemptEventKind::PermanentlyRejected
                | MatrixDispatchAttemptEventKind::Canceled
        ) {
            return Err(MatrixDurableError::Invalid);
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let identity = claim.identity();
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
        require_active_claim_identity_tx(&mut transaction, &identity).await?;
        append_attempt_event_tx(
            &mut transaction,
            &identity,
            kind,
            None,
            None,
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
        let active =
            require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        if require_dispatching && active.phase != "dispatching" {
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

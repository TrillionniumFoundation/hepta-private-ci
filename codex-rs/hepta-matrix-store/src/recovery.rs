//! Persistent fair scheduling, not a second inbox or source of admission authority.
use super::*;

/// Select normal work or read-only reconciliation for an already emitted turn.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixRecoveryPurpose {
    Scheduled,
    Projection,
}

/// Safe, bounded reason codes. Remote error strings and payloads are not durable labels.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixRecoveryFailure {
    DependencyUnavailable,
    IdentityConflict,
    BindingUnrecoverable,
    InvalidInput,
}

impl MatrixRecoveryFailure {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::DependencyUnavailable => "dependency_unavailable",
            Self::IdentityConflict => "identity_conflict",
            Self::BindingUnrecoverable => "binding_unrecoverable",
            Self::InvalidInput => "invalid_input",
        }
    }
}

/// Result of one attempt. Quarantine never erases the underlying pending event.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixRecoveryDisposition {
    Ready,
    Retry(MatrixRecoveryFailure),
    Quarantine(MatrixRecoveryFailure),
}

impl MatrixDurableStore {
    /// Oldest *attempted* work moves behind unattempted work, including across restart.
    /// Only event IDs are selected; one payload is loaded at a time by the runtime.
    pub async fn due_inbox_recovery(
        &self,
        limit: usize,
        now_ms: u64,
    ) -> Result<Vec<MatrixEventId>, MatrixDurableError> {
        validate_limit(limit)?;
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT i.event_id FROM matrix_visible_inbox_events_v2 i
             LEFT JOIN matrix_inbox_recovery r ON r.event_id = i.event_id
             WHERE i.state = 'pending' AND (r.event_id IS NULL OR
                   (r.outcome != 'quarantined' AND r.next_attempt_at_ms <= ?))
             ORDER BY COALESCE(r.last_started_at_ms, 0), COALESCE(r.attempts, 0), i.inbox_cursor LIMIT ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(to_i64(limit as u64)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        ids.into_iter()
            .map(|id| MatrixEventId::parse(id).map_err(|_| MatrixDurableError::Corrupt))
            .collect()
    }

    /// Target only existing dispatches bound to this exact current thread.
    /// Quarantine is deliberately included in this inventory so the projector
    /// cannot confuse blocked reconciliation with an unrelated/ignorable turn.
    pub async fn inbox_recovery_for_thread(
        &self,
        thread_id: &str,
        limit: usize,
    ) -> Result<Vec<MatrixEventId>, MatrixDurableError> {
        validate_local_identity(thread_id)?;
        validate_limit(limit)?;
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT i.event_id FROM matrix_visible_inbox_events_v2 i
             JOIN matrix_actionable_inbox_dispatches_v2 d ON d.event_id = i.event_id
             JOIN room_threads t ON t.room_id = i.room_id
               AND t.binding_revision = i.binding_revision AND t.generation = i.generation
             LEFT JOIN matrix_inbox_recovery r ON r.event_id = i.event_id
             WHERE i.state = 'pending' AND d.state IN ('begun','queued','admitted')
               AND d.turn_id IS NULL AND t.thread_id = ?
               AND (d.thread_id IS NULL OR d.thread_id = t.thread_id)
             ORDER BY COALESCE(r.last_started_at_ms, 0), COALESCE(r.attempts, 0), i.inbox_cursor LIMIT ?",
        )
        .bind(thread_id)
        .bind(to_i64(limit as u64)?)
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        ids.into_iter()
            .map(|id| MatrixEventId::parse(id).map_err(|_| MatrixDurableError::Corrupt))
            .collect()
    }

    /// Reserve scheduling before a cancellable call. A dropped task leaves the
    /// SAME event/client identity delayed, never marked absent or completed.
    /// Projection may bypass retry delay, but never durable quarantine; its
    /// runtime caller is constrained to ReconcileOnly, not fresh admission.
    pub async fn begin_inbox_recovery(
        &self,
        event_id: &MatrixEventId,
        purpose: MatrixRecoveryPurpose,
        now_ms: u64,
    ) -> Result<Option<u64>, MatrixDurableError> {
        let now = to_i64(now_ms)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let visible: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM matrix_visible_inbox_events_v2
             WHERE event_id = ? AND state = 'pending')",
        )
        .bind(event_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        if !visible {
            return Ok(None);
        }
        let previous = sqlx::query(
            "SELECT attempts, last_started_at_ms, next_attempt_at_ms, outcome
             FROM matrix_inbox_recovery WHERE event_id = ?",
        )
        .bind(event_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        let attempt = match previous {
            Some(row) => {
                let outcome: String = row.try_get("outcome").map_err(unavailable)?;
                let next: i64 = row.try_get("next_attempt_at_ms").map_err(unavailable)?;
                let started: i64 = row.try_get("last_started_at_ms").map_err(unavailable)?;
                if outcome == "quarantined"
                    || now < started
                    || (purpose == MatrixRecoveryPurpose::Scheduled && now < next)
                {
                    return Ok(None);
                }
                let attempts: i64 = row.try_get("attempts").map_err(unavailable)?;
                attempts.checked_add(1).ok_or(MatrixDurableError::Corrupt)?
            }
            None => 1,
        };
        sqlx::query(
            "INSERT INTO matrix_inbox_recovery
             (event_id, attempts, last_started_at_ms, next_attempt_at_ms, outcome, failure_class)
             VALUES (?, ?, ?, ?, 'running', NULL)
             ON CONFLICT(event_id) DO UPDATE SET attempts=excluded.attempts,
               last_started_at_ms=excluded.last_started_at_ms,
               next_attempt_at_ms=excluded.next_attempt_at_ms,
               outcome='running', failure_class=NULL",
        )
        .bind(event_id.as_str())
        .bind(attempt)
        .bind(now)
        .bind(now.saturating_add(30_000))
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(Some(to_u64(attempt)?))
    }

    /// CAS prevents a late completion from changing a newer scheduling attempt.
    pub async fn finish_inbox_recovery(
        &self,
        event_id: &MatrixEventId,
        attempt: u64,
        disposition: MatrixRecoveryDisposition,
        next_attempt_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        let (outcome, failure) = match disposition {
            MatrixRecoveryDisposition::Ready => ("ready", None),
            MatrixRecoveryDisposition::Retry(reason) => ("retry", Some(reason.as_str())),
            MatrixRecoveryDisposition::Quarantine(reason) => ("quarantined", Some(reason.as_str())),
        };
        let updated = sqlx::query(
            "UPDATE matrix_inbox_recovery SET outcome=?, failure_class=?, next_attempt_at_ms=?
             WHERE event_id=? AND attempts=? AND outcome='running'
               AND last_started_at_ms <= ?",
        )
        .bind(outcome)
        .bind(failure)
        .bind(to_i64(next_attempt_at_ms)?)
        .bind(event_id.as_str())
        .bind(to_i64(attempt)?)
        .bind(to_i64(next_attempt_at_ms)?)
        .execute(&self.pool)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        Ok(())
    }
}

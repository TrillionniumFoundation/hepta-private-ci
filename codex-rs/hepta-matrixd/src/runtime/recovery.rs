//! Fair, bounded recovery. Budgets are cooperative at safe event boundaries:
//! never cancel an ambiguous bridge admission merely to satisfy a latency SLO.
use std::time::Duration;

use codex_hepta_matrix_store::MatrixRecoveryDisposition;
use codex_hepta_matrix_store::MatrixRecoveryFailure;
use codex_hepta_matrix_store::MatrixRecoveryPurpose;
use tokio::time::Instant;

use super::telemetry::GateKind;
use super::*;

#[derive(Clone, Debug)]
pub struct MatrixRecoveryPolicy {
    pub max_batch: usize,
    pub pass_budget: Duration,
}

impl Default for MatrixRecoveryPolicy {
    fn default() -> Self {
        Self {
            max_batch: 64,
            pass_budget: Duration::from_millis(250),
        }
    }
}

impl<B: MatrixRuntimeBridge> MatrixRuntime<B> {
    pub async fn recover_pending(
        &self,
        limit: usize,
        now_ms: u64,
    ) -> Result<MatrixRuntimeRecovery, MatrixRuntimeError> {
        if limit == 0 {
            return Err(MatrixRuntimeError::Invalid(
                "recovery limit must be non-zero".to_string(),
            ));
        }
        let started = Instant::now();
        let ids = self
            .store
            .due_inbox_recovery(limit.min(self.recovery_policy.max_batch), now_ms)
            .await?;
        let mut report = MatrixRuntimeRecovery::default();
        for id in ids {
            if started.elapsed() >= self.recovery_policy.pass_budget {
                report.budget_exhausted = true;
                break;
            }
            let acquired = tokio::time::timeout_at(
                started + self.recovery_policy.pass_budget,
                self.telemetry.acquire(&self.operation, GateKind::Admission),
            )
            .await;
            let operation = match acquired {
                Ok(operation) => operation?,
                Err(_) => {
                    report.budget_exhausted = true;
                    break;
                }
            };
            // Semaphore waiting is cancel-safe. Once acquired, finish this
            // event or use the bridge's existing timeout/uncertainty contract.
            let at_ms = now_ms
                .saturating_add(u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX));
            match self
                .recover_one_locked(&id, MatrixRecoveryPurpose::Scheduled, at_ms)
                .await
            {
                Ok(Some(outcome)) => report.outcomes.push(outcome),
                Ok(None) => report.deferred = report.deferred.saturating_add(1),
                Err(error) => match recovery_disposition(&error) {
                    Some(MatrixRecoveryDisposition::Quarantine(_)) => report.quarantined += 1,
                    Some(MatrixRecoveryDisposition::Retry(_)) => report.deferred += 1,
                    Some(MatrixRecoveryDisposition::Ready) | None => return Err(error),
                },
            }
            drop(operation);
            tokio::task::yield_now().await;
        }
        Ok(report)
    }

    pub(super) async fn recover_one_locked(
        &self,
        id: &MatrixEventId,
        purpose: MatrixRecoveryPurpose,
        now_ms: u64,
    ) -> Result<Option<MatrixDispatchOutcome>, MatrixRuntimeError> {
        let Some(attempt) = self
            .store
            .begin_inbox_recovery(id, purpose, now_ms)
            .await
            .map_err(MatrixRuntimeError::RecoveryPersistence)?
        else {
            return Ok(None);
        };
        let result = async {
            let inbox = self
                .store
                .inbox(id)
                .await?
                .ok_or(MatrixRuntimeError::MissingInbox)?;
            self.process_inbox_locked(&inbox, purpose, now_ms).await
        }
        .await;
        let (disposition, next) = match &result {
            Ok(_) => (MatrixRecoveryDisposition::Ready, now_ms),
            Err(error) => {
                let Some(disposition) = recovery_disposition(error) else {
                    return result.map(Some);
                };
                let delay = 1_000_u64.saturating_mul(1_u64 << attempt.min(6));
                (
                    disposition,
                    now_ms.saturating_add(delay).min(i64::MAX as u64),
                )
            }
        };
        // Failure to persist the disposition is a STORE error: stop the owner,
        // do not pretend this attempt has been safely isolated or rescheduled.
        self.store
            .finish_inbox_recovery(id, attempt, disposition, next)
            .await
            .map_err(MatrixRuntimeError::RecoveryPersistence)?;
        result.map(Some)
    }

    pub(super) async fn dispatch_for_projection(
        &self,
        event: &ProjectableEvent,
        now_ms: u64,
    ) -> Result<Option<InboxDispatchRecord>, MatrixRuntimeError> {
        if let Some(dispatch) = self
            .store
            .inbox_dispatch_for_turn(event.thread_id(), event.turn_id())
            .await?
        {
            return Ok(Some(dispatch));
        }
        let _operation = self
            .telemetry
            .acquire(&self.operation, GateKind::Admission)
            .await?;
        // Re-read after waiting: an in-flight normal admission may have finished.
        if let Some(dispatch) = self
            .store
            .inbox_dispatch_for_turn(event.thread_id(), event.turn_id())
            .await?
        {
            return Ok(Some(dispatch));
        }
        let started = Instant::now();
        let ids = self
            .store
            .inbox_recovery_for_thread(event.thread_id(), self.recovery_policy.max_batch)
            .await?;
        let had_candidates = !ids.is_empty();
        for id in ids {
            if started.elapsed() >= self.recovery_policy.pass_budget {
                break;
            }
            let result = self
                .recover_one_locked(&id, MatrixRecoveryPurpose::Projection, now_ms)
                .await;
            if let Err(error) = result
                && recovery_disposition(&error).is_none()
            {
                return Err(error);
            }
            if let Some(dispatch) = self
                .store
                .inbox_dispatch_for_turn(event.thread_id(), event.turn_id())
                .await?
            {
                return Ok(Some(dispatch));
            }
        }
        if had_candidates {
            // Stop this runtime generation visibly rather than acknowledge an
            // unassociated output or create a new submission. No replay or
            // successful projection is implied by this error.
            return Err(MatrixRuntimeError::ProjectionPending);
        }
        Ok(None)
    }
}

fn recovery_disposition(error: &MatrixRuntimeError) -> Option<MatrixRecoveryDisposition> {
    use MatrixRecoveryDisposition::{Quarantine, Retry};
    use MatrixRecoveryFailure::{
        BindingUnrecoverable, DependencyUnavailable, IdentityConflict, InvalidInput,
    };
    match error {
        MatrixRuntimeError::IdentityConflict
        | MatrixRuntimeError::Store(MatrixDurableError::Conflict)
        | MatrixRuntimeError::StoreOperation {
            source: MatrixDurableError::Conflict,
            ..
        } => Some(Quarantine(IdentityConflict)),
        MatrixRuntimeError::Store(MatrixDurableError::AccessDenied)
        | MatrixRuntimeError::StoreOperation {
            source: MatrixDurableError::AccessDenied,
            ..
        }
        | MatrixRuntimeError::Bridge(MatrixBridgeError::Protocol(_)) => {
            Some(Quarantine(BindingUnrecoverable))
        }
        MatrixRuntimeError::Bridge(MatrixBridgeError::AppServer(_) | MatrixBridgeError::Io(_)) => {
            Some(Retry(DependencyUnavailable))
        }
        MatrixRuntimeError::Bridge(MatrixBridgeError::Invalid(_)) => Some(Quarantine(InvalidInput)),
        // Store corruption, unavailable persistence, protocol invariants and
        // Agentd lifecycle/owner errors cannot safely be hidden as a bad event.
        _ => None,
    }
}

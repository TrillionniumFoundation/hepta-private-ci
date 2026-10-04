//! Bounded fair read-only lookup scheduling. No scheduling choice authorizes replay.
use crate::ledger::{OperationState, OperationView};
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RecoveryMetrics {
    pub observations: u64,
    pub failures: u64,
    pub last_batch_duration_ms: u64,
    pub max_lookup_wait_ms: u64,
    pub deferred_by_backoff: u64,
    pub backoff_entries: usize,
    pub next_eligible_at: Option<u64>,
}

#[derive(Debug, Default)]
pub struct RecoveryScheduler {
    cursor: Option<String>,
    backoff: BTreeMap<String, (u32, u64)>,
    visited: BTreeMap<String, u64>,
    metrics: RecoveryMetrics,
}

impl RecoveryScheduler {
    pub fn select(&mut self, operations: &[OperationView], now: u64) -> Vec<String> {
        let live: BTreeSet<_> = operations
            .iter()
            .filter(|op| op.state != OperationState::Submitting)
            .map(|op| op.operation_id.clone())
            .collect();
        self.backoff.retain(|id, _| live.contains(id));
        self.visited.retain(|id, _| live.contains(id));
        let mut ids: Vec<_> = live.into_iter().collect();
        if let Some(cursor) = &self.cursor {
            let index = ids.iter().position(|id| id > cursor).unwrap_or(0);
            ids.rotate_left(index);
        }
        let mut selected = Vec::new();
        for id in ids {
            if self.backoff.get(&id).is_some_and(|(_, next)| *next > now) {
                self.metrics.deferred_by_backoff =
                    self.metrics.deferred_by_backoff.saturating_add(1);
                continue;
            }
            if selected.len() == 32 {
                break;
            }
            let created = operations
                .iter()
                .find(|op| op.operation_id == id)
                .map(|op| op.created_at)
                .unwrap_or(now);
            self.metrics.max_lookup_wait_ms = self
                .metrics
                .max_lookup_wait_ms
                .max(now.saturating_sub(*self.visited.get(&id).unwrap_or(&created)));
            self.visited.insert(id.clone(), now);
            self.cursor = Some(id.clone());
            selected.push(id);
        }
        selected
    }

    pub fn observed(&mut self, id: &str, state: OperationState, now: u64) {
        self.metrics.observations = self.metrics.observations.saturating_add(1);
        if state == OperationState::Terminal {
            self.backoff.remove(id);
        } else {
            self.defer(id, now);
        }
    }
    pub fn failed(&mut self, id: &str, now: u64) {
        self.metrics.failures = self.metrics.failures.saturating_add(1);
        self.defer(id, now);
    }
    fn defer(&mut self, id: &str, now: u64) {
        let attempts = self
            .backoff
            .get(id)
            .map(|(attempts, _)| attempts.saturating_add(1))
            .unwrap_or(1);
        let delay = 1000_u64
            .saturating_mul(1_u64 << attempts.saturating_sub(1).min(6))
            .min(60_000);
        self.backoff
            .insert(id.to_owned(), (attempts, now.saturating_add(delay)));
    }
    pub fn batch_finished(&mut self, started: u64, now: u64) {
        self.metrics.last_batch_duration_ms = now.saturating_sub(started);
    }
    pub fn metrics(&self) -> RecoveryMetrics {
        RecoveryMetrics {
            backoff_entries: self.backoff.len(),
            next_eligible_at: self.backoff.values().map(|(_, time)| *time).min(),
            ..self.metrics.clone()
        }
    }
}

/// Read timeouts are per-record backoff; only authenticated-session loss aborts the batch.
pub fn is_fatal_recovery_error(error: &crate::error::ControlError) -> bool {
    use crate::error::ErrorCode;
    matches!(
        error.code,
        ErrorCode::NotConnected
            | ErrorCode::SessionExpired
            | ErrorCode::SessionRevoked
            | ErrorCode::SessionIdentityChanged
            | ErrorCode::PermissionDenied
            | ErrorCode::StalePermissionRevision
            | ErrorCode::ProtocolMismatch
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::{ControlError, ErrorCode};

    #[test]
    fn individual_lookup_timeout_backs_off_without_aborting_session() {
        assert!(!is_fatal_recovery_error(
            &ControlError::new(ErrorCode::Aborted).with_dispatch(true)
        ));
        assert!(!is_fatal_recovery_error(
            &ControlError::new(ErrorCode::Transport).with_dispatch(true)
        ));
        assert!(is_fatal_recovery_error(&ControlError::new(
            ErrorCode::SessionExpired
        )));
        assert!(is_fatal_recovery_error(&ControlError::new(
            ErrorCode::PermissionDenied
        )));
    }
}

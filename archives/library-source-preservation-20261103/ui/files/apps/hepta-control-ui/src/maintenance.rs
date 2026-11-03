//! Bounded explicit scheduling; the caller owns timers and cancellation.
use crate::ledger::{OperationState, OperationView};
use crate::{ControlError, ErrorCode, Result};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Default)]
pub struct SessionSchedule {
    failures: u32,
}
impl SessionSchedule {
    pub fn succeeded(&mut self) {
        self.failures = 0;
    }
    pub fn failed(&mut self) {
        self.failures = self.failures.saturating_add(1);
    }
    pub fn delay_ms(&self, expires: u64, now: u64) -> u64 {
        let remaining = expires.saturating_sub(now);
        let desired = if self.failures == 0 {
            remaining.saturating_sub(60_000).max(1000)
        } else {
            1000_u64
                .saturating_mul(1_u64 << self.failures.saturating_sub(1).min(6))
                .min(60_000)
        };
        desired.min(remaining).min(2_147_000_000)
    }
}

#[derive(Default)]
pub struct RecoverySchedule {
    cursor: Option<String>,
    backoff: BTreeMap<String, (u32, u64)>,
}
impl RecoverySchedule {
    pub fn select(
        &mut self,
        operations: &[OperationView],
        now: u64,
        limit: usize,
    ) -> Result<Vec<String>> {
        if limit == 0 || limit > 128 || operations.len() > 4096 {
            return Err(ControlError::new(ErrorCode::InvalidInput));
        }
        let mut ids: Vec<_> = operations
            .iter()
            .filter(|view| view.state != OperationState::Submitting)
            .map(|view| view.operation_id.clone())
            .collect();
        ids.sort();
        for id in &ids {
            crate::canonical::assert_stable_identifier(id)?;
        }
        if ids.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(ControlError::new(ErrorCode::InvalidInput));
        }
        let live: BTreeSet<_> = ids.iter().cloned().collect();
        self.backoff.retain(|id, _| live.contains(id));
        let index = self
            .cursor
            .as_ref()
            .and_then(|cursor| ids.iter().position(|id| id > cursor))
            .unwrap_or(0);
        ids.rotate_left(index);
        let selected: Vec<_> = ids
            .into_iter()
            .filter(|id| self.backoff.get(id).is_none_or(|(_, when)| *when <= now))
            .take(limit)
            .collect();
        if let Some(last) = selected.last() {
            self.cursor = Some(last.clone());
        }
        Ok(selected)
    }
    pub fn record(&mut self, id: &str, now: u64, terminal: bool) -> Result<()> {
        crate::canonical::assert_stable_identifier(id)?;
        if terminal {
            self.backoff.remove(id);
            return Ok(());
        }
        if !self.backoff.contains_key(id) && self.backoff.len() >= 4096 {
            return Err(ControlError::new(ErrorCode::PendingLimit));
        }
        let attempt = self
            .backoff
            .get(id)
            .map_or(1, |(attempt, _)| attempt.saturating_add(1));
        let delay = 1000_u64
            .saturating_mul(1_u64 << attempt.saturating_sub(1).min(6))
            .min(60_000);
        self.backoff
            .insert(id.into(), (attempt, now.saturating_add(delay)));
        Ok(())
    }
}

#[cfg(test)]
#[path = "maintenance_tests.rs"]
mod tests;

//! Conserved work reservations. Unknown work never returns its reservation.

use std::collections::BTreeMap;

use serde::Serialize;

use crate::TaskFlowError;
use crate::circuit_profile::invalid;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitBudgetV2 {
    limit: u64,
    spent: u64,
    reservations: BTreeMap<u64, u64>,
}

impl CircuitBudgetV2 {
    pub(crate) fn new(limit: u64) -> Self {
        Self { limit, spent: 0, reservations: BTreeMap::new() }
    }

    pub fn spent(&self) -> u64 { self.spent }

    pub fn reserved(&self) -> u64 { self.reservations.values().sum() }

    pub fn available(&self) -> u64 { self.limit - self.spent - self.reserved() }

    pub(crate) fn reserve(&mut self, id: u64, amount: u64) -> Result<(), TaskFlowError> {
        if amount == 0 || self.reservations.contains_key(&id) || amount > self.available() {
            return Err(invalid("work reservation exceeds available budget or repeats identity"));
        }
        self.reservations.insert(id, amount);
        Ok(())
    }

    pub(crate) fn settle(&mut self, id: u64, actual_work: u64) -> Result<(), TaskFlowError> {
        let reserved = *self.reservations.get(&id).ok_or_else(|| invalid("missing work reservation"))?;
        if actual_work > reserved {
            return Err(invalid("actual work exceeds admitted reservation"));
        }
        self.spent = self.spent.checked_add(actual_work).ok_or_else(|| invalid("work charge overflow"))?;
        self.reservations.remove(&id);
        Ok(())
    }
}
